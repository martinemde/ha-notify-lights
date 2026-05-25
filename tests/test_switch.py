import pytest
from unittest.mock import AsyncMock, MagicMock
from custom_components.notify_lights.switch import NotificationSwitch
from custom_components.notify_lights.notification import Notification
from custom_components.notify_lights.const import Effect, Speed

TARGETS = ["light.lr"]
ENTRY_ID = "pool_entry_1"


def _make_entry(entry_id=ENTRY_ID, name="Test Pool"):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"name": name}
    return entry


def _make_notif(name="test_alert", display_name="Test Alert"):
    return Notification(
        name=name, display_name=display_name, color=0, brightness=100,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=0, priority=50,
    )


@pytest.mark.asyncio
async def test_turn_on_activates_notification():
    coordinator = AsyncMock()
    notif = _make_notif()
    entry = _make_entry()
    switch = NotificationSwitch(coordinator, notif, TARGETS, entry)
    await switch.async_turn_on()
    assert switch.is_on is True
    coordinator.async_activate.assert_called_once_with(notif, TARGETS, ENTRY_ID)


@pytest.mark.asyncio
async def test_turn_off_deactivates_notification():
    coordinator = AsyncMock()
    notif = _make_notif()
    entry = _make_entry()
    switch = NotificationSwitch(coordinator, notif, TARGETS, entry)
    await switch.async_turn_on()
    coordinator.async_activate.reset_mock()
    await switch.async_turn_off()
    assert switch.is_on is False
    coordinator.async_deactivate.assert_called_once_with(notif, TARGETS, ENTRY_ID)


def test_unique_id_includes_entry_id():
    coordinator = AsyncMock()
    notif = _make_notif("heating_alert", "Heating Alert")
    entry = _make_entry()
    switch = NotificationSwitch(coordinator, notif, TARGETS, entry)
    assert switch.unique_id == f"notify_lights_{ENTRY_ID}_heating_alert"


def test_display_name():
    coordinator = AsyncMock()
    notif = _make_notif("heating_alert", "Heating Alert")
    entry = _make_entry()
    switch = NotificationSwitch(coordinator, notif, TARGETS, entry)
    assert switch.name == "Heating Alert"


def test_initial_state_is_off():
    coordinator = AsyncMock()
    notif = _make_notif()
    entry = _make_entry()
    switch = NotificationSwitch(coordinator, notif, TARGETS, entry)
    assert switch.is_on is False
