"""Adapter for Inovelli Blue series switches via Zigbee2MQTT.

Converts Notification objects to MQTT payloads and publishes them
to Zigbee2MQTT via HA's mqtt.publish service.

MQTT topic: zigbee2mqtt/{IEEE address}/set
Payload: {"led_effect": {"effect": "...", "color": 0-255, "level": 0-100,
                          "duration": 1-255}}

Duration encoding: 1-60=seconds, 61-120=minutes(value-60),
121-254=hours(value-120), 255=indefinite.
Color: 0-255 hue wheel (value/255*360=degrees, 255=white).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from ..adapter import NotificationAdapter
from ..const import Effect, Speed
from .inovelli_blue_bar import LED_COUNT, BarPixel, InovelliBlueBar

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..active_set import ActiveEntry


Z2M_EFFECT_MAP: dict[tuple[Effect, Speed], str] = {
    (Effect.SOLID, Speed.SLOW): "solid",
    (Effect.SOLID, Speed.MEDIUM): "solid",
    (Effect.SOLID, Speed.FAST): "solid",
    (Effect.BLINK, Speed.SLOW): "slow_blink",
    (Effect.BLINK, Speed.MEDIUM): "medium_blink",
    (Effect.BLINK, Speed.FAST): "fast_blink",
    (Effect.PULSE, Speed.SLOW): "pulse",
    (Effect.PULSE, Speed.MEDIUM): "pulse",
    (Effect.PULSE, Speed.FAST): "pulse",
    (Effect.CHASE, Speed.SLOW): "slow_chase",
    (Effect.CHASE, Speed.MEDIUM): "chase",
    (Effect.CHASE, Speed.FAST): "fast_chase",
    (Effect.FALLING, Speed.SLOW): "slow_falling",
    (Effect.FALLING, Speed.MEDIUM): "medium_falling",
    (Effect.FALLING, Speed.FAST): "fast_falling",
    (Effect.RISING, Speed.SLOW): "slow_rising",
    (Effect.RISING, Speed.MEDIUM): "medium_rising",
    (Effect.RISING, Speed.FAST): "fast_rising",
    (Effect.AURORA, Speed.SLOW): "aurora",
    (Effect.AURORA, Speed.MEDIUM): "aurora",
    (Effect.AURORA, Speed.FAST): "aurora",
}

# Zigbee2MQTT exposes a smaller effect set for an individual pixel than for
# the full bar. In particular, individual effects do not have speed variants
# for chase/falling/rising and do not expose a medium blink.
Z2M_INDIVIDUAL_EFFECT_MAP: dict[tuple[Effect, Speed], str] = {
    (Effect.SOLID, Speed.SLOW): "solid",
    (Effect.SOLID, Speed.MEDIUM): "solid",
    (Effect.SOLID, Speed.FAST): "solid",
    (Effect.BLINK, Speed.SLOW): "slow_blink",
    (Effect.BLINK, Speed.MEDIUM): "fast_blink",
    (Effect.BLINK, Speed.FAST): "fast_blink",
    (Effect.PULSE, Speed.SLOW): "pulse",
    (Effect.PULSE, Speed.MEDIUM): "pulse",
    (Effect.PULSE, Speed.FAST): "pulse",
    (Effect.CHASE, Speed.SLOW): "chase",
    (Effect.CHASE, Speed.MEDIUM): "chase",
    (Effect.CHASE, Speed.FAST): "chase",
    (Effect.FALLING, Speed.SLOW): "falling",
    (Effect.FALLING, Speed.MEDIUM): "falling",
    (Effect.FALLING, Speed.FAST): "falling",
    (Effect.RISING, Speed.SLOW): "rising",
    (Effect.RISING, Speed.MEDIUM): "rising",
    (Effect.RISING, Speed.FAST): "rising",
    (Effect.AURORA, Speed.SLOW): "aurora",
    (Effect.AURORA, Speed.MEDIUM): "aurora",
    (Effect.AURORA, Speed.FAST): "aurora",
}

# MQTT publication only confirms that Home Assistant handed the payload to the
# broker; it does not wait for Zigbee2MQTT to finish the Ember group send. Give
# each multicast frame time to leave the coordinator before queueing the next
# individual-pixel write. The final interval also protects the first command of
# the next render waiting on ``_command_lock``.
GROUP_COMMAND_INTERVAL_SECONDS = 0.2


def hue_to_z2m_color(hue: int) -> int:
    """Convert a 0-360 hue degree value to Z2M's 0-255 color range."""
    return round(hue * 255 / 360)


def seconds_to_z2m_duration(seconds: int) -> int:
    """Encode a duration in seconds to Z2M's compressed duration format.

    Encoding:
      0          -> 255 (indefinite)
      1-60       -> seconds directly
      61-3600    -> 60 + minutes
      >3600      -> 120 + hours (capped at 254)
    """
    if seconds == 0:
        return 255  # indefinite
    if seconds <= 60:
        return seconds
    minutes = seconds // 60
    if minutes < 60:
        return 60 + minutes
    hours = seconds // 3600
    return min(120 + hours, 254)


def effect_to_z2m_string(effect: Effect, speed: Speed) -> str:
    """Map an Effect+Speed combination to the Z2M effect string."""
    return Z2M_EFFECT_MAP[(effect, speed)]


def individual_effect_to_z2m_string(effect: Effect, speed: Speed) -> str:
    """Map an Effect+Speed to Zigbee2MQTT's individual-pixel effect set."""
    return Z2M_INDIVIDUAL_EFFECT_MAP[(effect, speed)]


@dataclass(frozen=True)
class Z2MLayerState:
    """One latched hardware layer, including timed-effect refresh identity."""

    effect: str
    color: int
    level: int
    duration: int
    generation: float | None = None


@dataclass(frozen=True)
class Z2MDesiredState:
    """The independent full-bar and per-pixel layers desired on one switch."""

    full_bar: Z2MLayerState | None
    individual_pixels: tuple[Z2MLayerState | None, ...]

    def __post_init__(self) -> None:
        if len(self.individual_pixels) != LED_COUNT:
            raise ValueError(f"An Inovelli Blue bar has {LED_COUNT} pixels")


def _state_for_pixel(pixel: BarPixel, *, individual: bool) -> Z2MLayerState:
    """Translate a composed bar pixel into one native hardware layer."""
    notification = pixel.notification
    effect = (
        individual_effect_to_z2m_string(pixel.effect, notification.effect_speed)
        if individual
        else effect_to_z2m_string(pixel.effect, notification.effect_speed)
    )
    return Z2MLayerState(
        effect=effect,
        color=hue_to_z2m_color(notification.color),
        level=notification.brightness,
        duration=seconds_to_z2m_duration(notification.duration),
        # Re-pressing a timed notification must restart its hardware timer.
        # Indefinite notifications need no write when reactivated unchanged.
        generation=pixel.activated_at if notification.is_momentary else None,
    )


def build_z2m_desired_state(active: list[ActiveEntry]) -> Z2MDesiredState:
    """Compute native shadow layers from a priority-sorted active stack."""
    bar = InovelliBlueBar.from_active(active)
    full_bar = (
        _state_for_pixel(
            bar.full_bar,
            individual=False,
        )
        if bar.full_bar is not None
        else None
    )
    individual_pixels = tuple(
        (
            _state_for_pixel(
                pixel,
                individual=True,
            )
            if pixel is not None
            else None
        )
        for pixel in bar.individual_pixels
    )
    return Z2MDesiredState(full_bar, individual_pixels)


def _effect_values(state: Z2MLayerState) -> dict:
    """Return the values Zigbee2MQTT accepts for either effect command."""
    return {
        "effect": state.effect,
        "color": state.color,
        "level": state.level,
        "duration": state.duration,
    }


def _build_led_effect_payload(state: Z2MLayerState) -> dict:
    """Build a Z2M full-bar command from one desired layer."""
    return {"led_effect": _effect_values(state)}


def _build_individual_led_effect_payload(led: int, state: Z2MLayerState) -> dict:
    """Build one Z2M individual LED command from a desired layer."""
    return {
        "individual_led_effect": {
            # Zigbee2MQTT models the LED selector as an enum, hence a string.
            "led": str(led),
            **_effect_values(state),
        }
    }


_CLEAR_PAYLOAD = {
    "led_effect": {
        "effect": "clear_effect",
        "color": 0,
        "level": 100,
        "duration": 255,
    }
}


def _build_individual_clear_payload(led: int) -> dict:
    """Build a clear command for one individually programmed LED."""
    return {
        "individual_led_effect": {
            "led": str(led),
            "effect": "clear_effect",
            "color": 0,
            "level": 100,
            "duration": 255,
        }
    }


def _individual_clear_payloads() -> list[dict]:
    """Clear all seven independently latched LED notifications."""
    return [_build_individual_clear_payload(led) for led in range(1, LED_COUNT + 1)]


def _build_z2m_transition_payloads(
    desired: Z2MDesiredState,
    previous_states: list[Z2MDesiredState | None],
) -> list[dict]:
    """Build the union of writes needed to bring switches to desired state."""
    full_bar_changed = any(
        previous is None or previous.full_bar != desired.full_bar
        for previous in previous_states
    )
    changed_leds = [
        led
        for led in range(1, LED_COUNT + 1)
        if any(
            previous is None
            or previous.individual_pixels[led - 1] != desired.individual_pixels[led - 1]
            for previous in previous_states
        )
    ]

    full_bar_payloads = (
        [
            _build_led_effect_payload(desired.full_bar)
            if desired.full_bar is not None
            else _CLEAR_PAYLOAD
        ]
        if full_bar_changed
        else []
    )
    individual_payloads = [
        (
            _build_individual_led_effect_payload(
                led, desired.individual_pixels[led - 1]
            )
            if desired.individual_pixels[led - 1] is not None
            else _build_individual_clear_payload(led)
        )
        for led in changed_leds
    ]

    # Establish or update the base before its overrides. When removing the
    # base, establish any surviving indicators first so the bar never flashes
    # empty between commands.
    if desired.full_bar is not None:
        return [*full_bar_payloads, *individual_payloads]
    return [*individual_payloads, *full_bar_payloads]


def build_z2m_render_payloads(
    active: list[ActiveEntry],
    *,
    previous: Z2MDesiredState | None = None,
) -> list[dict]:
    """Build only the commands needed since a switch's previous render.

    An omitted previous state means the physical switch is unknown, so all
    eight independently latched layers are reconciled. Once state is known,
    unchanged layers produce no Zigbee traffic.
    """
    desired = build_z2m_desired_state(active)
    return _build_z2m_transition_payloads(desired, [previous])


@dataclass(frozen=True)
class Z2MPixelState:
    """Observable state of one pixel after applying Z2M commands."""

    effect: str
    color: int
    level: int
    duration: int


class InovelliBlueZ2MState:
    """Small switch simulator for inspecting and testing MQTT command stacks."""

    def __init__(self) -> None:
        self._full_bar: Z2MPixelState | None = None
        self._individual_pixels: list[Z2MPixelState | None] = [None] * LED_COUNT

    @property
    def pixels(self) -> list[Z2MPixelState | None]:
        """Return visible pixels, with individual effects shadowing the base."""
        return [individual or self._full_bar for individual in self._individual_pixels]

    def apply(self, payload: dict) -> None:
        """Apply one Z2M set payload to the simulated switch."""
        if "led_effect" in payload:
            effect = payload["led_effect"]
            if effect["effect"] in {"clear_effect", "off"}:
                self._full_bar = None
            else:
                self._full_bar = self._state_from_effect(effect)

        if "individual_led_effect" in payload:
            effect = payload["individual_led_effect"]
            led = int(effect["led"])
            if not 1 <= led <= LED_COUNT:
                raise ValueError(f"LED must be 1-{LED_COUNT}, got {led}")
            self._individual_pixels[led - 1] = (
                None
                if effect["effect"] in {"clear_effect", "off"}
                else self._state_from_effect(effect)
            )

    def apply_all(self, payloads: list[dict]) -> None:
        """Apply a sequence in MQTT publication order."""
        for payload in payloads:
            self.apply(payload)

    @staticmethod
    def _state_from_effect(effect: dict) -> Z2MPixelState:
        return Z2MPixelState(
            effect=effect["effect"],
            color=effect["color"],
            level=effect["level"],
            duration=effect["duration"],
        )


class InovelliBlueZ2MAdapter(NotificationAdapter):
    """Adapter for Inovelli Blue dimmer (VZM31) and fan switch (VZM35).

    Publishes led_effect and individual_led_effect payloads to Zigbee2MQTT.
    The two highest-priority notifications can be visible concurrently.
    """

    manufacturer = "Inovelli"
    model_patterns: ClassVar[list[str]] = [
        "VZM31*",
        "VZM35*",
        "mmWave Zigbee Dimmer",
        "2-in-1 switch + dimmer",
    ]
    max_concurrent = 2
    supported_effects: ClassVar[set[Effect]] = set(Effect)
    effect_fallbacks: ClassVar[dict[Effect, Effect]] = {}

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._rendered_states: dict[str, Z2MDesiredState] = {}
        # Group and individual renders may address the same physical switches.
        # Serialize complete command sequences so their pixel writes cannot
        # interleave when multiple HA state events arrive together.
        self._command_lock = asyncio.Lock()

    def target_for_device(self, device) -> str:
        """Use the stable Zigbee IEEE address instead of the HA display name.

        Zigbee2MQTT accepts the IEEE address as a device target. Home Assistant's
        device name can differ from the Zigbee2MQTT friendly name, so using it as
        an MQTT topic silently publishes to a nonexistent device.
        """
        for source, identifier in device.identifiers:
            if source == "mqtt" and identifier.startswith("zigbee2mqtt_0x"):
                return identifier.removeprefix("zigbee2mqtt_")
        return super().target_for_device(device)

    async def render(self, target: str, active: list[ActiveEntry]) -> None:
        """Publish only layers that differ from the last commanded state."""
        async with self._command_lock:
            desired = build_z2m_desired_state(active)
            payloads = _build_z2m_transition_payloads(
                desired, [self._rendered_states.get(target)]
            )
            _LOGGER.info(
                "Publishing %d changed LED layer(s) to %s",
                len(payloads),
                target,
            )
            try:
                for payload in payloads:
                    await self._publish(target, payload)
            except Exception:
                # A partially published transition is no longer trustworthy.
                # The next render must reconcile every layer defensively.
                self._rendered_states.pop(target, None)
                raise
            self._rendered_states[target] = desired

    async def render_group(
        self, target: str, active: list[ActiveEntry], members: list[str]
    ) -> None:
        """Render the union of member deltas through a Zigbee group topic."""
        async with self._command_lock:
            desired = build_z2m_desired_state(active)
            payloads = _build_z2m_transition_payloads(
                desired,
                [self._rendered_states.get(member) for member in members],
            )
            _LOGGER.info(
                "Publishing %d changed LED group layer(s) to %s for %d members",
                len(payloads),
                target,
                len(members),
            )
            try:
                for payload in payloads:
                    await self._publish(target, payload)
                    await asyncio.sleep(GROUP_COMMAND_INTERVAL_SECONDS)
            except Exception:
                # Group delivery may have reached any subset of members.
                for member in members:
                    self._rendered_states.pop(member, None)
                raise
            for member in members:
                self._rendered_states[member] = desired

    async def clear(self, target: str) -> None:
        """Clear both full-bar and individually latched notification LEDs."""
        async with self._command_lock:
            _LOGGER.info("Clearing all notification LED layers on %s", target)
            try:
                for payload in [*_individual_clear_payloads(), _CLEAR_PAYLOAD]:
                    await self._publish(target, payload)
            except Exception:
                self._rendered_states.pop(target, None)
                raise
            self._rendered_states[target] = build_z2m_desired_state([])

    async def _publish(self, target: str, payload: dict) -> None:
        topic = f"zigbee2mqtt/{target}/set"
        _LOGGER.debug("MQTT publish: topic=%s payload=%s", topic, json.dumps(payload))
        await self._hass.services.async_call(
            "mqtt",
            "publish",
            {"topic": topic, "payload": json.dumps(payload)},
        )
