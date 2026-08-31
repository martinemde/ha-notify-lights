"""Central coordinator for Notify Lights.

Tracks per-target active notification stacks, resolves entity IDs to device
info, matches adapters from the registry, and dispatches render calls.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .active_set import ActiveEntry, compute_active_set
from .adapter import AdapterRegistry
from .notification import Notification

_LOGGER = logging.getLogger(__name__)

# (Notification, pool_entry_id, activated_at)
StackEntry = tuple[Notification, str, float]


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
        await self._render_targets(changed_targets)

    async def async_deactivate_entry(self, pool_entry_id: str) -> None:
        """Remove every active notification owned by one config entry."""
        changed_targets: list[str] = []
        for target, stack in self._stacks.items():
            kept = [entry for entry in stack if entry[1] != pool_entry_id]
            if len(kept) != len(stack):
                self._stacks[target] = kept
                changed_targets.append(target)

        _LOGGER.info(
            "Deactivated entry %s on %d targets",
            pool_entry_id,
            len(changed_targets),
        )
        await self._render_targets(set(changed_targets))

    def _active_set(self, stack_key: str) -> list[ActiveEntry]:
        """Return the priority-resolved stack for one concrete target."""
        return compute_active_set(
            [
                (notification, activated_at)
                for notification, _pool_id, activated_at in self._stacks.get(
                    stack_key, []
                )
            ]
        )

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
