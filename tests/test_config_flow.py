"""Tests for the Notify Lights config flow (catalog-based)."""
import pytest
from unittest.mock import MagicMock
from custom_components.notify_lights.config_flow import (
    NotifyLightsConfigFlow,
    NotifyLightsOptionsFlow,
)
from custom_components.notify_lights.const import DOMAIN


@pytest.mark.asyncio
async def test_user_step_shows_form():
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()
    result = await flow.async_step_user(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_user_step_creates_entry():
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()
    result = await flow.async_step_user(user_input={"name": "Floor 1 Switches"})
    assert result["type"] == "create_entry"
    assert result["title"] == "Floor 1 Switches"
    assert result["data"]["name"] == "Floor 1 Switches"
    # Targets belong to notifications now, not to the catalog.
    assert "targets" not in result["data"]
    assert result["options"] == {"notifications": {}}


@pytest.mark.asyncio
async def test_user_step_default_name():
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()
    result = await flow.async_step_user(user_input={"name": "Home Notify Lights"})
    assert result["type"] == "create_entry"
    assert result["title"] == "Home Notify Lights"


@pytest.mark.asyncio
async def test_options_init_shows_menu():
    entry = MagicMock()
    entry.data = {
        "name": "Test Catalog",
    }
    entry.options = {
        "notifications": {
            "heating": {"slug": "heating", "display_name": "Heating"}
        }
    }
    flow = NotifyLightsOptionsFlow(entry)
    flow.hass = MagicMock()
    result = await flow.async_step_init(user_input=None)
    assert result["type"] == "menu"
    assert "add" in result["menu_options"]
    assert "modify" in result["menu_options"]
    assert "delete" in result["menu_options"]
    assert "targets" not in result["menu_options"]


@pytest.mark.asyncio
async def test_options_init_redirects_to_add_when_empty():
    entry = MagicMock()
    entry.data = {
        "name": "Test Catalog",
    }
    entry.options = {"notifications": {}}
    flow = NotifyLightsOptionsFlow(entry)
    flow.hass = MagicMock()
    result = await flow.async_step_init(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "add"


@pytest.mark.asyncio
async def test_state_source_rejects_nonzero_duration():
    entry = MagicMock()
    entry.options = {"notifications": {}}
    flow = NotifyLightsOptionsFlow(entry)
    flow.hass = MagicMock()
    result = await flow.async_step_add({
        "name": "Front door unlocked",
        "description": "",
        "targets": {"entity_id": ["light.entry"]},
        "exclude": {},
        "color": "red",
        "effect": "pulse",
        "effect_speed": "medium",
        "brightness": 100,
        "duration": 5,
        "priority": 90,
        "state_entity": "lock.front_door_lock",
        "active_state": "unlocked",
    })
    assert result["type"] == "form"
    assert result["errors"]["duration"] == "state_source_requires_zero_duration"
