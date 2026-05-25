"""End-to-end smoke tests for the full Notify Lights round-trip.

Exercises the wiring between coordinator, adapter registry, switch, and button
without requiring a real Home Assistant installation.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.notify_lights.coordinator import NotifyLightsCoordinator
from custom_components.notify_lights.adapter import AdapterRegistry, NotificationAdapter
from custom_components.notify_lights.notification import Notification
from custom_components.notify_lights.const import Effect, Speed, DOMAIN
from custom_components.notify_lights.switch import NotificationSwitch
from custom_components.notify_lights.button import NotificationButton


class MockAdapter(NotificationAdapter):
    manufacturer = "Inovelli"
    model_patterns = ["VZM31*"]
    max_concurrent = 1
    supported_effects = set(Effect)
    effect_fallbacks = {}

    def __init__(self):
        self.render_calls = []
        self.clear_calls = []

    async def render(self, target, active):
        self.render_calls.append((target, list(active)))

    async def clear(self, target):
        self.clear_calls.append(target)


def _make_registries(device_name="office_dimmer"):
    """Create mock entity and device registries."""
    entity_entry = MagicMock()
    entity_entry.device_id = "device_123"

    entity_registry = MagicMock()
    entity_registry.async_get.return_value = entity_entry

    device_entry = MagicMock()
    device_entry.manufacturer = "Inovelli"
    device_entry.model = "VZM31-SN"
    device_entry.name = device_name

    device_registry = MagicMock()
    device_registry.async_get.return_value = device_entry

    return entity_registry, device_registry


@pytest.mark.asyncio
async def test_switch_round_trip():
    """Full round-trip: switch on → adapter renders → switch off → adapter clears."""
    hass = MagicMock()
    entity_reg, device_reg = _make_registries("office_dimmer")
    adapter = MockAdapter()

    registry = AdapterRegistry()
    registry.register(adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)

    notif = Notification(
        name="heating",
        color=120,
        brightness=80,
        effect=Effect.PULSE,
        effect_speed=Speed.FAST,
        duration=0,
        priority=50,
        targets=["light.office_dimmer"],
    )

    switch = NotificationSwitch(coordinator, notif)

    # Turn on
    await switch.async_turn_on()
    assert switch.is_on is True
    assert len(adapter.render_calls) == 1
    target, active = adapter.render_calls[0]
    assert target == "office_dimmer"
    assert len(active) == 1
    assert active[0][0].name == "heating"
    assert active[0][0].color == 120

    # Turn off
    await switch.async_turn_off()
    assert switch.is_on is False
    assert len(adapter.render_calls) == 2
    target, active = adapter.render_calls[1]
    assert target == "office_dimmer"
    assert len(active) == 0  # empty = cleared


@pytest.mark.asyncio
async def test_button_activates_and_schedules_deactivation():
    """Button press → adapter renders → auto-deactivate callback → adapter clears."""
    hass = MagicMock()
    entity_reg, device_reg = _make_registries("kitchen_switch")
    adapter = MockAdapter()

    registry = AdapterRegistry()
    registry.register(adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)

    notif = Notification(
        name="doorbell_flash",
        color=0,
        brightness=100,
        effect=Effect.BLINK,
        effect_speed=Speed.FAST,
        duration=5,
        priority=90,
        targets=["light.kitchen_switch"],
    )

    captured_callback = None

    def fake_call_later(hass, delay, callback):
        nonlocal captured_callback
        captured_callback = callback
        assert delay == 5
        return MagicMock()

    button = NotificationButton(coordinator, notif, hass)

    with patch("custom_components.notify_lights.button.async_call_later", side_effect=fake_call_later):
        await button.async_press()

    # Verify activation happened
    assert len(adapter.render_calls) == 1
    target, active = adapter.render_calls[0]
    assert target == "kitchen_switch"
    assert active[0][0].name == "doorbell_flash"

    # Simulate timer expiry
    assert captured_callback is not None
    await captured_callback()

    # Verify deactivation
    assert len(adapter.render_calls) == 2
    target, active = adapter.render_calls[1]
    assert target == "kitchen_switch"
    assert len(active) == 0


@pytest.mark.asyncio
async def test_multiple_notifications_priority_ordering():
    """Two switches on same target, higher priority renders on top."""
    hass = MagicMock()
    entity_reg, device_reg = _make_registries("office_dimmer")
    adapter = MockAdapter()

    registry = AdapterRegistry()
    registry.register(adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)

    low = Notification(
        name="background", color=120, brightness=50,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=0, priority=10,
        targets=["light.office_dimmer"],
    )
    high = Notification(
        name="urgent_alert", color=0, brightness=100,
        effect=Effect.BLINK, effect_speed=Speed.FAST,
        duration=0, priority=90,
        targets=["light.office_dimmer"],
    )

    switch_low = NotificationSwitch(coordinator, low)
    switch_high = NotificationSwitch(coordinator, high)

    await switch_low.async_turn_on()
    await switch_high.async_turn_on()

    # Last render should have both, high priority first
    target, active = adapter.render_calls[-1]
    assert active[0][0].name == "urgent_alert"
    assert active[1][0].name == "background"

    # Turn off high priority → only low remains
    await switch_high.async_turn_off()
    target, active = adapter.render_calls[-1]
    assert len(active) == 1
    assert active[0][0].name == "background"
