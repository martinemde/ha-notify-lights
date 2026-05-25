"""Switch entity for stateful (duration=0) notifications."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity

from .notification import Notification


class NotificationSwitch(SwitchEntity):
    """Represents a persistent notification as a HA switch.

    Turning the switch on activates the notification; turning it off
    deactivates it. State is owned by this entity and reflected back to
    Home Assistant via is_on.
    """

    def __init__(self, coordinator, notification: Notification) -> None:
        self._coordinator = coordinator
        self._notification = notification
        self._is_on = False
        self._attr_unique_id = f"notify_lights_{notification.name}"
        self._attr_name = (
            f"Notify {notification.name.replace('_', ' ')}"
        )

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        await self._coordinator.async_activate(self._notification)

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        await self._coordinator.async_deactivate(self._notification)
