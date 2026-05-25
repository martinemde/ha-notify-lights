"""Central coordinator for Notify Lights.

Tracks per-target active notification sets, resolves entity IDs to device
info, matches adapters from the registry, and dispatches render calls.
"""
from __future__ import annotations

import logging
import time

from .adapter import AdapterRegistry
from .active_set import ActiveEntry, compute_active_set
from .notification import Notification

_LOGGER = logging.getLogger(__name__)


class NotifyLightsCoordinator:
    """Coordinate notifications across targets and adapters.

    Holds the AdapterRegistry, tracks per-target active notification sets,
    resolves target references to entity IDs, looks up device info from HA
    registries, and dispatches render calls to matched adapters.
    """

    _LOGGER = _LOGGER  # expose for tests that want to inspect/patch it

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
        # Per-target active sets: entity_id -> list of (Notification, activated_at)
        self._active: dict[str, list[ActiveEntry]] = {}
        # Avoid spamming logs for the same unresolvable target
        self._warned_targets: set[str] = set()

    async def async_activate(self, notification: Notification) -> None:
        """Add notification to each target's active set and re-render."""
        activated_at = time.monotonic()
        targets = self._resolve_targets(notification.targets)
        _LOGGER.info(
            "Activating %s on %d targets: %s",
            notification.name, len(targets), targets,
        )
        for target in targets:
            entries = self._active.setdefault(target, [])
            entries.append((notification, activated_at))
            await self._render_target(target)

    async def async_deactivate(self, notification: Notification) -> None:
        """Remove notification from each target's active set and re-render."""
        targets = self._resolve_targets(notification.targets)
        _LOGGER.info(
            "Deactivating %s on %d targets: %s",
            notification.name, len(targets), targets,
        )
        for target in targets:
            entries = self._active.get(target, [])
            self._active[target] = [
                (n, t) for n, t in entries if n.name != notification.name
            ]
            _LOGGER.debug(
                "Target %s: %d remaining active notifications",
                target, len(self._active[target]),
            )
            await self._render_target(target)

    def _resolve_targets(self, targets: list[str]) -> list[str]:
        """Resolve target references to entity IDs.

        v1: entity IDs are passed through unchanged. Area and group
        resolution is a future enhancement.
        """
        return targets

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
                    target_entity_id,
                    entity_entry.device_id,
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
                    target_entity_id,
                    device_entry.manufacturer,
                    device_entry.model,
                )
                self._warned_targets.add(target_entity_id)
            return

        active_set = compute_active_set(self._active.get(target_entity_id, []))
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
