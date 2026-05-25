"""Tests for the Inovelli Blue Z2M adapter."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.notify_lights.adapters.inovelli_blue_z2m import (
    InovelliBlueZ2MAdapter,
    effect_to_z2m_string,
    hue_to_z2m_color,
    seconds_to_z2m_duration,
)
from custom_components.notify_lights.const import Effect, Speed
from custom_components.notify_lights.notification import Notification


# --- Conversion helper tests ---


def test_hue_to_z2m_color():
    assert hue_to_z2m_color(0) == 0
    assert hue_to_z2m_color(120) == 85
    assert hue_to_z2m_color(240) == 170
    assert hue_to_z2m_color(360) == 255


def test_seconds_to_z2m_duration():
    assert seconds_to_z2m_duration(0) == 255    # indefinite for stateful
    assert seconds_to_z2m_duration(30) == 30    # direct seconds
    assert seconds_to_z2m_duration(60) == 60
    assert seconds_to_z2m_duration(120) == 62   # 2 minutes -> 60 + 2
    assert seconds_to_z2m_duration(3600) == 121  # 1 hour -> 120 + 1
    assert seconds_to_z2m_duration(86400) == 144  # 24 hours -> 120 + 24


def test_effect_to_z2m_string():
    assert effect_to_z2m_string(Effect.SOLID, Speed.MEDIUM) == "solid"
    assert effect_to_z2m_string(Effect.BLINK, Speed.SLOW) == "slow_blink"
    assert effect_to_z2m_string(Effect.BLINK, Speed.MEDIUM) == "medium_blink"
    assert effect_to_z2m_string(Effect.BLINK, Speed.FAST) == "fast_blink"
    assert effect_to_z2m_string(Effect.CHASE, Speed.SLOW) == "slow_chase"
    assert effect_to_z2m_string(Effect.CHASE, Speed.MEDIUM) == "chase"
    assert effect_to_z2m_string(Effect.CHASE, Speed.FAST) == "fast_chase"
    assert effect_to_z2m_string(Effect.FALLING, Speed.FAST) == "fast_falling"
    assert effect_to_z2m_string(Effect.AURORA, Speed.FAST) == "aurora"


# --- Adapter render/clear tests ---


def _make_notif(
    name="test",
    color=0,
    effect=Effect.SOLID,
    speed=Speed.MEDIUM,
    duration=0,
    priority=50,
    brightness=100,
):
    return Notification(
        name=name,
        color=color,
        brightness=brightness,
        effect=effect,
        effect_speed=speed,
        duration=duration,
        priority=priority,
        targets=["light.lr"],
    )


@pytest.mark.asyncio
async def test_render_single_notification_uses_full_bar():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBlueZ2MAdapter(hass)
    active = [(_make_notif(color=120, effect=Effect.PULSE), 1.0)]

    await adapter.render("inovelli_dimmer", active)

    hass.services.async_call.assert_called_once()
    call_args = hass.services.async_call.call_args
    assert call_args[0][0] == "mqtt"
    assert call_args[0][1] == "publish"
    service_data = call_args[0][2]
    assert service_data["topic"] == "zigbee2mqtt/inovelli_dimmer/set"
    payload = json.loads(service_data["payload"])
    assert payload["led_effect"]["effect"] == "pulse"
    assert payload["led_effect"]["color"] == 85   # 120 * 255 / 360
    assert payload["led_effect"]["level"] == 100
    assert payload["led_effect"]["duration"] == 255  # indefinite (duration=0)


@pytest.mark.asyncio
async def test_render_multiple_uses_top_priority_only():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBlueZ2MAdapter(hass)
    active = [
        (_make_notif("high", priority=90), 1.0),
        (_make_notif("low", priority=10, color=120), 2.0),
    ]

    await adapter.render("inovelli_dimmer", active)

    # v1: only top-priority notification rendered on full bar
    hass.services.async_call.assert_called_once()


@pytest.mark.asyncio
async def test_render_empty_clears():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBlueZ2MAdapter(hass)

    await adapter.render("inovelli_dimmer", [])

    hass.services.async_call.assert_called_once()
    call_args = hass.services.async_call.call_args
    payload = json.loads(call_args[0][2]["payload"])
    assert payload["led_effect"]["effect"] == "clear_effect"


@pytest.mark.asyncio
async def test_clear_sends_clear_effect():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBlueZ2MAdapter(hass)

    await adapter.clear("inovelli_dimmer")

    hass.services.async_call.assert_called_once()
    call_args = hass.services.async_call.call_args
    payload = json.loads(call_args[0][2]["payload"])
    assert payload["led_effect"]["effect"] == "clear_effect"
