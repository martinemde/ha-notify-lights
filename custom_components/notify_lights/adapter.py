"""Adapter interface and registry for hardware-specific notification adapters.

Each adapter targets a specific manufacturer/model family and implements the
render/clear protocol. The registry matches devices using glob patterns so a
single adapter can cover an entire product line (e.g. "VZM31*").
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from fnmatch import fnmatch
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.helpers.device_registry import DeviceEntry

    from .active_set import ActiveEntry
    from .const import Effect


class NotificationAdapter(ABC):
    """Abstract base for hardware-specific light notification adapters."""

    manufacturer: str
    model_patterns: list[str]
    max_concurrent: int
    supported_effects: set[Effect]
    # Maps unsupported effects to the closest supported substitute.
    effect_fallbacks: dict[Effect, Effect]

    def target_for_device(self, device: DeviceEntry) -> str:
        """Return the adapter-specific command target for a device."""
        return device.name

    @abstractmethod
    async def render(self, target: str, active: list[ActiveEntry]) -> None:
        """Apply the highest-priority active notifications to the target device."""
        ...

    @abstractmethod
    async def clear(self, target: str) -> None:
        """Remove all notification effects from the target device."""
        ...


class AdapterRegistry:
    """Registry that maps manufacturer + model to the correct adapter."""

    def __init__(self) -> None:
        self._adapters: list[NotificationAdapter] = []

    def register(self, adapter: NotificationAdapter) -> None:
        """Add an adapter to the registry."""
        self._adapters.append(adapter)

    def get_adapter(self, manufacturer: str, model: str) -> NotificationAdapter | None:
        """Return the first adapter whose manufacturer and model glob match."""
        for adapter in self._adapters:
            if adapter.manufacturer != manufacturer:
                continue
            if any(fnmatch(model, pat) for pat in adapter.model_patterns):
                return adapter
        return None
