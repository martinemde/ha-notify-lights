"""Binary sensor entities for notifications bound to source state."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

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

    bound = [n for n in notifications.values() if n.is_source_bound]
    _LOGGER.info(
        "Binary sensor platform setup: %d source-bound notifications",
        len(bound),
    )
    async_add_entities(
        [
            StateNotificationBinarySensor(
                coordinator,
                notification,
                targets.get(notification.name, []),
                entry,
            )
            for notification in bound
        ]
    )


class StateNotificationBinarySensor(BinarySensorEntity):
    """A notification whose active state follows another HA entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        notification: Notification,
        targets: list[str],
        entry: ConfigEntry,
    ) -> None:
        self._coordinator = coordinator
        self._notification = notification
        self._targets = targets
        self._entry_id = entry.entry_id
        self._attr_is_on = None
        self._attr_available = False
        self._attr_unique_id = (
            f"notify_lights_{entry.entry_id}_{notification.name}"
        )
        self._attr_name = notification.display_name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the notification definition and source binding."""
        return {
            "description": self._notification.description,
            "priority": self._notification.priority,
            "targets": self._targets,
            "state_entity": self._notification.state_entity,
            "active_state": self._notification.active_state,
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to the source and synchronize immediately."""
        await super().async_added_to_hass()
        source_entity = self._notification.state_entity
        assert source_entity is not None
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [source_entity],
                self._async_source_changed,
            )
        )
        await self._async_apply_source_state(self.hass.states.get(source_entity))

    async def _async_source_changed(self, event: Event) -> None:
        """Apply one source entity state-change event."""
        await self._async_apply_source_state(event.data.get("new_state"))

    async def _async_apply_source_state(self, source: State | None) -> None:
        """Synchronize the notification with a source state."""
        if source is None or source.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        active = source.state == self._notification.active_state
        previous = self._attr_is_on
        self._attr_is_on = active

        if active and previous is not True:
            await self._coordinator.async_activate(
                self._notification,
                self._targets,
                self._entry_id,
            )
        elif not active and previous is not False:
            await self._coordinator.async_deactivate(
                self._notification,
                self._targets,
                self._entry_id,
            )

        self.async_write_ha_state()
