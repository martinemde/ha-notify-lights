import pytest
from unittest.mock import AsyncMock
from custom_components.notify_lights.switch import NotificationSwitch
from custom_components.notify_lights.notification import Notification
from custom_components.notify_lights.const import Effect, Speed


def _make_notif(name="test_alert"):
    return Notification(
        name=name, color=0, brightness=100,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=0, priority=50,
        targets=["light.lr"],
    )


@pytest.mark.asyncio
async def test_turn_on_activates_notification():
    coordinator = AsyncMock()
    notif = _make_notif()
    switch = NotificationSwitch(coordinator, notif)

    await switch.async_turn_on()

    assert switch.is_on is True
    coordinator.async_activate.assert_called_once_with(notif)


@pytest.mark.asyncio
async def test_turn_off_deactivates_notification():
    coordinator = AsyncMock()
    notif = _make_notif()
    switch = NotificationSwitch(coordinator, notif)

    await switch.async_turn_on()
    coordinator.async_activate.reset_mock()
    await switch.async_turn_off()

    assert switch.is_on is False
    coordinator.async_deactivate.assert_called_once_with(notif)


def test_entity_id_derives_from_name():
    coordinator = AsyncMock()
    notif = _make_notif("heating_alert")
    switch = NotificationSwitch(coordinator, notif)

    assert switch.unique_id == "notify_lights_heating_alert"
    assert switch.name == "Notify heating alert"


def test_initial_state_is_off():
    coordinator = AsyncMock()
    notif = _make_notif()
    switch = NotificationSwitch(coordinator, notif)

    assert switch.is_on is False
