"""Button entity for momentary (duration > 0) notifications."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.event import async_call_later

from .notification import Notification


class NotificationButton(ButtonEntity):
    """Button that triggers a momentary notification and auto-deactivates."""

    def __init__(self, coordinator, notification: Notification, hass) -> None:
        self._coordinator = coordinator
        self._notification = notification
        self._hass = hass
        self._cancel_timer = None
        self._attr_unique_id = f"notify_lights_{notification.name}"
        self._attr_name = f"Notify {notification.name.replace('_', ' ')}"

    async def async_press(self, **kwargs) -> None:
        """Activate the notification and schedule auto-deactivation."""
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None

        await self._coordinator.async_activate(self._notification)

        self._cancel_timer = async_call_later(
            self._hass,
            self._notification.duration,
            self._auto_deactivate,
        )

    async def _auto_deactivate(self, _now=None) -> None:
        """Deactivate the notification after the timer expires."""
        self._cancel_timer = None
        await self._coordinator.async_deactivate(self._notification)
