"""Switch entity for stateful (duration=0) notifications."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .notification import Notification

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    notifications = data["notifications"]
    targets = data["targets"]

    stateful = [n for n in notifications.values() if n.is_stateful]
    _LOGGER.info(
        "Switch platform setup: %d stateful of %d total notifications",
        len(stateful), len(notifications),
    )

    entities = [
        NotificationSwitch(coordinator, notif, targets, entry.entry_id)
        for notif in stateful
    ]
    async_add_entities(entities)


class NotificationSwitch(SwitchEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        notification: Notification,
        targets: list[str],
        entry_id: str,
    ) -> None:
        self._coordinator = coordinator
        self._notification = notification
        self._targets = targets
        self._entry_id = entry_id
        self._is_on = False
        self._attr_unique_id = f"notify_lights_{entry_id}_{notification.name}"
        self._attr_name = f"Notify {notification.name.replace('_', ' ')}"

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        _LOGGER.info("Switch %s turned ON", self._notification.name)
        self._is_on = True
        await self._coordinator.async_activate(
            self._notification, self._targets, self._entry_id
        )

    async def async_turn_off(self, **kwargs) -> None:
        _LOGGER.info("Switch %s turned OFF", self._notification.name)
        self._is_on = False
        await self._coordinator.async_deactivate(
            self._notification, self._targets, self._entry_id
        )
