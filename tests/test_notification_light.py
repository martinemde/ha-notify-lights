"""Tests for the per-notification light: one rule, rendered as a light."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.notify_lights.adapter import AdapterRegistry, NotificationAdapter
from custom_components.notify_lights.const import DOMAIN, Effect, Speed
from custom_components.notify_lights.coordinator import NotifyLightsCoordinator
from custom_components.notify_lights.light import (
    EFFECT_NAMES,
    NotificationLight,
    async_setup_entry,
)
from custom_components.notify_lights.notification import Notification

TARGETS = ["light.office_dimmer"]
ENTRY_ID = "catalog_entry_1"


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


def _make_entry(notifications=None):
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = {"name": "Home Notifications"}
    entry.options = {
        "targets": {"entity_id": TARGETS},
        "notifications": notifications if notifications is not None else {},
    }
    return entry


def _make_notif(**overrides):
    fields = {
        "name": "fridge_ajar",
        "display_name": "Fridge ajar",
        "color": 21,
        "brightness": 100,
        "effect": Effect.PULSE,
        "effect_speed": Speed.MEDIUM,
        "duration": 0,
        "priority": 85,
    }
    fields.update(overrides)
    return Notification(**fields)


def _mock_coordinator():
    """An AsyncMock whose synchronous listener API stays synchronous."""
    coordinator = AsyncMock()
    coordinator.async_add_entry_listener = MagicMock(return_value=lambda: None)
    coordinator.entry_active_set = MagicMock(return_value=[])
    return coordinator


def _make_light(notification=None, entry=None, coordinator=None, hass=None):
    light = NotificationLight(
        coordinator or _mock_coordinator(),
        notification or _make_notif(),
        TARGETS,
        entry or _make_entry(),
    )
    light.hass = hass or MagicMock()
    return light


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


def _state(value, **attributes):
    state = MagicMock()
    state.state = value
    state.attributes = attributes
    return state


# --- identity -------------------------------------------------------------


def test_name_leads_with_a_sortable_priority():
    assert _make_light().name == "085 Fridge ajar"
    assert _make_light(_make_notif(priority=100)).name == "100 Fridge ajar"
    assert _make_light(_make_notif(priority=5)).name == "005 Fridge ajar"


def test_entity_id_is_built_without_the_priority():
    """Re-prioritizing a rule must not move its entity ID."""
    assert _make_light().suggested_object_id == "Fridge ajar"


def test_it_is_configuration_not_a_control():
    assert _make_light().entity_category == "config"


def test_unique_id_survives_from_the_switch_it_replaces():
    assert _make_light().unique_id == f"notify_lights_{ENTRY_ID}_fridge_ajar"


# --- appearance -----------------------------------------------------------


def test_it_shows_the_notification_it_renders():
    light = _make_light(_make_notif(color=120, brightness=80, effect=Effect.BLINK))
    assert light.brightness == 204
    assert light.hs_color == (120.0, 100.0)
    assert light.effect == "blink medium"


def test_speedless_effects_drop_the_speed_from_their_name():
    assert _make_light(_make_notif(effect=Effect.SOLID)).effect == "solid"
    assert _make_light(_make_notif(effect=Effect.PULSE)).effect == "pulse"
    assert _make_light(_make_notif(effect=Effect.AURORA)).effect == "aurora"
    assert "blink slow" in EFFECT_NAMES
    assert "pulse medium" not in EFFECT_NAMES


def test_white_is_reachable_by_desaturating():
    light = _make_light(_make_notif(color="white"))
    assert light.hs_color == (0.0, 0.0)


@pytest.mark.asyncio
async def test_turning_on_with_a_color_restyles_the_notification():
    light = _make_light()
    await light.async_turn_on(hs_color=(240.0, 100.0), brightness=128)
    assert light._notification.color == 240
    assert light._notification.brightness == 50
    activated = light._coordinator.async_activate.call_args[0][0]
    assert activated.color == 240
    assert activated.brightness == 50


@pytest.mark.asyncio
async def test_a_desaturated_turn_on_asks_for_white():
    light = _make_light()
    await light.async_turn_on(hs_color=(37.0, 0.0))
    assert light._notification.color == 360


@pytest.mark.asyncio
async def test_choosing_an_effect_sets_both_effect_and_speed():
    light = _make_light()
    await light.async_turn_on(effect="blink fast")
    assert light._notification.effect is Effect.BLINK
    assert light._notification.effect_speed is Speed.FAST


@pytest.mark.asyncio
async def test_a_speedless_effect_leaves_the_stored_speed_alone():
    light = _make_light(_make_notif(effect=Effect.BLINK, effect_speed=Speed.FAST))
    await light.async_turn_on(effect="pulse")
    assert light._notification.effect is Effect.PULSE
    assert light._notification.effect_speed is Speed.FAST


@pytest.mark.asyncio
async def test_an_unknown_effect_is_ignored():
    light = _make_light()
    await light.async_turn_on(effect="disco")
    assert light._notification.effect is Effect.PULSE


@pytest.mark.asyncio
async def test_restyling_is_written_back_to_the_catalog():
    entry = _make_entry({"fridge_ajar": {"slug": "fridge_ajar", "priority": 85}})
    light = _make_light(entry=entry)
    await light.async_turn_on(hs_color=(120.0, 100.0), effect="chase slow")

    _, kwargs = light.hass.config_entries.async_update_entry.call_args
    saved = kwargs["options"]["notifications"]["fridge_ajar"]
    assert saved["color"] == 120
    assert saved["effect"] == "chase"
    assert saved["effect_speed"] == "slow"
    assert saved["priority"] == 85


@pytest.mark.asyncio
async def test_a_bare_turn_on_writes_nothing_back():
    light = _make_light()
    await light.async_turn_on()
    light.hass.config_entries.async_update_entry.assert_not_called()


# --- activation -----------------------------------------------------------


@pytest.mark.asyncio
async def test_turning_on_activates_the_notification():
    light = _make_light()
    await light.async_turn_on()
    assert light.is_on is True
    light._coordinator.async_activate.assert_called_once_with(
        light._notification, TARGETS, ENTRY_ID
    )


@pytest.mark.asyncio
async def test_turning_off_deactivates_the_notification():
    light = _make_light()
    await light.async_turn_on()
    await light.async_turn_off()
    assert light.is_on is False
    light._coordinator.async_deactivate.assert_called_once_with(
        light._notification, TARGETS, ENTRY_ID
    )


@pytest.mark.asyncio
async def test_a_timed_notification_clears_itself():
    light = _make_light(_make_notif(duration=300))
    captured = None

    def fake_call_later(hass, delay, callback):
        nonlocal captured
        captured = (delay, callback)
        return MagicMock()

    with patch(
        "custom_components.notify_lights.light.async_call_later",
        side_effect=fake_call_later,
    ):
        await light.async_turn_on()

    assert light.is_on is True
    assert captured[0] == 300

    await captured[1]()
    assert light.is_on is False
    light._coordinator.async_deactivate.assert_called_once()


# --- restoring ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stateful_notification_comes_back_after_a_restart():
    light = _make_light()
    light.async_get_last_state = AsyncMock(return_value=_state("on"))
    await light.async_added_to_hass()
    assert light.is_on is True
    light._coordinator.async_activate.assert_called_once()


@pytest.mark.asyncio
async def test_an_inactive_notification_stays_off():
    light = _make_light()
    light.async_get_last_state = AsyncMock(return_value=_state("off"))
    await light.async_added_to_hass()
    assert light.is_on is False
    light._coordinator.async_activate.assert_not_called()


@pytest.mark.asyncio
async def test_a_timed_notification_does_not_come_back():
    """Its duration ran out while Home Assistant was down."""
    light = _make_light(_make_notif(duration=300))
    light.async_get_last_state = AsyncMock(return_value=_state("on"))
    await light.async_added_to_hass()
    assert light.is_on is False


# --- following a source entity --------------------------------------------


def _source_light(**overrides):
    notification = _make_notif(
        state_entity="binary_sensor.fridge_ajar",
        active_state="on",
        **overrides,
    )
    hass = MagicMock()
    return _make_light(notification, hass=hass)


@pytest.mark.asyncio
async def test_it_follows_its_source_entity():
    light = _source_light()
    light.hass.states.get.return_value = _state("off")
    await light.async_added_to_hass()
    assert light.is_on is False

    await light._async_apply_source_state(_state("on"))
    assert light.is_on is True
    light._coordinator.async_activate.assert_called_once()

    await light._async_apply_source_state(_state("off"))
    assert light.is_on is False
    light._coordinator.async_deactivate.assert_called_once()


@pytest.mark.asyncio
async def test_an_active_source_is_picked_up_at_setup():
    light = _source_light()
    light.hass.states.get.return_value = _state("on")
    await light.async_added_to_hass()
    assert light.is_on is True


@pytest.mark.asyncio
async def test_a_source_that_drops_out_leaves_the_display_alone():
    light = _source_light()
    light.hass.states.get.return_value = _state("on")
    await light.async_added_to_hass()

    await light._async_apply_source_state(_state("unavailable"))
    assert light.is_on is True
    light._coordinator.async_deactivate.assert_not_called()


@pytest.mark.asyncio
async def test_it_can_watch_an_attribute_instead_of_the_state():
    light = _make_light(
        _make_notif(
            state_entity="climate.bedroom",
            state_attribute="hvac_action",
            active_state="heating",
        )
    )
    light.hass.states.get.return_value = _state("heat", hvac_action="idle")
    await light.async_added_to_hass()
    assert light.is_on is False

    await light._async_apply_source_state(_state("heat", hvac_action="heating"))
    assert light.is_on is True


@pytest.mark.asyncio
async def test_an_edge_triggered_rule_does_not_replay_at_setup():
    light = _source_light(duration=300)
    light.hass.states.get.return_value = _state("on")
    await light.async_added_to_hass()
    assert light.is_on is False


@pytest.mark.asyncio
async def test_an_edge_triggered_rule_fires_on_entering_the_state():
    light = _source_light(duration=300)
    light.hass.states.get.return_value = _state("off")
    await light.async_added_to_hass()

    with patch("custom_components.notify_lights.light.async_call_later"):
        await light._async_apply_source_state(_state("on"))
    assert light.is_on is True
    light._coordinator.async_activate.assert_called_once()


# --- staying honest about the coordinator ---------------------------------


@pytest.mark.asyncio
async def test_clearing_the_catalog_turns_the_notification_light_off():
    coordinator = _make_coordinator()
    notification = _make_notif()
    light = NotificationLight(coordinator, notification, TARGETS, _make_entry())
    light.hass = MagicMock()
    light.async_get_last_state = AsyncMock(return_value=None)
    await light.async_added_to_hass()

    await light.async_turn_on()
    assert light.is_on is True

    await coordinator.async_clear_entry_notifications(ENTRY_ID)
    assert light.is_on is False


# --- platform setup -------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_adds_the_catalog_light_and_one_light_per_rule():
    hass = MagicMock()
    notifications = {
        "fridge_ajar": _make_notif(),
        "heating": _make_notif(name="heating"),
    }
    hass.data = {
        DOMAIN: {
            ENTRY_ID: {
                "coordinator": _make_coordinator(),
                "notifications": notifications,
                "targets": {slug: TARGETS for slug in notifications},
                "entry_targets": TARGETS,
            }
        }
    }

    added = []
    await async_setup_entry(
        hass, _make_entry(), lambda entities: added.extend(entities)
    )

    assert [entity.unique_id for entity in added] == [
        f"notify_lights_{ENTRY_ID}_brightness",
        f"notify_lights_{ENTRY_ID}_fridge_ajar",
        f"notify_lights_{ENTRY_ID}_heating",
    ]
