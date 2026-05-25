"""Switch entity for stateful (duration=0) notifications."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .notification import Notification


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    notifications = data["notifications"]

    entities = [
        NotificationSwitch(coordinator, notif)
        for notif in notifications.values()
        if notif.is_stateful
    ]
    async_add_entities(entities)


class NotificationSwitch(SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, notification: Notification) -> None:
        self._coordinator = coordinator
        self._notification = notification
        self._is_on = False
        self._attr_unique_id = f"notify_lights_{notification.name}"
        self._attr_name = f"Notify {notification.name.replace('_', ' ')}"

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        await self._coordinator.async_activate(self._notification)

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        await self._coordinator.async_deactivate(self._notification)
