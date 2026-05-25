"""End-to-end smoke tests for the pool-based Notify Lights architecture."""
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


TARGETS = ["light.office_dimmer"]
POOL_A = "pool_entry_a"
POOL_B = "pool_entry_b"


def _make_entry(entry_id, name="Test Pool"):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"name": name}
    return entry


def _make_registries(device_name="office_dimmer"):
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
    """Full round-trip: switch on -> adapter renders -> switch off -> adapter clears."""
    hass = MagicMock()
    hass.states.get.return_value = None
    entity_reg, device_reg = _make_registries("office_dimmer")
    adapter = MockAdapter()
    registry = AdapterRegistry()
    registry.register(adapter)
    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)

    notif = Notification(
        name="heating", display_name="Heating", color=120, brightness=80,
        effect=Effect.PULSE, effect_speed=Speed.FAST,
        duration=0, priority=50,
    )

    entry = _make_entry(POOL_A)
    switch = NotificationSwitch(coordinator, notif, TARGETS, entry)

    await switch.async_turn_on()
    assert switch.is_on is True
    assert len(adapter.render_calls) == 1
    target, active = adapter.render_calls[0]
    assert target == "office_dimmer"
    assert len(active) == 1
    assert active[0][0].name == "heating"

    await switch.async_turn_off()
    assert switch.is_on is False
    assert len(adapter.render_calls) == 2
    target, active = adapter.render_calls[1]
    assert target == "office_dimmer"
    assert len(active) == 0


@pytest.mark.asyncio
async def test_button_activates_and_schedules_deactivation():
    """Button press -> adapter renders -> timer fires -> adapter clears."""
    hass = MagicMock()
    hass.states.get.return_value = None
    entity_reg, device_reg = _make_registries("kitchen_switch")
    adapter = MockAdapter()
    registry = AdapterRegistry()
    registry.register(adapter)
    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)

    notif = Notification(
        name="doorbell_flash", display_name="Doorbell Flash",
        color=0, brightness=100,
        effect=Effect.BLINK, effect_speed=Speed.FAST,
        duration=5, priority=90,
    )

    targets = ["light.kitchen_switch"]
    captured_callback = None

    def fake_call_later(hass, delay, callback):
        nonlocal captured_callback
        captured_callback = callback
        assert delay == 5
        return MagicMock()

    entry = _make_entry(POOL_A)
    button = NotificationButton(coordinator, notif, targets, entry, hass)

    with patch("custom_components.notify_lights.button.async_call_later", side_effect=fake_call_later):
        await button.async_press()

    assert len(adapter.render_calls) == 1
    target, active = adapter.render_calls[0]
    assert target == "kitchen_switch"
    assert active[0][0].name == "doorbell_flash"

    assert captured_callback is not None
    await captured_callback()

    assert len(adapter.render_calls) == 2
    target, active = adapter.render_calls[1]
    assert len(active) == 0


@pytest.mark.asyncio
async def test_cross_pool_priority_on_shared_switch():
    """Two pools targeting the same switch resolve by priority."""
    hass = MagicMock()
    hass.states.get.return_value = None
    entity_reg, device_reg = _make_registries("office_dimmer")
    adapter = MockAdapter()
    registry = AdapterRegistry()
    registry.register(adapter)
    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)

    low = Notification(
        name="background", display_name="Background",
        color=120, brightness=50,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=0, priority=10,
    )
    high = Notification(
        name="urgent_alert", display_name="Urgent Alert",
        color=0, brightness=100,
        effect=Effect.BLINK, effect_speed=Speed.FAST,
        duration=0, priority=90,
    )

    entry_a = _make_entry(POOL_A)
    entry_b = _make_entry(POOL_B)
    switch_low = NotificationSwitch(coordinator, low, TARGETS, entry_a)
    switch_high = NotificationSwitch(coordinator, high, TARGETS, entry_b)

    await switch_low.async_turn_on()
    await switch_high.async_turn_on()

    target, active = adapter.render_calls[-1]
    assert active[0][0].name == "urgent_alert"
    assert active[1][0].name == "background"

    await switch_high.async_turn_off()
    target, active = adapter.render_calls[-1]
    assert len(active) == 1
    assert active[0][0].name == "background"


@pytest.mark.asyncio
async def test_same_notification_different_pools_independent():
    """Same notification name from two pools are tracked independently."""
    hass = MagicMock()
    hass.states.get.return_value = None
    entity_reg, device_reg = _make_registries("office_dimmer")
    adapter = MockAdapter()
    registry = AdapterRegistry()
    registry.register(adapter)
    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)

    notif = Notification(
        name="heating", display_name="Heating",
        color=120, brightness=80,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=0, priority=50,
    )

    entry_a = _make_entry(POOL_A)
    entry_b = _make_entry(POOL_B)
    switch_a = NotificationSwitch(coordinator, notif, TARGETS, entry_a)
    switch_b = NotificationSwitch(coordinator, notif, TARGETS, entry_b)

    await switch_a.async_turn_on()
    await switch_b.async_turn_on()

    target, active = adapter.render_calls[-1]
    assert len(active) == 2

    await switch_a.async_turn_off()
    target, active = adapter.render_calls[-1]
    assert len(active) == 1
