"""Button entity for momentary (duration > 0) notifications."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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

    momentary = [n for n in notifications.values() if n.is_momentary]
    _LOGGER.info(
        "Button platform setup: %d momentary of %d total notifications",
        len(momentary), len(notifications),
    )
    for n in momentary:
        _LOGGER.debug(
            "  button: %s (duration=%ds, priority=%d, targets=%s)",
            n.name, n.duration, n.priority, n.targets,
        )

    entities = [
        NotificationButton(coordinator, notif, hass) for notif in momentary
    ]
    async_add_entities(entities)


class NotificationButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, notification: Notification, hass) -> None:
        self._coordinator = coordinator
        self._notification = notification
        self._hass = hass
        self._cancel_timer = None
        self._attr_unique_id = f"notify_lights_{notification.name}"
        self._attr_name = f"Notify {notification.name.replace('_', ' ')}"

    async def async_press(self, **kwargs) -> None:
        _LOGGER.info(
            "Button %s pressed (duration=%ds)",
            self._notification.name, self._notification.duration,
        )
        if self._cancel_timer is not None:
            _LOGGER.debug("Cancelling existing timer for %s", self._notification.name)
            self._cancel_timer()
            self._cancel_timer = None

        await self._coordinator.async_activate(self._notification)

        self._cancel_timer = async_call_later(
            self._hass,
            self._notification.duration,
            self._auto_deactivate,
        )
        _LOGGER.debug(
            "Timer set for %s: %ds", self._notification.name, self._notification.duration,
        )

    async def _auto_deactivate(self, _now=None) -> None:
        _LOGGER.info("Auto-deactivating button %s (timer expired)", self._notification.name)
        self._cancel_timer = None
        await self._coordinator.async_deactivate(self._notification)
