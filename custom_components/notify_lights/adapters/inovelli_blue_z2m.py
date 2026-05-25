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

import json
from typing import TYPE_CHECKING, Any

from ..adapter import NotificationAdapter
from ..const import Effect, Speed

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


_CLEAR_PAYLOAD = json.dumps({"led_effect": {"effect": "clear_effect"}})


class InovelliBlueZ2MAdapter(NotificationAdapter):
    """Adapter for Inovelli Blue dimmer (VZM31) and fan switch (VZM35).

    Publishes led_effect payloads to Zigbee2MQTT. v1 renders only the
    top-priority notification on the full LED bar (max_concurrent=1).
    """

    manufacturer = "Inovelli"
    model_patterns = ["VZM31*", "VZM35*"]
    max_concurrent = 1
    supported_effects = set(Effect)
    effect_fallbacks: dict[Effect, Effect] = {}

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def render(self, target: str, active: list[ActiveEntry]) -> None:
        """Publish the top-priority notification or clear if none active."""
        if not active:
            await self.clear(target)
            return

        # active[0] is the highest-priority entry (sorted by ActiveSet)
        notification, _score = active[0]
        payload = _build_led_effect_payload(notification)
        await self._publish(target, payload)

    async def clear(self, target: str) -> None:
        """Send a clear_effect to remove all notification LEDs."""
        await self._hass.services.async_call(
            "mqtt",
            "publish",
            {
                "topic": f"zigbee2mqtt/{target}/set",
                "payload": _CLEAR_PAYLOAD,
            },
        )

    async def _publish(self, target: str, payload: dict) -> None:
        await self._hass.services.async_call(
            "mqtt",
            "publish",
            {
                "topic": f"zigbee2mqtt/{target}/set",
                "payload": json.dumps(payload),
            },
        )
