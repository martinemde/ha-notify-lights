"""Tests for NotifyLightsCoordinator."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.notify_lights.coordinator import NotifyLightsCoordinator
from custom_components.notify_lights.adapter import AdapterRegistry
from custom_components.notify_lights.notification import Notification
from custom_components.notify_lights.const import Effect, Speed


def _make_notif(name="test", priority=50, color=0, effect=Effect.SOLID):
    return Notification(
        name=name,
        color=color,
        brightness=100,
        effect=effect,
        effect_speed=Speed.MEDIUM,
        duration=0,
        priority=priority,
    )


TARGETS = ["light.test_switch"]
POOL_ID = "pool_entry_1"


def _mock_hass_with_device(
    manufacturer="Inovelli", model="VZM31-SN", device_name="office_dimmer"
):
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
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)
    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif()
    await coordinator.async_activate(notif, TARGETS, POOL_ID)
    mock_adapter.render.assert_called_once()
    call_args = mock_adapter.render.call_args
    assert call_args[0][0] == "office_dimmer"
    assert len(call_args[0][1]) == 1


@pytest.mark.asyncio
async def test_activate_passes_notification_in_active_set():
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)
    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif(name="my_notif")
    await coordinator.async_activate(notif, TARGETS, POOL_ID)
    active_set = mock_adapter.render.call_args[0][1]
    assert active_set[0][0].name == "my_notif"


@pytest.mark.asyncio
async def test_deactivate_clears_when_empty():
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)
    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif()
    await coordinator.async_activate(notif, TARGETS, POOL_ID)
    mock_adapter.render.reset_mock()
    await coordinator.async_deactivate(notif, TARGETS, POOL_ID)
    mock_adapter.render.assert_called_once()
    assert len(mock_adapter.render.call_args[0][1]) == 0


@pytest.mark.asyncio
async def test_deactivate_only_removes_matching_notification():
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)
    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif_a = _make_notif(name="alpha")
    notif_b = _make_notif(name="beta")
    await coordinator.async_activate(notif_a, TARGETS, POOL_ID)
    await coordinator.async_activate(notif_b, TARGETS, POOL_ID)
    mock_adapter.render.reset_mock()
    await coordinator.async_deactivate(notif_a, TARGETS, POOL_ID)
    active_set = mock_adapter.render.call_args[0][1]
    names = [entry[0].name for entry in active_set]
    assert "alpha" not in names
    assert "beta" in names


@pytest.mark.asyncio
async def test_cross_pool_priority_resolution():
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)
    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    low = _make_notif(name="low", priority=10)
    high = _make_notif(name="high", priority=90)
    await coordinator.async_activate(low, TARGETS, "pool_a")
    await coordinator.async_activate(high, TARGETS, "pool_b")
    active_set = mock_adapter.render.call_args[0][1]
    assert active_set[0][0].name == "high"
    assert active_set[1][0].name == "low"


@pytest.mark.asyncio
async def test_deactivate_scoped_to_pool():
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)
    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif(name="heating")
    await coordinator.async_activate(notif, TARGETS, "pool_a")
    await coordinator.async_activate(notif, TARGETS, "pool_b")
    mock_adapter.render.reset_mock()
    await coordinator.async_deactivate(notif, TARGETS, "pool_a")
    active_set = mock_adapter.render.call_args[0][1]
    assert len(active_set) == 1


@pytest.mark.asyncio
async def test_unmatched_device_logs_and_skips():
    hass, entity_reg, device_reg = _mock_hass_with_device(manufacturer="Unknown", model="XYZ")
    registry = AdapterRegistry()
    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif()
    await coordinator.async_activate(notif, TARGETS, POOL_ID)


@pytest.mark.asyncio
async def test_missing_entity_entry_logs_and_skips():
    hass = MagicMock()
    entity_registry = MagicMock()
    entity_registry.async_get.return_value = None
    device_registry = MagicMock()
    registry = AdapterRegistry()
    coordinator = NotifyLightsCoordinator(hass, registry, entity_registry, device_registry)
    notif = _make_notif()
    await coordinator.async_activate(notif, TARGETS, POOL_ID)
    device_registry.async_get.assert_not_called()


@pytest.mark.asyncio
async def test_missing_device_entry_skips():
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
    await coordinator.async_activate(notif, TARGETS, POOL_ID)


@pytest.mark.asyncio
async def test_adapter_render_exception_is_caught():
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    mock_adapter.render.side_effect = RuntimeError("adapter exploded")
    registry.register(mock_adapter)
    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif()
    await coordinator.async_activate(notif, TARGETS, POOL_ID)
