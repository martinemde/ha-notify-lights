"""Central coordinator for Notify Lights.

Tracks per-target active notification stacks, resolves entity IDs to device
info, matches adapters from the registry, and dispatches render calls.
"""
from __future__ import annotations

import logging
import time

from .adapter import AdapterRegistry
from .active_set import ActiveEntry, compute_active_set
from .notification import Notification

_LOGGER = logging.getLogger(__name__)

# (Notification, pool_entry_id, activated_at)
StackEntry = tuple[Notification, str, float]


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

    async def async_activate(
        self, notification: Notification, targets: list[str], pool_entry_id: str
    ) -> None:
        """Add notification to each target's stack and re-render."""
        activated_at = time.monotonic()
        _LOGGER.info(
            "Activating %s (pool=%s) on %d targets: %s",
            notification.name, pool_entry_id, len(targets), targets,
        )
        for target in targets:
            stack = self._stacks.setdefault(target, [])
            stack.append((notification, pool_entry_id, activated_at))
            await self._render_target(target)

    async def async_deactivate(
        self, notification: Notification, targets: list[str], pool_entry_id: str
    ) -> None:
        """Remove notification from each target's stack and re-render."""
        _LOGGER.info(
            "Deactivating %s (pool=%s) on %d targets: %s",
            notification.name, pool_entry_id, len(targets), targets,
        )
        for target in targets:
            stack = self._stacks.get(target, [])
            self._stacks[target] = [
                (n, pid, t) for n, pid, t in stack
                if not (n.name == notification.name and pid == pool_entry_id)
            ]
            await self._render_target(target)

    def _resolve_group_members(
        self, entity_id: str, *, _depth: int = 0
    ) -> list[str] | None:
        """Return member entity IDs if entity_id is a group, else None."""
        if _depth > 3:
            return None
        state = self._hass.states.get(entity_id)
        if state is None:
            return None
        members = state.attributes.get("entity_id")
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
                target_entity_id, len(members), members,
            )
            for member_id in members:
                await self._render_device(member_id, stack_key=target_entity_id)
        else:
            await self._render_device(
                target_entity_id, stack_key=target_entity_id
            )

    async def _render_device(
        self, entity_id: str, *, stack_key: str
    ) -> None:
        """Look up device info, match adapter, and call render for one device."""
        entity_entry = self._entity_registry.async_get(entity_id)
        if entity_entry is None or entity_entry.device_id is None:
            if entity_id not in self._warned_targets:
                _LOGGER.warning(
                    "Target %s has no device entry, skipping", entity_id
                )
                self._warned_targets.add(entity_id)
            return

        device_entry = self._device_registry.async_get(entity_entry.device_id)
        if device_entry is None:
            if entity_id not in self._warned_targets:
                _LOGGER.warning(
                    "No device found for target %s (device_id=%s), skipping",
                    entity_id, entity_entry.device_id,
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
                    entity_id, device_entry.manufacturer, device_entry.model,
                )
                self._warned_targets.add(entity_id)
            return

        active_entries: list[ActiveEntry] = [
            (n, t) for n, _pid, t in self._stacks.get(stack_key, [])
        ]
        active_set = compute_active_set(active_entries)
        friendly_name = device_entry.name

        _LOGGER.info(
            "Rendering %s (%s): %d active notifications, adapter=%s",
            entity_id, friendly_name, len(active_set),
            type(adapter).__name__,
        )

        try:
            await adapter.render(friendly_name, active_set)
        except Exception:
            _LOGGER.exception("Adapter render failed for %s", entity_id)
