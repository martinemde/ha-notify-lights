"""Binary sensor entities for notifications bound to source state."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

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
        self._last_source_value: str | None = None
        self._source_initialized = False
        self._cancel_timer = None
        self._attr_unique_id = f"notify_lights_{entry.entry_id}_{notification.name}"
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
            "state_attribute": self._notification.state_attribute,
            "active_state": self._notification.active_state,
            "activation": (
                "state_entered"
                if self._notification.is_source_momentary
                else "state_while"
            ),
            "duration": self._notification.duration,
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
        self.async_on_remove(self._cancel_active_timer)
        await self._async_apply_source_state(
            self.hass.states.get(source_entity), initial=True
        )

    async def _async_source_changed(self, event: Event) -> None:
        """Apply one source entity state-change event."""
        await self._async_apply_source_state(event.data.get("new_state"))

    async def _async_apply_source_state(
        self, source: State | None, *, initial: bool = False
    ) -> None:
        """Synchronize the notification with a source state."""
        if source is None or source.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        was_initialized = self._source_initialized
        self._source_initialized = True
        source_value = self._source_value(source)
        previous_source_value = self._last_source_value
        self._last_source_value = source_value
        active = source_value == self._notification.active_state

        if self._notification.is_source_momentary:
            # Edge-triggered rules do not replay on integration setup. They
            # activate only when the source *enters* the configured state.
            if self._attr_is_on is None:
                self._attr_is_on = False
            if (
                was_initialized
                and not initial
                and active
                and previous_source_value != source_value
            ):
                await self._async_activate_timed()
            self.async_write_ha_state()
            return

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

    def _source_value(self, source: State) -> str:
        """Read either the entity state or its configured attribute."""
        if self._notification.state_attribute:
            value = source.attributes.get(self._notification.state_attribute)
            return "" if value is None else str(value)
        return source.state

    async def _async_activate_timed(self) -> None:
        """Activate or restart an edge-triggered notification timer."""
        self._cancel_active_timer()
        self._attr_is_on = True
        await self._coordinator.async_activate(
            self._notification,
            self._targets,
            self._entry_id,
        )
        self._cancel_timer = async_call_later(
            self.hass,
            self._notification.duration,
            self._async_timer_finished,
        )

    async def _async_timer_finished(self, _now=None) -> None:
        """Clear a timed source notification."""
        self._cancel_timer = None
        self._attr_is_on = False
        await self._coordinator.async_deactivate(
            self._notification,
            self._targets,
            self._entry_id,
        )
        self.async_write_ha_state()

    def _cancel_active_timer(self) -> None:
        """Cancel the current timer, if any."""
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None
