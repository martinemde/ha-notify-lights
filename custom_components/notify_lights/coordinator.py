"""Central coordinator for Notify Lights.

Tracks per-target active notification stacks, resolves entity IDs to device
info, matches adapters from the registry, and dispatches render calls.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from .active_set import ActiveEntry, compute_active_set
from .adapter import AdapterRegistry
from .notification import Notification

_LOGGER = logging.getLogger(__name__)

# (Notification, pool_entry_id, activated_at)
StackEntry = tuple[Notification, str, float]

# HA light brightness scale. A ceiling of 255 applies no dimming.
MAX_CEILING = 255


@dataclass(frozen=True)
class TransportGroup:
    """One adapter-native group target and its concrete HA members."""

    name: str
    target: str
    members: frozenset[str]


class NotifyLightsCoordinator:
    """Coordinate notifications across targets and adapters.

    Holds the AdapterRegistry, tracks per-target notification stacks,
    resolves target references to entity IDs, looks up device info from HA
    registries, and dispatches render calls to matched adapters.
    """

    def __init__(
        self,
        hass,
        adapter_registry: AdapterRegistry,
        entity_registry,
        device_registry,
    ) -> None:
        self._hass = hass
        self._adapter_registry = adapter_registry
        self._entity_registry = entity_registry
        self._device_registry = device_registry
        self._stacks: dict[str, list[StackEntry]] = {}
        self._warned_targets: set[str] = set()
        self._transport_groups: dict[str, list[TransportGroup]] = {}
        # One config entry's own notifications, independent of physical
        # targets. Powers each entry's group light entity: its brightness is
        # a ceiling applied to every notification that entry activates, and
        # its on/off/color/effect mirror whichever of its own notifications
        # is currently top priority.
        self._entry_active: dict[str, list[tuple[Notification, float]]] = {}
        self._entry_listeners: dict[
            str, list[Callable[[], Awaitable[None] | None]]
        ] = {}
        self._ceilings: dict[str, int] = {}

    def register_transport_groups(
        self, owner_id: str, groups: list[TransportGroup]
    ) -> None:
        """Register adapter-native groups owned by one config entry."""
        self._transport_groups[owner_id] = groups
        for group in groups:
            _LOGGER.info(
                "Registered transport group %s (%s) with %d members",
                group.name,
                group.target,
                len(group.members),
            )

    def unregister_transport_groups(self, owner_id: str) -> None:
        """Remove adapter-native groups owned by one config entry."""
        self._transport_groups.pop(owner_id, None)

    def supported_targets(self, targets: list[str]) -> list[str]:
        """Keep one concrete entity for each adapter-supported device.

        Area and device selectors naturally include ordinary lights alongside
        notification-capable switches. Filtering here lets selectors stay
        semantic (for example, ``area: kitchen``) while the adapter registry
        decides which physical devices can render a notification.
        """
        chosen: dict[str, str] = {}
        for entity_id in targets:
            entity_entry = self._entity_registry.async_get(entity_id)
            if entity_entry is None or entity_entry.device_id is None:
                _LOGGER.debug("Ignoring target without a device: %s", entity_id)
                continue

            device_entry = self._device_registry.async_get(entity_entry.device_id)
            if device_entry is None:
                _LOGGER.debug("Ignoring target with missing device: %s", entity_id)
                continue

            adapter = self._adapter_registry.get_adapter(
                device_entry.manufacturer or "", device_entry.model or ""
            )
            if adapter is None:
                _LOGGER.debug(
                    "Ignoring target without a notification adapter: %s", entity_id
                )
                continue

            existing = chosen.get(entity_entry.device_id)
            if existing is None or (
                entity_id.startswith("light.") and not existing.startswith("light.")
            ):
                chosen[entity_entry.device_id] = entity_id

        return sorted(chosen.values())

    async def async_activate(
        self, notification: Notification, targets: list[str], pool_entry_id: str
    ) -> None:
        """Add notification to each target's stack and re-render."""
        activated_at = time.monotonic()
        _LOGGER.info(
            "Activating %s (pool=%s) on %d targets: %s",
            notification.name,
            pool_entry_id,
            len(targets),
            targets,
        )
        # Announce on the entry first. Its light entity turns itself on through
        # a real `light.turn_on`, which is what gives Adaptive Lighting a chance
        # to set the ceiling. Do that before the stacks change so the render
        # below is the first one, and already at the adapted brightness.
        await self._async_set_entry_notification(
            pool_entry_id, notification, activated_at
        )
        changed_targets = set(targets)
        for target in changed_targets:
            stack = self._stacks.setdefault(target, [])
            # Services and startup restoration may activate an already-active
            # switch. Replace its old entry instead of growing duplicates.
            stack[:] = [
                (n, pid, timestamp)
                for n, pid, timestamp in stack
                if not (n.name == notification.name and pid == pool_entry_id)
            ]
            stack.append((notification, pool_entry_id, activated_at))
        await self._render_targets(changed_targets)

    async def async_deactivate(
        self, notification: Notification, targets: list[str], pool_entry_id: str
    ) -> None:
        """Remove notification from each target's stack and re-render."""
        _LOGGER.info(
            "Deactivating %s (pool=%s) on %d targets: %s",
            notification.name,
            pool_entry_id,
            len(targets),
            targets,
        )
        changed_targets = set(targets)
        for target in changed_targets:
            stack = self._stacks.get(target, [])
            self._stacks[target] = [
                (n, pid, t)
                for n, pid, t in stack
                if not (n.name == notification.name and pid == pool_entry_id)
            ]
        await self._async_clear_entry_notification(pool_entry_id, notification)
        await self._render_targets(changed_targets)

    async def async_deactivate_entry(self, pool_entry_id: str) -> None:
        """Remove every active notification owned by one config entry."""
        changed_targets = self._remove_entry_from_stacks(pool_entry_id)
        self._entry_active.pop(pool_entry_id, None)
        self._ceilings.pop(pool_entry_id, None)
        self._entry_listeners.pop(pool_entry_id, None)
        _LOGGER.info(
            "Deactivated entry %s on %d targets",
            pool_entry_id,
            len(changed_targets),
        )
        await self._render_targets(changed_targets)

    async def async_clear_entry_notifications(self, pool_entry_id: str) -> None:
        """Deactivate every notification currently active for one entry.

        Used when a catalog's brightness light turns off. A ceiling of zero
        alone mutes rendering but leaves the entry's notifications occupying
        their priority slots in the stack, which can keep a lower-priority
        notification from another catalog from showing through. Clearing
        frees those slots outright. Unlike `async_deactivate_entry`, the
        entry's ceiling and listener registrations survive -- this entry can
        still be reactivated (and stay muted, if it was) rather than torn
        down.
        """
        changed_targets = self._remove_entry_from_stacks(pool_entry_id)
        self._entry_active[pool_entry_id] = []
        _LOGGER.info(
            "Cleared entry %s notifications on %d targets",
            pool_entry_id,
            len(changed_targets),
        )
        await self._async_notify_entry_listeners(pool_entry_id)
        await self._render_targets(changed_targets)

    def _remove_entry_from_stacks(self, pool_entry_id: str) -> set[str]:
        """Remove one entry's entries from every physical target's stack."""
        changed_targets: set[str] = set()
        for target, stack in self._stacks.items():
            kept = [entry for entry in stack if entry[1] != pool_entry_id]
            if len(kept) != len(stack):
                self._stacks[target] = kept
                changed_targets.add(target)
        return changed_targets

    async def _async_set_entry_notification(
        self, pool_entry_id: str, notification: Notification, activated_at: float
    ) -> None:
        """Track one entry's own active notification and notify listeners."""
        entries = self._entry_active.setdefault(pool_entry_id, [])
        entries[:] = [(n, t) for n, t in entries if n.name != notification.name]
        entries.append((notification, activated_at))
        await self._async_notify_entry_listeners(pool_entry_id)

    async def _async_clear_entry_notification(
        self, pool_entry_id: str, notification: Notification
    ) -> None:
        """Stop tracking one entry's notification and notify listeners."""
        entries = self._entry_active.get(pool_entry_id)
        if entries is None:
            return
        entries[:] = [(n, t) for n, t in entries if n.name != notification.name]
        await self._async_notify_entry_listeners(pool_entry_id)

    async def _async_notify_entry_listeners(self, pool_entry_id: str) -> None:
        """Run each entry listener, awaiting the ones that return a coroutine.

        The light entity's listener turns itself on through the `light.turn_on`
        service, so activation has to be able to wait for it.
        """
        for listener in list(self._entry_listeners.get(pool_entry_id, [])):
            result = listener()
            if result is not None:
                await result

    def entry_active_set(self, pool_entry_id: str) -> list[ActiveEntry]:
        """Return one config entry's own notifications, priority-resolved."""
        return compute_active_set(self._entry_active.get(pool_entry_id, []))

    def async_add_entry_listener(
        self,
        pool_entry_id: str,
        listener: Callable[[], Awaitable[None] | None],
    ) -> Callable[[], None]:
        """Subscribe to changes in one entry's active notifications.

        Returns an unsubscribe callable.
        """
        listeners = self._entry_listeners.setdefault(pool_entry_id, [])
        listeners.append(listener)

        def _unsubscribe() -> None:
            if listener in listeners:
                listeners.remove(listener)

        return _unsubscribe

    def get_ceiling(self, pool_entry_id: str) -> int:
        """Return one entry's brightness ceiling (0-255, default full)."""
        return self._ceilings.get(pool_entry_id, MAX_CEILING)

    async def async_set_ceiling(self, pool_entry_id: str, ceiling: int) -> None:
        """Set one entry's brightness ceiling and re-render its targets.

        The ceiling scales every notification that entry activates, wherever
        it renders -- this is what lets a group's light entity dim its
        notifications without touching the notifications' own authored
        brightness.
        """
        ceiling = max(0, min(MAX_CEILING, ceiling))
        if self._ceilings.get(pool_entry_id, MAX_CEILING) == ceiling:
            return
        self._ceilings[pool_entry_id] = ceiling
        affected = {
            target
            for target, stack in self._stacks.items()
            if any(pid == pool_entry_id for _n, pid, _t in stack)
        }
        _LOGGER.info(
            "Set ceiling for entry %s to %d, affecting %d target(s)",
            pool_entry_id,
            ceiling,
            len(affected),
        )
        await self._render_targets(affected)

    def _active_set(self, stack_key: str) -> list[ActiveEntry]:
        """Return the priority-resolved stack for one concrete target.

        Each notification's authored brightness is scaled by its owning
        entry's live ceiling before priority ordering. Ordering itself is
        unaffected -- brightness plays no part in `_sort_key`.
        """
        scaled: list[tuple[Notification, float]] = []
        for notification, pool_id, activated_at in self._stacks.get(stack_key, []):
            ceiling = self._ceilings.get(pool_id, MAX_CEILING)
            if ceiling != MAX_CEILING:
                notification = replace(
                    notification,
                    brightness=round(notification.brightness * ceiling / MAX_CEILING),
                )
            scaled.append((notification, activated_at))
        return compute_active_set(scaled)

    async def _render_targets(self, targets: set[str]) -> None:
        """Render changed targets, using native groups when their state agrees."""
        remaining = set(targets)
        groups = [
            group
            for owner_groups in self._transport_groups.values()
            for group in owner_groups
        ]

        # Prefer the largest eligible group when routes overlap. A groupcast is
        # safe only when every configured member changed in this transaction and
        # every member has the same final notification stack.
        for group in sorted(groups, key=lambda item: len(item.members), reverse=True):
            if not group.members or not group.members.issubset(remaining):
                continue

            renderers = [self._renderer_for_entity(member) for member in group.members]
            if any(renderer is None for renderer in renderers):
                continue
            resolved_renderers = [renderer for renderer in renderers if renderer]
            adapter = resolved_renderers[0][0]
            if any(item[0] is not adapter for item in resolved_renderers[1:]):
                continue
            render_group = getattr(adapter, "render_group", None)
            if render_group is None:
                continue

            active_set = self._active_set(next(iter(group.members)))
            if any(self._active_set(member) != active_set for member in group.members):
                _LOGGER.debug(
                    "Transport group %s has divergent member stacks; using unicast",
                    group.name,
                )
                continue

            adapter_targets = [item[1] for item in resolved_renderers]
            try:
                await render_group(group.target, active_set, adapter_targets)
            except Exception:
                _LOGGER.exception(
                    "Group render failed for %s; falling back to individual targets",
                    group.name,
                )
                continue

            _LOGGER.info(
                "Rendered %d devices through transport group %s (%s)",
                len(group.members),
                group.name,
                group.target,
            )
            remaining.difference_update(group.members)

        for target in sorted(remaining):
            await self._render_target(target)

    def _renderer_for_entity(self, entity_id: str):
        """Resolve one entity to its adapter and adapter-specific target."""
        entity_entry = self._entity_registry.async_get(entity_id)
        if entity_entry is None or entity_entry.device_id is None:
            return None
        device_entry = self._device_registry.async_get(entity_entry.device_id)
        if device_entry is None:
            return None
        adapter = self._adapter_registry.get_adapter(
            device_entry.manufacturer or "", device_entry.model or ""
        )
        if adapter is None:
            return None
        return adapter, adapter.target_for_device(device_entry)

    def _resolve_group_members(
        self, entity_id: str, *, _depth: int = 0
    ) -> list[str] | None:
        """Return member entity IDs if entity_id is a group, else None."""
        if _depth > 3:
            return None
        state = self._hass.states.get(entity_id)
        if state is None:
            return None
        members = state.attributes.get("entity_id") or state.attributes.get(
            "group_entities"
        )
        if not members:
            return None

        result: list[str] = []
        for member_id in members:
            nested = self._resolve_group_members(member_id, _depth=_depth + 1)
            if nested:
                result.extend(nested)
            else:
                result.append(member_id)
        return result

    async def _render_target(self, target_entity_id: str) -> None:
        """Expand groups and render individual devices for one target."""
        members = self._resolve_group_members(target_entity_id)
        if members:
            _LOGGER.debug(
                "Expanding group %s to %d members: %s",
                target_entity_id,
                len(members),
                members,
            )
            for member_id in members:
                await self._render_device(member_id, stack_key=target_entity_id)
        else:
            await self._render_device(target_entity_id, stack_key=target_entity_id)

    async def _render_device(self, entity_id: str, *, stack_key: str) -> None:
        """Look up device info, match adapter, and call render for one device."""
        entity_entry = self._entity_registry.async_get(entity_id)
        if entity_entry is None or entity_entry.device_id is None:
            if entity_id not in self._warned_targets:
                _LOGGER.warning("Target %s has no device entry, skipping", entity_id)
                self._warned_targets.add(entity_id)
            return

        device_entry = self._device_registry.async_get(entity_entry.device_id)
        if device_entry is None:
            if entity_id not in self._warned_targets:
                _LOGGER.warning(
                    "No device found for target %s (device_id=%s), skipping",
                    entity_id,
                    entity_entry.device_id,
                )
                self._warned_targets.add(entity_id)
            return

        adapter = self._adapter_registry.get_adapter(
            device_entry.manufacturer or "", device_entry.model or ""
        )
        if adapter is None:
            if entity_id not in self._warned_targets:
                _LOGGER.warning(
                    "No adapter for %s (manufacturer=%s, model=%s), skipping",
                    entity_id,
                    device_entry.manufacturer,
                    device_entry.model,
                )
                self._warned_targets.add(entity_id)
            return

        active_set = self._active_set(stack_key)
        adapter_target = adapter.target_for_device(device_entry)

        _LOGGER.info(
            "Rendering %s (%s): %d active notifications, adapter=%s",
            entity_id,
            adapter_target,
            len(active_set),
            type(adapter).__name__,
        )

        try:
            await adapter.render(adapter_target, active_set)
        except Exception:
            _LOGGER.exception("Adapter render failed for %s", entity_id)
