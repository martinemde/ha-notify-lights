"""Tests for the Inovelli Blue Z2M adapter."""

import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.notify_lights.adapters.inovelli_blue_z2m import (
    InovelliBlueZ2MAdapter,
    InovelliBlueZ2MState,
    build_z2m_desired_state,
    build_z2m_render_payloads,
    effect_to_z2m_string,
    hue_to_z2m_color,
    individual_effect_to_z2m_string,
    seconds_to_z2m_duration,
)
from custom_components.notify_lights.const import DisplayMode, Effect, Speed
from custom_components.notify_lights.notification import Notification

# --- Conversion helper tests ---


def test_hue_to_z2m_color():
    assert hue_to_z2m_color(0) == 0
    assert hue_to_z2m_color(120) == 85
    assert hue_to_z2m_color(240) == 170
    assert hue_to_z2m_color(360) == 255


def test_seconds_to_z2m_duration():
    assert seconds_to_z2m_duration(0) == 255  # indefinite for stateful
    assert seconds_to_z2m_duration(30) == 30  # direct seconds
    assert seconds_to_z2m_duration(60) == 60
    assert seconds_to_z2m_duration(120) == 62  # 2 minutes -> 60 + 2
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


def test_individual_effect_to_z2m_string_uses_supported_effects():
    assert individual_effect_to_z2m_string(Effect.BLINK, Speed.SLOW) == "slow_blink"
    assert individual_effect_to_z2m_string(Effect.BLINK, Speed.MEDIUM) == "fast_blink"
    assert individual_effect_to_z2m_string(Effect.FALLING, Speed.FAST) == "falling"
    assert individual_effect_to_z2m_string(Effect.RISING, Speed.SLOW) == "rising"
    assert individual_effect_to_z2m_string(Effect.CHASE, Speed.FAST) == "chase"


# --- Adapter render/clear tests ---


def test_target_for_device_uses_stable_zigbee_ieee_address():
    adapter = InovelliBlueZ2MAdapter(MagicMock())
    device = MagicMock()
    device.name = "Great Room Ceiling Lights"
    device.identifiers = {
        ("mqtt", "zigbee2mqtt_0x5c3aa2fffe55df3b"),
    }

    assert adapter.target_for_device(device) == "0x5c3aa2fffe55df3b"


def test_target_for_device_falls_back_to_device_name():
    adapter = InovelliBlueZ2MAdapter(MagicMock())
    device = MagicMock()
    device.name = "inovelli_dimmer"
    device.identifiers = set()

    assert adapter.target_for_device(device) == "inovelli_dimmer"


def _make_notif(
    name="test",
    color=0,
    effect=Effect.SOLID,
    speed=Speed.MEDIUM,
    duration=0,
    priority=50,
    brightness=100,
    display_mode=DisplayMode.FULL,
):
    return Notification(
        name=name,
        display_name=name.replace("_", " ").title(),
        color=color,
        brightness=brightness,
        effect=effect,
        effect_speed=speed,
        duration=duration,
        priority=priority,
        display_mode=display_mode,
    )


@pytest.mark.asyncio
async def test_render_single_notification_uses_full_bar():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBlueZ2MAdapter(hass)
    active = [(_make_notif(color=120, effect=Effect.PULSE), 1.0)]

    await adapter.render("inovelli_dimmer", active)

    assert hass.services.async_call.call_count == 8
    payloads = [
        json.loads(call.args[2]["payload"])
        for call in hass.services.async_call.call_args_list
    ]
    assert payloads[0]["led_effect"] == {
        "effect": "pulse",
        "color": 85,
        "level": 100,
        "duration": 255,
    }
    assert all(
        payload["individual_led_effect"]["effect"] == "clear_effect"
        for payload in payloads[1:]
    )
    call_args = hass.services.async_call.call_args_list[0]
    assert call_args[0][0] == "mqtt"
    assert call_args[0][1] == "publish"
    service_data = call_args[0][2]
    assert service_data["topic"] == "zigbee2mqtt/inovelli_dimmer/set"
    payload = json.loads(service_data["payload"])
    assert payload["led_effect"]["effect"] == "pulse"


def test_single_indicator_uses_one_individual_led():
    notification = _make_notif(
        "heating", effect=Effect.PULSE, display_mode=DisplayMode.INDICATOR
    )

    payloads = build_z2m_render_payloads([(notification, 1.0)])

    assert len(payloads) == 8
    assert payloads[0]["individual_led_effect"]["led"] == "1"
    assert payloads[0]["individual_led_effect"]["effect"] == "pulse"
    assert all(
        payload["individual_led_effect"]["effect"] == "clear_effect"
        for payload in payloads[1:7]
    )
    assert payloads[-1]["led_effect"]["effect"] == "clear_effect"


@pytest.mark.asyncio
async def test_render_multiple_layers_second_priority_at_bottom():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBlueZ2MAdapter(hass)
    active = [
        (_make_notif("high", priority=90, color=0, effect=Effect.PULSE), 1.0),
        (_make_notif("low", priority=10, color=120, effect=Effect.BLINK), 2.0),
    ]

    await adapter.render("inovelli_dimmer", active)

    # Keep the priority notification on the full-bar layer and shadow only
    # its bottom pixel with the minor notification.
    assert hass.services.async_call.call_count == 8
    payloads = [
        json.loads(call.args[2]["payload"])
        for call in hass.services.async_call.call_args_list
    ]
    assert payloads[0]["led_effect"] == {
        "effect": "pulse",
        "color": 0,
        "level": 100,
        "duration": 255,
    }
    bottom = payloads[1]["individual_led_effect"]
    assert bottom == {
        "led": "1",
        "effect": "solid",
        "color": 85,
        "level": 100,
        "duration": 255,
    }
    for led, payload in enumerate(payloads[2:], start=2):
        pixel = payload["individual_led_effect"]
        assert pixel["led"] == str(led)
        assert pixel["effect"] == "clear_effect"


@pytest.mark.asyncio
async def test_render_group_publishes_once_per_payload_to_group_topic():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBlueZ2MAdapter(hass)
    active = [(_make_notif(color=270, effect=Effect.SOLID), 1.0)]
    members = ["0xaaa", "0xbbb", "0xccc"]

    with patch(
        "custom_components.notify_lights.adapters.inovelli_blue_z2m.asyncio.sleep",
        new=AsyncMock(),
    ) as sleep:
        await adapter.render_group("notify/security", active, members)

    assert hass.services.async_call.call_count == 8
    assert sleep.await_args_list == [call(0.2)] * 8
    assert {
        call.args[2]["topic"] for call in hass.services.async_call.call_args_list
    } == {"zigbee2mqtt/notify/security/set"}

    # Group state is remembered for every physical member. An identical
    # unicast render needs no command at all.
    hass.services.async_call.reset_mock()
    await adapter.render("0xbbb", active)
    hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_render_sends_union_of_member_deltas():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBlueZ2MAdapter(hass)
    full = _make_notif("full", color=270)
    indicator = _make_notif("minor", color=120, priority=10)
    members = ["0xaaa", "0xbbb"]

    with patch(
        "custom_components.notify_lights.adapters.inovelli_blue_z2m.asyncio.sleep",
        new=AsyncMock(),
    ):
        await adapter.render_group("notify/security", [(full, 1.0)], members)
        await adapter.render("0xaaa", [(full, 1.0), (indicator, 2.0)])
        hass.services.async_call.reset_mock()
        await adapter.render_group("notify/security", [(full, 1.0)], members)

    hass.services.async_call.assert_awaited_once()
    payload = json.loads(hass.services.async_call.call_args.args[2]["payload"])
    assert payload["individual_led_effect"]["led"] == "1"
    assert payload["individual_led_effect"]["effect"] == "clear_effect"


@pytest.mark.asyncio
async def test_direct_render_does_not_use_group_command_pacing():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBlueZ2MAdapter(hass)
    active = [(_make_notif(color=270, effect=Effect.SOLID), 1.0)]

    with patch(
        "custom_components.notify_lights.adapters.inovelli_blue_z2m.asyncio.sleep",
        new=AsyncMock(),
    ) as sleep:
        await adapter.render("0xaaa", active)

    sleep.assert_not_awaited()


def test_render_payloads_ignore_notifications_below_second_priority():
    active = [
        (_make_notif("high", priority=90, color=0), 1.0),
        (_make_notif("middle", priority=50, color=120), 2.0),
        (_make_notif("low", priority=10, color=240), 3.0),
    ]

    desired = build_z2m_desired_state(active)

    assert desired.full_bar.color == 0
    assert desired.individual_pixels[0].color == 85
    assert all(pixel is None for pixel in desired.individual_pixels[1:])


def test_z2m_state_model_applies_layered_command_stack():
    active = [
        (_make_notif("high", color=240, effect=Effect.PULSE), 1.0),
        (_make_notif("low", color=60, effect=Effect.BLINK), 2.0),
    ]
    model = InovelliBlueZ2MState()

    model.apply_all(build_z2m_render_payloads(active))

    assert model.pixels[0].color == 42
    assert model.pixels[0].effect == "solid"
    assert [pixel.color for pixel in model.pixels[1:]] == [170] * 6
    assert [pixel.effect for pixel in model.pixels[1:]] == ["pulse"] * 6


def test_z2m_state_model_full_bar_replaces_layered_state():
    high = _make_notif("high", color=240, effect=Effect.PULSE)
    low = _make_notif("low", color=60)
    model = InovelliBlueZ2MState()
    layered = [(high, 1.0), (low, 2.0)]
    model.apply_all(build_z2m_render_payloads(layered))

    full = [(low, 2.0)]
    model.apply_all(
        build_z2m_render_payloads(full, previous=build_z2m_desired_state(layered))
    )

    assert [pixel.color for pixel in model.pixels] == [42] * 7
    assert [pixel.effect for pixel in model.pixels] == ["solid"] * 7

    model.apply_all(
        build_z2m_render_payloads([], previous=build_z2m_desired_state(full))
    )
    assert model.pixels == [None] * 7


def test_indicator_overrides_full_bar_with_one_write_and_clear_resumes_it():
    full = _make_notif("priority", priority=90, color=0, effect=Effect.PULSE)
    minor = _make_notif("minor", priority=10, color=120)
    full_active = [(full, 1.0)]
    layered_active = [(full, 1.0), (minor, 2.0)]
    model = InovelliBlueZ2MState()
    model.apply_all(build_z2m_render_payloads(full_active))

    add_indicator = build_z2m_render_payloads(
        layered_active, previous=build_z2m_desired_state(full_active)
    )
    assert len(add_indicator) == 1
    assert add_indicator[0]["individual_led_effect"]["led"] == "1"
    model.apply_all(add_indicator)
    assert model.pixels[0].color == 85
    assert [pixel.color for pixel in model.pixels[1:]] == [0] * 6

    remove_indicator = build_z2m_render_payloads(
        full_active, previous=build_z2m_desired_state(layered_active)
    )
    assert len(remove_indicator) == 1
    assert remove_indicator[0]["individual_led_effect"]["effect"] == "clear_effect"
    model.apply_all(remove_indicator)
    assert [pixel.color for pixel in model.pixels] == [0] * 7


def test_unchanged_stateful_layer_sends_nothing():
    notification = _make_notif("stateful", duration=0)
    previous = build_z2m_desired_state([(notification, 1.0)])

    assert build_z2m_render_payloads([(notification, 2.0)], previous=previous) == []


def test_repressed_momentary_layer_refreshes_hardware_timer():
    notification = _make_notif(
        "momentary",
        duration=10,
        priority=10,
        display_mode=DisplayMode.INDICATOR,
    )
    previous = build_z2m_desired_state([(notification, 1.0)])

    payloads = build_z2m_render_payloads([(notification, 2.0)], previous=previous)

    assert len(payloads) == 1
    assert payloads[0]["individual_led_effect"]["led"] == "1"
    assert payloads[0]["individual_led_effect"]["duration"] == 10


@pytest.mark.asyncio
async def test_garage_and_lock_sequence_clears_stacked_individual_layers():
    """Regression: a cleared full bar must not reveal an old stacked layout."""
    model = InovelliBlueZ2MState()
    hass = MagicMock()

    async def apply_publish(_domain, _service, service_data):
        model.apply(json.loads(service_data["payload"]))

    hass.services.async_call = AsyncMock(side_effect=apply_publish)
    adapter = InovelliBlueZ2MAdapter(hass)
    garage_open = _make_notif("garage_open", priority=75, color=270)
    door_unlocked = _make_notif(
        "door_unlocked", priority=80, color=0, effect=Effect.PULSE
    )
    garage_closing = _make_notif(
        "garage_closing", priority=75, color=270, effect=Effect.FALLING
    )

    await adapter.render("garage_switch", [(garage_open, 1.0)])
    await adapter.render("garage_switch", [(door_unlocked, 2.0), (garage_open, 1.0)])
    await adapter.render("garage_switch", [(garage_open, 1.0)])
    await adapter.render("garage_switch", [(garage_closing, 3.0)])
    await adapter.render("garage_switch", [])

    assert model.pixels == [None] * 7


@pytest.mark.asyncio
async def test_failed_transition_forgets_cached_state():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBlueZ2MAdapter(hass)
    full = _make_notif("full", priority=90)
    minor = _make_notif("minor", priority=10)
    await adapter.render("garage_switch", [(full, 1.0)])

    hass.services.async_call = AsyncMock(side_effect=RuntimeError("publish failed"))
    with pytest.raises(RuntimeError, match="publish failed"):
        await adapter.render("garage_switch", [(full, 1.0), (minor, 2.0)])

    # The failed write may still have reached the MQTT broker, so the next
    # attempt must reconcile all eight hardware layers from unknown state.
    hass.services.async_call = AsyncMock()
    await adapter.render("garage_switch", [(full, 1.0), (minor, 2.0)])
    assert hass.services.async_call.await_count == 8


def test_z2m_state_model_validates_led_number():
    model = InovelliBlueZ2MState()

    with pytest.raises(ValueError, match="LED must be 1-7"):
        model.apply(
            {
                "individual_led_effect": {
                    "led": "8",
                    "effect": "solid",
                    "color": 0,
                    "level": 100,
                    "duration": 255,
                }
            }
        )


@pytest.mark.asyncio
async def test_render_empty_clears():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBlueZ2MAdapter(hass)

    await adapter.render("inovelli_dimmer", [])

    assert hass.services.async_call.call_count == 8
    call_args = hass.services.async_call.call_args_list[-1]
    payload = json.loads(call_args[0][2]["payload"])
    assert payload["led_effect"]["effect"] == "clear_effect"


@pytest.mark.asyncio
async def test_clear_sends_clear_effect():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBlueZ2MAdapter(hass)

    await adapter.render("inovelli_dimmer", [])
    hass.services.async_call.reset_mock()
    await adapter.clear("inovelli_dimmer")

    # Explicit teardown stays defensive even when the cache already says empty.
    assert hass.services.async_call.call_count == 8
    call_args = hass.services.async_call.call_args_list[-1]
    payload = json.loads(call_args[0][2]["payload"])
    assert payload["led_effect"]["effect"] == "clear_effect"
