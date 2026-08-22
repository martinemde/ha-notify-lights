"""Adapter for Inovelli Blue series switches via Zigbee2MQTT.

Converts Notification objects to MQTT payloads and publishes them
to Zigbee2MQTT via HA's mqtt.publish service.

MQTT topic: zigbee2mqtt/{friendly_name}/set
Payload: {"led_effect": {"effect": "...", "color": 0-255, "level": 0-100,
                          "duration": 1-255}}

Duration encoding: 1-60=seconds, 61-120=minutes(value-60),
121-254=hours(value-120), 255=indefinite.
Color: 0-255 hue wheel (value/255*360=degrees, 255=white).
"""
from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..adapter import NotificationAdapter
from ..const import Effect, Speed
from .inovelli_blue_bar import BarPixel, InovelliBlueBar, LED_COUNT

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


def _build_led_effect_payload(notification: Any) -> dict:
    """Build the Z2M led_effect dict from a Notification."""
    return {
        "led_effect": {
            "effect": effect_to_z2m_string(
                notification.effect, notification.effect_speed
            ),
            "color": hue_to_z2m_color(notification.color),
            "level": notification.brightness,
            "duration": seconds_to_z2m_duration(notification.duration),
        }
    }


def _build_individual_led_effect_payload(pixel: BarPixel) -> dict:
    """Build one Z2M individual_led_effect command for a bar pixel."""
    notification = pixel.notification
    return {
        "individual_led_effect": {
            # Zigbee2MQTT models the LED selector as an enum, hence a string.
            "led": str(pixel.led),
            "effect": individual_effect_to_z2m_string(
                pixel.effect, notification.effect_speed
            ),
            "color": hue_to_z2m_color(notification.color),
            "level": notification.brightness,
            "duration": seconds_to_z2m_duration(notification.duration),
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


def build_z2m_render_payloads(active: list[ActiveEntry]) -> list[dict]:
    """Build the complete command sequence for a priority-sorted stack.

    A single active notification continues to use the native full-bar command,
    preserving coordinated animations. A layered bar is cleared first so a
    previous full-bar effect cannot bleed through, then programmed one pixel
    at a time because Zigbee2MQTT accepts one individual LED per command.
    """
    bar = InovelliBlueBar.from_active(active)
    if bar.is_empty:
        return [_CLEAR_PAYLOAD]
    if not bar.is_layered:
        notification = next(pixel.notification for pixel in bar.pixels if pixel)
        return [_build_led_effect_payload(notification)]
    return [
        _CLEAR_PAYLOAD,
        *[
            _build_individual_led_effect_payload(pixel)
            for pixel in bar.pixels
            if pixel is not None
        ],
    ]


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
        self.pixels: list[Z2MPixelState | None] = [None] * LED_COUNT

    def apply(self, payload: dict) -> None:
        """Apply one Z2M set payload to the simulated switch."""
        if "led_effect" in payload:
            effect = payload["led_effect"]
            if effect["effect"] in {"clear_effect", "off"}:
                self.pixels = [None] * LED_COUNT
            else:
                state = self._state_from_effect(effect)
                self.pixels = [state] * LED_COUNT

        if "individual_led_effect" in payload:
            effect = payload["individual_led_effect"]
            led = int(effect["led"])
            if not 1 <= led <= LED_COUNT:
                raise ValueError(f"LED must be 1-{LED_COUNT}, got {led}")
            self.pixels[led - 1] = (
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
    model_patterns = [
        "VZM31*",
        "VZM35*",
        "mmWave Zigbee Dimmer",
        "2-in-1 switch + dimmer",
    ]
    max_concurrent = 2
    supported_effects = set(Effect)
    effect_fallbacks: dict[Effect, Effect] = {}

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def render(self, target: str, active: list[ActiveEntry]) -> None:
        """Publish a full-bar or two-layer rendering of the active stack."""
        payloads = build_z2m_render_payloads(active)
        _LOGGER.info("Publishing %d LED command(s) to %s", len(payloads), target)
        for payload in payloads:
            await self._publish(target, payload)

    async def clear(self, target: str) -> None:
        """Send a clear_effect to remove all notification LEDs."""
        _LOGGER.info("Clearing LED on %s", target)
        await self._publish(target, _CLEAR_PAYLOAD)

    async def _publish(self, target: str, payload: dict) -> None:
        topic = f"zigbee2mqtt/{target}/set"
        _LOGGER.debug("MQTT publish: topic=%s payload=%s", topic, json.dumps(payload))
        await self._hass.services.async_call(
            "mqtt",
            "publish",
            {"topic": topic, "payload": json.dumps(payload)},
        )
