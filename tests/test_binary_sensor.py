"""Tests for notifications bound directly to source entity state."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.notify_lights.binary_sensor import (
    StateNotificationBinarySensor,
)
from custom_components.notify_lights.const import Effect, Speed
from custom_components.notify_lights.notification import Notification

TARGETS = ["light.entry"]
ENTRY_ID = "catalog_1"


def _notification():
    return Notification(
        name="front_door_unlocked",
        display_name="Front door unlocked",
        color=0,
        brightness=100,
        effect=Effect.PULSE,
        effect_speed=Speed.MEDIUM,
        duration=0,
        priority=90,
        state_entity="lock.front_door_lock",
        active_state="unlocked",
    )


def _timed_notification():
    return Notification(
        name="tesla_charger_ready",
        display_name="Tesla charger ready",
        color=120,
        brightness=100,
        effect=Effect.PULSE,
        effect_speed=Speed.MEDIUM,
        duration=300,
        priority=60,
        state_entity="sensor.tesla_wall_connector_status",
        active_state="ready",
    )


def _entry():
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    return entry


def _state(value):
    state = MagicMock()
    state.state = value
    state.attributes = {}
    return state


@pytest.mark.asyncio
async def test_active_source_activates_notification():
    coordinator = AsyncMock()
    entity = StateNotificationBinarySensor(
        coordinator, _notification(), TARGETS, _entry()
    )
    await entity._async_apply_source_state(_state("unlocked"))
    assert entity.is_on is True
    assert entity.available is True
    coordinator.async_activate.assert_called_once()


@pytest.mark.asyncio
async def test_inactive_source_deactivates_notification():
    coordinator = AsyncMock()
    entity = StateNotificationBinarySensor(
        coordinator, _notification(), TARGETS, _entry()
    )
    await entity._async_apply_source_state(_state("locked"))
    assert entity.is_on is False
    coordinator.async_deactivate.assert_called_once()


@pytest.mark.asyncio
async def test_repeated_same_state_is_idempotent():
    coordinator = AsyncMock()
    entity = StateNotificationBinarySensor(
        coordinator, _notification(), TARGETS, _entry()
    )
    await entity._async_apply_source_state(_state("unlocked"))
    await entity._async_apply_source_state(_state("unlocked"))
    coordinator.async_activate.assert_called_once()


@pytest.mark.asyncio
async def test_unavailable_source_preserves_last_active_state():
    coordinator = AsyncMock()
    entity = StateNotificationBinarySensor(
        coordinator, _notification(), TARGETS, _entry()
    )
    await entity._async_apply_source_state(_state("unlocked"))
    coordinator.reset_mock()
    await entity._async_apply_source_state(_state("unavailable"))
    assert entity.is_on is True
    assert entity.available is False
    coordinator.async_deactivate.assert_not_called()


def test_attributes_expose_source_binding():
    entity = StateNotificationBinarySensor(
        AsyncMock(), _notification(), TARGETS, _entry()
    )
    assert entity.extra_state_attributes["state_entity"] == "lock.front_door_lock"
    assert entity.extra_state_attributes["active_state"] == "unlocked"
    assert entity.extra_state_attributes["activation"] == "state_while"


@pytest.mark.asyncio
async def test_timed_source_activates_only_when_state_is_entered():
    coordinator = AsyncMock()
    entity = StateNotificationBinarySensor(
        coordinator, _timed_notification(), TARGETS, _entry()
    )
    entity.hass = MagicMock()

    # Ready at setup is synchronization, not an event to replay.
    await entity._async_apply_source_state(_state("ready"), initial=True)
    coordinator.async_activate.assert_not_called()

    await entity._async_apply_source_state(_state("charging"))
    with patch(
        "custom_components.notify_lights.binary_sensor.async_call_later",
        return_value=MagicMock(),
    ) as call_later:
        await entity._async_apply_source_state(_state("ready"))

    coordinator.async_activate.assert_called_once()
    assert entity.is_on is True
    assert call_later.call_args.args[1] == 300


@pytest.mark.asyncio
async def test_timed_source_deactivates_when_timer_finishes():
    coordinator = AsyncMock()
    entity = StateNotificationBinarySensor(
        coordinator, _timed_notification(), TARGETS, _entry()
    )
    entity.hass = MagicMock()
    await entity._async_apply_source_state(_state("charging"), initial=True)

    with patch(
        "custom_components.notify_lights.binary_sensor.async_call_later",
        return_value=MagicMock(),
    ):
        await entity._async_apply_source_state(_state("ready"))
        await entity._async_timer_finished()

    assert entity.is_on is False
    coordinator.async_deactivate.assert_called_once()


@pytest.mark.asyncio
async def test_timed_source_does_not_replay_when_first_available_state_is_ready():
    coordinator = AsyncMock()
    entity = StateNotificationBinarySensor(
        coordinator, _timed_notification(), TARGETS, _entry()
    )
    entity.hass = MagicMock()

    await entity._async_apply_source_state(_state("unavailable"), initial=True)
    await entity._async_apply_source_state(_state("ready"))

    assert entity.is_on is False
    assert entity.available is True
    coordinator.async_activate.assert_not_called()


@pytest.mark.asyncio
async def test_source_attribute_can_drive_hvac_notification():
    notification = Notification(
        name="bedrooms_heating",
        display_name="Bedrooms heating",
        color=0,
        brightness=50,
        effect=Effect.SOLID,
        effect_speed=Speed.MEDIUM,
        duration=0,
        priority=20,
        state_entity="climate.bedrooms",
        state_attribute="hvac_action",
        active_state="heating",
    )
    coordinator = AsyncMock()
    entity = StateNotificationBinarySensor(coordinator, notification, TARGETS, _entry())
    source = _state("heat")
    source.attributes = {"hvac_action": "heating"}

    await entity._async_apply_source_state(source)

    assert entity.is_on is True
    assert entity.extra_state_attributes["state_attribute"] == "hvac_action"
    coordinator.async_activate.assert_called_once()
