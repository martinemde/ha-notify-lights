"""Tests for NotifyLightsCoordinator.

The coordinator tracks active notifications per target device, resolves entity
IDs to device info, matches adapters, and calls adapter.render accordingly.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.notify_lights.coordinator import NotifyLightsCoordinator
from custom_components.notify_lights.adapter import AdapterRegistry
from custom_components.notify_lights.notification import Notification
from custom_components.notify_lights.const import Effect, Speed


def _make_notif(name="test", targets=None, priority=50, color=0, effect=Effect.SOLID):
    return Notification(
        name=name,
        color=color,
        brightness=100,
        effect=effect,
        effect_speed=Speed.MEDIUM,
        duration=0,
        priority=priority,
        targets=targets or ["light.test_switch"],
    )


def _mock_hass_with_device(
    manufacturer="Inovelli", model="VZM31-SN", device_name="office_dimmer"
):
    """Create mock hass with entity/device registry entries for a target."""
    hass = MagicMock()

    entity_entry = MagicMock()
    entity_entry.device_id = "device_123"

    entity_registry = MagicMock()
    entity_registry.async_get.return_value = entity_entry

    device_entry = MagicMock()
    device_entry.manufacturer = manufacturer
    device_entry.model = model
    device_entry.name = device_name

    device_registry = MagicMock()
    device_registry.async_get.return_value = device_entry

    return hass, entity_registry, device_registry


def _make_adapter(manufacturer="Inovelli", model_patterns=None):
    mock_adapter = AsyncMock()
    mock_adapter.manufacturer = manufacturer
    mock_adapter.model_patterns = model_patterns or ["VZM31*"]
    return mock_adapter


@pytest.mark.asyncio
async def test_activate_calls_adapter_render():
    """activate should call adapter.render with friendly name and active set."""
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif()

    await coordinator.async_activate(notif)

    mock_adapter.render.assert_called_once()
    call_args = mock_adapter.render.call_args
    assert call_args[0][0] == "office_dimmer"  # friendly name from device
    assert len(call_args[0][1]) == 1  # one active notification


@pytest.mark.asyncio
async def test_activate_passes_notification_in_active_set():
    """activate should include the notification in the active set passed to render."""
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif(name="my_notif")

    await coordinator.async_activate(notif)

    active_set = mock_adapter.render.call_args[0][1]
    assert active_set[0][0].name == "my_notif"


@pytest.mark.asyncio
async def test_deactivate_clears_when_empty():
    """deactivate with empty resulting set should call render with empty active set."""
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif()

    await coordinator.async_activate(notif)
    mock_adapter.render.reset_mock()
    await coordinator.async_deactivate(notif)

    mock_adapter.render.assert_called_once()
    assert len(mock_adapter.render.call_args[0][1]) == 0  # empty active set


@pytest.mark.asyncio
async def test_deactivate_only_removes_matching_notification():
    """deactivate should only remove the named notification, not others."""
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif_a = _make_notif(name="alpha")
    notif_b = _make_notif(name="beta")

    await coordinator.async_activate(notif_a)
    await coordinator.async_activate(notif_b)
    mock_adapter.render.reset_mock()

    await coordinator.async_deactivate(notif_a)

    active_set = mock_adapter.render.call_args[0][1]
    names = [entry[0].name for entry in active_set]
    assert "alpha" not in names
    assert "beta" in names


@pytest.mark.asyncio
async def test_unmatched_device_logs_and_skips():
    """Targets with no matching adapter should log a warning without raising."""
    hass, entity_reg, device_reg = _mock_hass_with_device(
        manufacturer="Unknown", model="XYZ"
    )
    registry = AdapterRegistry()

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif()

    # Should not raise, just log
    await coordinator.async_activate(notif)


@pytest.mark.asyncio
async def test_missing_entity_entry_logs_and_skips():
    """Targets with no entity registry entry should be skipped gracefully."""
    hass = MagicMock()
    entity_registry = MagicMock()
    entity_registry.async_get.return_value = None
    device_registry = MagicMock()

    registry = AdapterRegistry()
    coordinator = NotifyLightsCoordinator(hass, registry, entity_registry, device_registry)
    notif = _make_notif()

    await coordinator.async_activate(notif)
    # No adapter render calls expected
    device_registry.async_get.assert_not_called()


@pytest.mark.asyncio
async def test_missing_device_entry_skips():
    """Targets where device lookup returns None should be skipped gracefully."""
    hass = MagicMock()

    entity_entry = MagicMock()
    entity_entry.device_id = "device_123"
    entity_registry = MagicMock()
    entity_registry.async_get.return_value = entity_entry

    device_registry = MagicMock()
    device_registry.async_get.return_value = None

    registry = AdapterRegistry()
    coordinator = NotifyLightsCoordinator(hass, registry, entity_registry, device_registry)
    notif = _make_notif()

    await coordinator.async_activate(notif)
    # Should not raise


@pytest.mark.asyncio
async def test_multiple_notifications_ordered():
    """Higher priority notifications should appear first in the active set."""
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    low = Notification(
        name="low",
        color=0,
        brightness=100,
        effect=Effect.SOLID,
        effect_speed=Speed.MEDIUM,
        duration=0,
        priority=10,
        targets=["light.test_switch"],
    )
    high = Notification(
        name="high",
        color=120,
        brightness=100,
        effect=Effect.PULSE,
        effect_speed=Speed.FAST,
        duration=0,
        priority=90,
        targets=["light.test_switch"],
    )

    await coordinator.async_activate(low)
    await coordinator.async_activate(high)

    # Last render should have both, high priority first
    active = mock_adapter.render.call_args[0][1]
    assert active[0][0].name == "high"
    assert active[1][0].name == "low"


@pytest.mark.asyncio
async def test_adapter_render_exception_is_caught():
    """An exception raised by adapter.render should be caught and logged."""
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    mock_adapter.render.side_effect = RuntimeError("adapter exploded")
    registry.register(mock_adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif()

    # Should not raise
    await coordinator.async_activate(notif)


@pytest.mark.asyncio
async def test_warning_logged_only_once_per_target():
    """Repeated calls for an unmatched target should only warn once."""
    hass, entity_reg, device_reg = _mock_hass_with_device(
        manufacturer="Unknown", model="XYZ"
    )
    registry = AdapterRegistry()
    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif()

    warning_calls = []

    import logging
    import custom_components.notify_lights.coordinator as coord_module
    original_warning = coord_module._LOGGER.warning

    def capture_warning(msg, *args, **kwargs):
        warning_calls.append(msg % args if args else msg)
        return original_warning(msg, *args, **kwargs)

    coord_module._LOGGER.warning = capture_warning
    try:
        await coordinator.async_activate(notif)
        await coordinator.async_activate(notif)
    finally:
        coord_module._LOGGER.warning = original_warning

    # Warning should only be emitted once despite two activations
    no_adapter_warnings = [w for w in warning_calls if "No adapter" in w]
    assert len(no_adapter_warnings) == 1
