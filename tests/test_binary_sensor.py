"""Tests for notifications bound directly to source entity state."""
import pytest
from unittest.mock import AsyncMock, MagicMock

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


def _entry():
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    return entry


def _state(value):
    state = MagicMock()
    state.state = value
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
