import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from custom_components.notify_lights.button import NotificationButton
from custom_components.notify_lights.notification import Notification
from custom_components.notify_lights.const import Effect, Speed

TARGETS = ["light.lr"]
ENTRY_ID = "pool_entry_1"


def _make_entry(entry_id=ENTRY_ID, name="Test Pool"):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"name": name}
    return entry


def _make_notif(name="flash_alert", display_name="Flash Alert", duration=10):
    return Notification(
        name=name, display_name=display_name, color=0, brightness=100,
        effect=Effect.BLINK, effect_speed=Speed.FAST,
        duration=duration, priority=50,
    )


@pytest.mark.asyncio
async def test_press_activates_notification():
    coordinator = AsyncMock()
    hass = MagicMock()
    notif = _make_notif()
    entry = _make_entry()
    button = NotificationButton(coordinator, notif, TARGETS, entry, hass)

    await button.async_press()

    coordinator.async_activate.assert_called_once_with(notif, TARGETS, ENTRY_ID)


def test_entity_id_derives_from_name():
    coordinator = AsyncMock()
    hass = MagicMock()
    notif = _make_notif("door_flash", "Door Flash")
    entry = _make_entry()
    button = NotificationButton(coordinator, notif, TARGETS, entry, hass)

    assert button.unique_id == f"notify_lights_{ENTRY_ID}_door_flash"
    assert button.name == "Door Flash"


@pytest.mark.asyncio
async def test_press_schedules_deactivation():
    coordinator = AsyncMock()
    hass = MagicMock()
    cancel_callback = MagicMock()
    hass.loop = MagicMock()

    notif = _make_notif(duration=5)
    entry = _make_entry()
    button = NotificationButton(coordinator, notif, TARGETS, entry, hass)

    with patch("custom_components.notify_lights.button.async_call_later", return_value=cancel_callback) as mock_call_later:
        await button.async_press()
        mock_call_later.assert_called_once()
        assert mock_call_later.call_args[0][1] == 5


@pytest.mark.asyncio
async def test_second_press_cancels_previous_timer():
    coordinator = AsyncMock()
    hass = MagicMock()
    cancel1 = MagicMock()
    cancel2 = MagicMock()

    notif = _make_notif(duration=5)
    entry = _make_entry()
    button = NotificationButton(coordinator, notif, TARGETS, entry, hass)

    with patch("custom_components.notify_lights.button.async_call_later", side_effect=[cancel1, cancel2]):
        await button.async_press()
        await button.async_press()

        cancel1.assert_called_once()
        assert coordinator.async_activate.call_count == 2
