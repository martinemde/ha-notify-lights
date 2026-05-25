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

    async def _render_target(self, target_entity_id: str) -> None:
        """Look up device info, match adapter, and call render for one target."""
        entity_entry = self._entity_registry.async_get(target_entity_id)
        if entity_entry is None or entity_entry.device_id is None:
            if target_entity_id not in self._warned_targets:
                _LOGGER.warning(
                    "Target %s has no device entry, skipping", target_entity_id
                )
                self._warned_targets.add(target_entity_id)
            return

        device_entry = self._device_registry.async_get(entity_entry.device_id)
        if device_entry is None:
            if target_entity_id not in self._warned_targets:
                _LOGGER.warning(
                    "No device found for target %s (device_id=%s), skipping",
                    target_entity_id, entity_entry.device_id,
                )
                self._warned_targets.add(target_entity_id)
            return

        adapter = self._adapter_registry.get_adapter(
            device_entry.manufacturer or "", device_entry.model or ""
        )
        if adapter is None:
            if target_entity_id not in self._warned_targets:
                _LOGGER.warning(
                    "No adapter for %s (manufacturer=%s, model=%s), skipping",
                    target_entity_id, device_entry.manufacturer, device_entry.model,
                )
                self._warned_targets.add(target_entity_id)
            return

        # Convert StackEntry to ActiveEntry for the adapter
        active_entries: list[ActiveEntry] = [
            (n, t) for n, _pid, t in self._stacks.get(target_entity_id, [])
        ]
        active_set = compute_active_set(active_entries)
        friendly_name = device_entry.name

        _LOGGER.info(
            "Rendering %s (%s): %d active notifications, adapter=%s",
            target_entity_id, friendly_name, len(active_set),
            type(adapter).__name__,
        )

        try:
            await adapter.render(friendly_name, active_set)
        except Exception:
            _LOGGER.exception("Adapter render failed for %s", target_entity_id)
