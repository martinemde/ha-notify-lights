"""Light entities for Notify Lights.

Two kinds live here.

`NotificationLight` is one notification rule, rendered as the light it is.
A notification has a color, a brightness and an effect, so the entity that
represents it is a light whose brightness, color and effect *are* those
settings: change them and you change what the notification displays,
everywhere it displays. That makes it configuration rather than a control,
so it sits in the device's configuration section, named with its priority so
the section reads in priority order. Turning it on activates the
notification by hand; several on at once stack by priority exactly as
automatic activations do.

`NotifyLightsGroupLight` is one per config entry. Its on/off, color, and
effect are a read-only reflection of whichever of that entry's own
notifications is currently highest priority -- there is nothing to command
there. Its brightness is the opposite: a live ceiling the entity owns and
that scales every notification the entry activates, wherever it renders.
Setting that brightness (by hand, from a scene, or from an Adaptive
Lighting-managed light group) is what lets a whole area go quiet at night
without touching any notification's own authored brightness.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, SPEEDLESS_EFFECTS, Activation, Effect, Speed
from .notification import Notification

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import Event, HomeAssistant, State
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)

# Home Assistant gives a light one effect name, while a notification carries
# an effect and a speed. The two are joined into a single name ("blink fast"),
# except for effects that ignore speed entirely.
WHITE_HUE = 360
# Below this saturation the switch is asked for white, which is off the hue
# wheel and otherwise unreachable from a color picker.
WHITE_SATURATION = 5.0


def effect_name(effect: Effect, speed: Speed | None) -> str:
    """Name one effect/speed pair for a light's effect list."""
    if speed is None or effect in SPEEDLESS_EFFECTS:
        return effect.value
    return f"{effect.value} {speed.value}"


def _build_effect_names() -> tuple[list[str], dict[str, tuple[Effect, Speed | None]]]:
    """Build the effect list and its reverse lookup, in enum order."""
    names: list[str] = []
    by_name: dict[str, tuple[Effect, Speed | None]] = {}
    for effect in Effect:
        speeds: tuple[Speed | None, ...] = (
            (None,) if effect in SPEEDLESS_EFFECTS else tuple(Speed)
        )
        for speed in speeds:
            name = effect_name(effect, speed)
            names.append(name)
            by_name[name] = (effect, speed)
    return names, by_name


EFFECT_NAMES, EFFECT_BY_NAME = _build_effect_names()


def hue_to_hs(hue: int) -> tuple[float, float]:
    """Present a notification hue as a Home Assistant HS color."""
    if hue >= WHITE_HUE:
        return (0.0, 0.0)
    return (float(hue), 100.0)


def hs_to_hue(hs_color: tuple[float, float]) -> int:
    """Read a notification hue back out of a Home Assistant HS color."""
    hue, saturation = hs_color
    if saturation <= WHITE_SATURATION:
        return WHITE_HUE
    return round(hue) % 360


def percent_to_brightness(percent: int) -> int:
    """Scale an authored 0-100 brightness to Home Assistant's 0-255."""
    return round(percent * 255 / 100)


def brightness_to_percent(brightness: int) -> int:
    """Scale a Home Assistant 0-255 brightness to an authored 0-100."""
    return round(brightness * 100 / 255)


def activation_of(notification: Notification) -> Activation:
    """Name how a notification becomes active, for the entity attributes."""
    if notification.is_source_momentary:
        return Activation.STATE_ENTERED
    if notification.is_source_bound:
        return Activation.STATE_WHILE
    if notification.is_momentary:
        return Activation.MANUAL_TIMED
    return Activation.MANUAL_WHILE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    notifications = data.get("notifications", {})
    targets = data.get("targets", {})
    entry_targets = data.get("entry_targets", [])

    _LOGGER.info(
        "Light platform setup: 1 catalog light and %d notification light(s)",
        len(notifications),
    )
    entities: list[LightEntity] = [
        NotifyLightsGroupLight(coordinator, entry, entry_targets)
    ]
    entities.extend(
        NotificationLight(
            coordinator, notification, targets.get(notification.name, []), entry
        )
        for notification in notifications.values()
    )
    async_add_entities(entities)


class NotificationLight(LightEntity, RestoreEntity):
    """One notification rule, as the light it renders."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_color_modes: ClassVar[set] = {ColorMode.HS}
    _attr_color_mode = ColorMode.HS
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list: ClassVar[list] = EFFECT_NAMES

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
        self._entry = entry
        self._entry_id = entry.entry_id
        self._is_on = False
        self._cancel_timer = None
        self._last_source_value: str | None = None
        self._source_initialized = False
        self._attr_unique_id = f"notify_lights_{entry.entry_id}_{notification.name}"
        # The priority prefix is display only, and zero-padded so 100 sorts
        # after 85. `suggested_object_id` keeps it out of the entity ID, so
        # re-prioritizing a rule reorders the configuration section without
        # breaking anything that references the entity.
        self._attr_name = f"{notification.priority:03d} {notification.display_name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
        )

    @property
    def suggested_object_id(self) -> str:
        """Build the entity ID from the plain name, without the priority."""
        return self._notification.display_name

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def brightness(self) -> int:
        return percent_to_brightness(self._notification.brightness)

    @property
    def hs_color(self) -> tuple[float, float]:
        return hue_to_hs(self._notification.color)

    @property
    def effect(self) -> str:
        return effect_name(self._notification.effect, self._notification.effect_speed)

    @property
    def extra_state_attributes(self) -> dict:
        """Expose what this notification means and where it will show."""
        notification = self._notification
        attributes: dict[str, Any] = {
            "description": notification.description,
            "priority": notification.priority,
            "activation": activation_of(notification).value,
            "display_mode": notification.display_mode.value,
            "targets": self._targets,
        }
        if notification.is_momentary:
            attributes["duration"] = notification.duration
        if notification.is_source_bound:
            attributes |= {
                "state_entity": notification.state_entity,
                "state_attribute": notification.state_attribute,
                "active_state": notification.active_state,
            }
        return attributes

    async def async_added_to_hass(self) -> None:
        """Follow the coordinator, then pick up wherever this rule left off."""
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_active_timer)
        self.async_on_remove(
            self._coordinator.async_add_entry_listener(
                self._entry_id, self._handle_entry_changed
            )
        )

        if self._notification.is_source_bound:
            source_entity = self._notification.state_entity
            assert source_entity is not None
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [source_entity],
                    self._async_source_changed,
                )
            )
            await self._async_apply_source_state(
                self.hass.states.get(source_entity), initial=True
            )
            return

        # A timed rule that was showing before a restart has long since
        # expired; only a "stays on until turned off" rule is restored.
        if self._notification.is_manual_stateful:
            last_state = await self.async_get_last_state()
            if last_state is not None and last_state.state == STATE_ON:
                await self.async_turn_on()

    def _handle_entry_changed(self):
        """Follow the coordinator when something else changes this rule.

        Turning the catalog's brightness light off clears every notification
        the catalog has active. Reading our state back from the coordinator
        keeps this entity from claiming to be lit after that.
        """
        active = any(
            notification.name == self._notification.name
            for notification, _ in self._coordinator.entry_active_set(self._entry_id)
        )
        if active != self._is_on:
            self._is_on = active
            if not active:
                self._cancel_active_timer()
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Apply any appearance change, then activate the notification."""
        updated = self._with_appearance(kwargs)
        if updated is not None:
            self._notification = updated
            self._persist_appearance()
        self._is_on = True
        _LOGGER.info("Notification %s turned ON", self._notification.name)
        await self._coordinator.async_activate(
            self._notification, self._targets, self._entry_id
        )
        if self._notification.is_momentary:
            self._restart_timer()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        _LOGGER.info("Notification %s turned OFF", self._notification.name)
        self._cancel_active_timer()
        self._is_on = False
        await self._coordinator.async_deactivate(
            self._notification, self._targets, self._entry_id
        )
        self.async_write_ha_state()

    def _with_appearance(self, kwargs: dict) -> Notification | None:
        """Return this notification restyled by a turn_on call, or None."""
        changes: dict[str, Any] = {}
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            changes["brightness"] = brightness_to_percent(brightness)
        if (hs_color := kwargs.get(ATTR_HS_COLOR)) is not None:
            changes["color"] = hs_to_hue(hs_color)
        if (requested := kwargs.get(ATTR_EFFECT)) is not None:
            pair = EFFECT_BY_NAME.get(requested)
            if pair is None:
                _LOGGER.warning(
                    "Ignoring unknown effect %r for %s",
                    requested,
                    self._notification.name,
                )
            else:
                effect, speed = pair
                changes["effect"] = effect
                # A speedless effect leaves the stored speed alone, so it
                # survives a trip through, say, solid and back to blink.
                if speed is not None:
                    changes["effect_speed"] = speed

        changed = {
            field: value
            for field, value in changes.items()
            if getattr(self._notification, field) != value
        }
        return replace(self._notification, **changed) if changed else None

    def _persist_appearance(self) -> None:
        """Write this notification's appearance back to the config entry.

        The catalog's options are the durable home for these settings now
        that the options flow no longer asks for them.
        `_async_update_listener` recognizes an appearance-only write and
        skips the reload it would otherwise do, so restyling a notification
        does not tear the catalog down and back up.
        """
        options = deepcopy(dict(self._entry.options))
        notifications = dict(options.get("notifications", {}))
        config = dict(notifications.get(self._notification.name, {}))
        config.update(
            color=self._notification.color,
            brightness=self._notification.brightness,
            effect=self._notification.effect.value,
            effect_speed=self._notification.effect_speed.value,
        )
        notifications[self._notification.name] = config
        options["notifications"] = notifications
        self.hass.config_entries.async_update_entry(self._entry, options=options)

    async def _async_source_changed(self, event: Event) -> None:
        """Apply one source entity state-change event."""
        await self._async_apply_source_state(event.data.get("new_state"))

    async def _async_apply_source_state(
        self, source: State | None, *, initial: bool = False
    ) -> None:
        """Synchronize the notification with a source state.

        A source that drops out is not a source that turned off, so an
        unknown or unavailable reading leaves whatever is showing alone. The
        entity itself stays available either way -- it carries the rule's
        settings, and those have to remain editable.
        """
        if source is None or source.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
            return

        was_initialized = self._source_initialized
        self._source_initialized = True
        source_value = self._source_value(source)
        previous_source_value = self._last_source_value
        self._last_source_value = source_value
        active = source_value == self._notification.active_state

        if self._notification.is_source_momentary:
            # Edge-triggered rules do not replay on integration setup. They
            # activate only when the source *enters* the configured state.
            if (
                was_initialized
                and not initial
                and active
                and previous_source_value != source_value
            ):
                await self.async_turn_on()
            return

        if active and not self._is_on:
            await self.async_turn_on()
        elif not active and self._is_on:
            await self.async_turn_off()

    def _source_value(self, source: State) -> str:
        """Read either the entity state or its configured attribute."""
        if self._notification.state_attribute:
            value = source.attributes.get(self._notification.state_attribute)
            return "" if value is None else str(value)
        return source.state

    def _restart_timer(self) -> None:
        """Start (or restart) the timer that clears a timed notification."""
        self._cancel_active_timer()
        self._cancel_timer = async_call_later(
            self.hass,
            self._notification.duration,
            self._async_timer_finished,
        )

    async def _async_timer_finished(self, _now=None) -> None:
        """Clear a timed notification when its duration runs out."""
        self._cancel_timer = None
        self._is_on = False
        _LOGGER.info("Notification %s timed out", self._notification.name)
        await self._coordinator.async_deactivate(
            self._notification, self._targets, self._entry_id
        )
        self.async_write_ha_state()

    def _cancel_active_timer(self) -> None:
        """Cancel the current timer, if any."""
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None


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
