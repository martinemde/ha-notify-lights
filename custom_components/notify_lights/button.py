"""Button entity for momentary (duration > 0) notifications."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

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

    momentary = [n for n in notifications.values() if n.is_momentary]
    _LOGGER.info(
        "Button platform setup: %d momentary of %d total notifications",
        len(momentary), len(notifications),
    )

    entities = [
        NotificationButton(coordinator, notif, targets, entry, hass)
        for notif in momentary
    ]
    async_add_entities(entities)


class NotificationButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        notification: Notification,
        targets: list[str],
        entry: ConfigEntry,
        hass,
    ) -> None:
        self._coordinator = coordinator
        self._notification = notification
        self._targets = targets
        self._entry_id = entry.entry_id
        self._hass = hass
        self._cancel_timer = None
        self._attr_unique_id = (
            f"notify_lights_{entry.entry_id}_{notification.name}"
        )
        self._attr_name = notification.display_name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
        )

    async def async_press(self, **kwargs) -> None:
        _LOGGER.info(
            "Button %s pressed (duration=%ds)",
            self._notification.name, self._notification.duration,
        )
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None

        await self._coordinator.async_activate(
            self._notification, self._targets, self._entry_id
        )

        self._cancel_timer = async_call_later(
            self._hass,
            self._notification.duration,
            self._auto_deactivate,
        )

    async def _auto_deactivate(self, _now=None) -> None:
        _LOGGER.info("Auto-deactivating button %s", self._notification.name)
        self._cancel_timer = None
        await self._coordinator.async_deactivate(
            self._notification, self._targets, self._entry_id
        )
