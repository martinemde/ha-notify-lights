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
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON
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
        self._announced_on = False
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

    def _handle_active_changed(self):
        """Refresh state whenever this entry's active notification changes.

        Going from dark to lit is announced as a real `light.turn_on` service
        call on ourselves rather than a bare state write. Adaptive Lighting
        adapts a light only when its `off` -> `on` state change carries the
        context of a tracked `light.turn_on`; a state write alone looks like an
        external turn-on, which AL marks as manually controlled and then leaves
        alone. Returning the coroutine lets the coordinator await it, so the
        ceiling AL injects is in place before the first render. The state stays
        `off` until the call lands -- AL skips lights that already read `on`.
        """
        if self.is_on and not self._announced_on:
            return self._async_announce_turn_on()
        self._announced_on = self.is_on
        self.async_write_ha_state()
        return None

    async def _async_announce_turn_on(self) -> None:
        """Turn ourselves on through the light service, bare of any attributes.

        Bare matters: AL skips any `light.turn_on` carrying an effect, and with
        `adapt_only_on_bare_turn_on` it marks whatever attributes the call names
        as manually controlled instead of adapting them.
        """
        await self.hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: self.entity_id},
            blocking=True,
        )

    async def async_turn_on(self, **kwargs) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS, self.brightness or 255)
        _LOGGER.info(
            "Setting brightness ceiling for entry %s to %d", self._entry_id, brightness
        )
        await self._coordinator.async_set_ceiling(self._entry_id, brightness)
        self._announced_on = self.is_on
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Clear this entry's active notifications and mute future ones.

        Clearing (rather than just zeroing the ceiling) frees whatever
        priority slots those notifications held, so a lower-priority
        notification from another catalog can show through immediately.
        """
        _LOGGER.info(
            "Turning off entry %s: clearing notifications and muting", self._entry_id
        )
        await self._coordinator.async_clear_entry_notifications(self._entry_id)
        await self._coordinator.async_set_ceiling(self._entry_id, 0)
        self._announced_on = False
        self.async_write_ha_state()
