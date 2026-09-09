"""Tests for the per-entry brightness ceiling / active-state light entity."""

from unittest.mock import MagicMock

import pytest

from custom_components.notify_lights.adapter import AdapterRegistry, NotificationAdapter
from custom_components.notify_lights.const import Effect, Speed
from custom_components.notify_lights.coordinator import NotifyLightsCoordinator
from custom_components.notify_lights.light import NotifyLightsGroupLight
from custom_components.notify_lights.notification import Notification

TARGETS = ["light.office_dimmer"]
ENTRY_ID = "pool_entry_1"


class MockAdapter(NotificationAdapter):
    manufacturer = "Inovelli"
    model_patterns = ["VZM31*"]
    max_concurrent = 2
    supported_effects = set(Effect)
    effect_fallbacks = {}

    async def render(self, target, active):
        pass

    async def clear(self, target):
        pass


def _make_entry(entry_id=ENTRY_ID, name="Test Pool"):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"name": name}
    return entry


def _make_notif(name="heating", priority=50, color=120, effect=Effect.PULSE):
    return Notification(
        name=name,
        display_name=name.replace("_", " ").title(),
        color=color,
        brightness=100,
        effect=effect,
        effect_speed=Speed.MEDIUM,
        duration=0,
        priority=priority,
    )


def _make_coordinator():
    hass = MagicMock()
    hass.states.get.return_value = None
    entity_entry = MagicMock()
    entity_entry.device_id = "device_123"
    entity_registry = MagicMock()
    entity_registry.async_get.return_value = entity_entry
    device_entry = MagicMock()
    device_entry.manufacturer = "Inovelli"
    device_entry.model = "VZM31-SN"
    device_entry.name = "office_dimmer"
    device_registry = MagicMock()
    device_registry.async_get.return_value = device_entry
    registry = AdapterRegistry()
    registry.register(MockAdapter())
    return NotifyLightsCoordinator(hass, registry, entity_registry, device_registry)


def _wire_hass(light, adapt_brightness=None):
    """Give a light a hass whose light.turn_on routes back into the entity.

    Passing `adapt_brightness` stands in for Adaptive Lighting's service-call
    interceptor, which injects its adapted brightness into the call's data
    before the entity ever sees it.
    """
    calls = []

    async def _async_call(domain, service, data, blocking=False):
        calls.append((domain, service, dict(data)))
        params = {k: v for k, v in data.items() if k != "entity_id"}
        if adapt_brightness is not None:
            params["brightness"] = adapt_brightness
        await light.async_turn_on(**params)

    light.hass = MagicMock()
    light.hass.services.async_call = _async_call
    light.entity_id = "light.test_pool_brightness"
    return calls


def test_unique_id_includes_entry_id():
    light = NotifyLightsGroupLight(_make_coordinator(), _make_entry(), TARGETS)
    assert light.unique_id == f"notify_lights_{ENTRY_ID}_brightness"


def test_off_with_nothing_active():
    light = NotifyLightsGroupLight(_make_coordinator(), _make_entry(), TARGETS)
    assert light.is_on is False
    assert light.hs_color is None
    assert light.effect is None


def test_default_brightness_is_full():
    light = NotifyLightsGroupLight(_make_coordinator(), _make_entry(), TARGETS)
    assert light.brightness == 255


@pytest.mark.asyncio
async def test_mirrors_the_active_notification():
    coordinator = _make_coordinator()
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)
    notif = _make_notif()

    await coordinator.async_activate(notif, TARGETS, ENTRY_ID)

    assert light.is_on is True
    assert light.hs_color == (120, 100)
    assert light.effect == Effect.PULSE.value
    assert light.extra_state_attributes["active_notification"] == "heating"


@pytest.mark.asyncio
async def test_mirrors_the_higher_priority_of_two_own_notifications():
    coordinator = _make_coordinator()
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)
    low = _make_notif(name="low", priority=10, color=0)
    high = _make_notif(name="high", priority=90, color=200)

    await coordinator.async_activate(low, TARGETS, ENTRY_ID)
    await coordinator.async_activate(high, TARGETS, ENTRY_ID)

    assert light.hs_color == (200, 100)


@pytest.mark.asyncio
async def test_goes_off_when_its_notification_clears():
    coordinator = _make_coordinator()
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)
    notif = _make_notif()

    await coordinator.async_activate(notif, TARGETS, ENTRY_ID)
    await coordinator.async_deactivate(notif, TARGETS, ENTRY_ID)

    assert light.is_on is False


@pytest.mark.asyncio
async def test_ignores_other_entries_notifications():
    coordinator = _make_coordinator()
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)

    await coordinator.async_activate(_make_notif(), TARGETS, "other_entry")

    assert light.is_on is False


@pytest.mark.asyncio
async def test_turn_on_sets_ceiling():
    coordinator = _make_coordinator()
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)

    await light.async_turn_on(brightness=64)

    assert light.brightness == 64
    assert coordinator.get_ceiling(ENTRY_ID) == 64


@pytest.mark.asyncio
async def test_turn_on_without_brightness_keeps_current_level():
    coordinator = _make_coordinator()
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)
    await light.async_turn_on(brightness=100)

    await light.async_turn_on()

    assert light.brightness == 100


@pytest.mark.asyncio
async def test_turn_off_zeroes_ceiling():
    coordinator = _make_coordinator()
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)

    await light.async_turn_off()

    assert light.brightness == 0
    assert coordinator.get_ceiling(ENTRY_ID) == 0


@pytest.mark.asyncio
async def test_turn_off_clears_active_notifications():
    coordinator = _make_coordinator()
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)
    await coordinator.async_activate(_make_notif(), TARGETS, ENTRY_ID)
    assert light.is_on is True

    await light.async_turn_off()

    assert light.is_on is False
    assert coordinator.entry_active_set(ENTRY_ID) == []


@pytest.mark.asyncio
async def test_turn_off_removes_the_notification_from_the_render_stack():
    """A ceiling of zero alone would still occupy the top priority slot.

    Zeroing brightness leaves the entry in the stack, so a real adapter's
    priority-based layering (e.g. the Inovelli bar's two visible slots)
    would still give it the primary slot -- rendered black -- ahead of a
    lower-priority notification from another catalog. Clearing removes it
    outright so that lower-priority notification can take the slot.
    """
    coordinator = _make_coordinator()
    render_calls = []

    class RecordingAdapter(MockAdapter):
        async def render(self, target, active):
            render_calls.append(list(active))

    coordinator._adapter_registry = AdapterRegistry()
    coordinator._adapter_registry.register(RecordingAdapter())
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)

    high = _make_notif(name="high", priority=90)
    low = _make_notif(name="low", priority=10)
    await coordinator.async_activate(high, TARGETS, ENTRY_ID)
    await coordinator.async_activate(low, TARGETS, "other_entry")

    await light.async_turn_off()

    names = [entry[0].name for entry in render_calls[-1]]
    assert names == ["low"]


@pytest.mark.asyncio
async def test_ceiling_scales_what_the_adapter_renders():
    coordinator = _make_coordinator()
    render_calls = []

    class RecordingAdapter(MockAdapter):
        async def render(self, target, active):
            render_calls.append(list(active))

    coordinator._adapter_registry = AdapterRegistry()
    coordinator._adapter_registry.register(RecordingAdapter())
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)

    await coordinator.async_activate(_make_notif(), TARGETS, ENTRY_ID)
    await light.async_turn_on(brightness=51)

    assert render_calls[-1][0][0].brightness == round(100 * 51 / 255)


@pytest.mark.asyncio
async def test_listener_triggers_state_write_on_activate():
    coordinator = _make_coordinator()
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)
    light.async_get_last_state = _no_previous_state
    _wire_hass(light)
    writes = []
    light.async_write_ha_state = lambda: writes.append(1)

    await light.async_added_to_hass()
    await coordinator.async_activate(_make_notif(), TARGETS, ENTRY_ID)

    assert writes


@pytest.mark.asyncio
async def test_activating_turns_itself_on_through_the_light_service():
    """Adaptive Lighting only adapts an 'off' -> 'on' it can tie to turn_on."""
    coordinator = _make_coordinator()
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)
    light.async_get_last_state = _no_previous_state
    calls = _wire_hass(light)

    await light.async_added_to_hass()
    await coordinator.async_activate(_make_notif(), TARGETS, ENTRY_ID)

    assert calls == [("light", "turn_on", {"entity_id": light.entity_id})]


@pytest.mark.asyncio
async def test_only_the_first_notification_announces_a_turn_on():
    coordinator = _make_coordinator()
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)
    light.async_get_last_state = _no_previous_state
    calls = _wire_hass(light)

    await light.async_added_to_hass()
    await coordinator.async_activate(_make_notif(name="first"), TARGETS, ENTRY_ID)
    await coordinator.async_activate(_make_notif(name="second"), TARGETS, ENTRY_ID)

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_adapted_brightness_lands_before_the_first_render():
    """The ceiling injected into the turn_on scales the very first render."""
    coordinator = _make_coordinator()
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)
    light.async_get_last_state = _no_previous_state
    _wire_hass(light, adapt_brightness=51)

    renders = []
    adapter = coordinator._adapter_registry.get_adapter("Inovelli", "VZM31-SN")

    async def _record(target, active):
        renders.append([n.brightness for n, _ in active])

    adapter.render = _record

    await light.async_added_to_hass()
    await coordinator.async_activate(_make_notif(), TARGETS, ENTRY_ID)

    assert renders == [[round(100 * 51 / 255)]]


@pytest.mark.asyncio
async def test_restores_ceiling_from_last_state():
    coordinator = _make_coordinator()
    light = NotifyLightsGroupLight(coordinator, _make_entry(), TARGETS)
    previous = MagicMock()
    previous.attributes = {"brightness": 77}
    light.async_get_last_state = _return(previous)

    await light.async_added_to_hass()

    assert coordinator.get_ceiling(ENTRY_ID) == 77


async def _no_previous_state():
    return None


def _return(value):
    async def _get():
        return value

    return _get


@pytest.mark.asyncio
async def test_setup_entry_creates_the_catalog_light():
    from custom_components.notify_lights import light as light_mod
    from custom_components.notify_lights.const import DOMAIN

    hass = MagicMock()
    coordinator = _make_coordinator()
    hass.data = {
        DOMAIN: {
            ENTRY_ID: {
                "coordinator": coordinator,
                "entry_targets": TARGETS,
            }
        }
    }

    added = []
    await light_mod.async_setup_entry(
        hass, _make_entry(), lambda ents: added.extend(ents)
    )

    assert len(added) == 1
    assert added[0].unique_id == f"notify_lights_{ENTRY_ID}_brightness"
