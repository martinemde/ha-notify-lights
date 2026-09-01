"""Light entity mirroring each catalog's own top-priority notification.

One light entity per config entry. Its on/off, color, and effect are a
read-only reflection of whichever of that entry's own notifications is
currently highest priority -- there is nothing to command there. Its
brightness is the opposite: a live ceiling the entity owns and that scales
every notification the entry activates, wherever it renders. Setting that
brightness (by hand, from a scene, or from an Adaptive Lighting-managed
light group) is what lets a whole area go quiet at night without touching
any notification's own authored brightness.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, Effect

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    entry_targets = data.get("entry_targets", [])
    async_add_entities([NotifyLightsGroupLight(coordinator, entry, entry_targets)])


class NotifyLightsGroupLight(LightEntity, RestoreEntity):
    """A brightness ceiling for one catalog, mirroring its active display."""

    _attr_has_entity_name = True
    _attr_name = "Brightness"
    _attr_supported_color_modes: ClassVar[set] = {ColorMode.HS}
    _attr_color_mode = ColorMode.HS
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list: ClassVar[list] = [effect.value for effect in Effect]

    def __init__(self, coordinator, entry: ConfigEntry, targets: list[str]) -> None:
        self._coordinator = coordinator
        self._entry_id = entry.entry_id
        self._targets = targets
        self._unsubscribe = None
        self._attr_unique_id = f"notify_lights_{entry.entry_id}_brightness"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
        )

    @property
    def is_on(self) -> bool:
        return bool(self._coordinator.entry_active_set(self._entry_id))

    @property
    def brightness(self) -> int:
        return self._coordinator.get_ceiling(self._entry_id)

    @property
    def hs_color(self) -> tuple[float, float] | None:
        active = self._coordinator.entry_active_set(self._entry_id)
        if not active:
            return None
        return (active[0][0].color, 100)

    @property
    def effect(self) -> str | None:
        active = self._coordinator.entry_active_set(self._entry_id)
        return active[0][0].effect.value if active else None

    @property
    def extra_state_attributes(self) -> dict:
        active = self._coordinator.entry_active_set(self._entry_id)
        return {
            "targets": self._targets,
            "active_notification": active[0][0].name if active else None,
        }

    async def async_added_to_hass(self) -> None:
        """Restore the last commanded ceiling and start mirroring the stack."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.attributes.get(ATTR_BRIGHTNESS):
            await self._coordinator.async_set_ceiling(
                self._entry_id, int(last_state.attributes[ATTR_BRIGHTNESS])
            )
        self._unsubscribe = self._coordinator.async_add_entry_listener(
            self._entry_id, self._handle_active_changed
        )
        self.async_on_remove(self._unsubscribe)

    def _handle_active_changed(self) -> None:
        """Refresh state whenever this entry's active notification changes."""
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS, self.brightness or 255)
        _LOGGER.info(
            "Setting brightness ceiling for entry %s to %d", self._entry_id, brightness
        )
        await self._coordinator.async_set_ceiling(self._entry_id, brightness)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        _LOGGER.info("Setting brightness ceiling for entry %s to 0", self._entry_id)
        await self._coordinator.async_set_ceiling(self._entry_id, 0)
        self.async_write_ha_state()
