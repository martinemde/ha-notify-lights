"""Tests for the Notify Lights config flow (pool-based)."""
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
    targets = {"entity_id": ["light.living_room", "light.kitchen"]}
    result = await flow.async_step_user(
        user_input={"name": "Floor 1 Switches", "targets": targets}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Floor 1 Switches"
    assert result["data"]["name"] == "Floor 1 Switches"
    assert result["data"]["targets"] == targets
    assert result["options"] == {"notifications": {}}


@pytest.mark.asyncio
async def test_user_step_default_name():
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()
    targets = {"entity_id": ["switch.hallway"]}
    result = await flow.async_step_user(
        user_input={"name": "Home Notify Lights", "targets": targets}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Home Notify Lights"


@pytest.mark.asyncio
async def test_options_init_shows_menu():
    entry = MagicMock()
    entry.data = {
        "name": "Test Pool",
        "targets": {"entity_id": ["light.x"]},
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
    assert "targets" in result["menu_options"]


@pytest.mark.asyncio
async def test_options_init_redirects_to_add_when_empty():
    entry = MagicMock()
    entry.data = {
        "name": "Test Pool",
        "targets": {"entity_id": ["light.x"]},
    }
    entry.options = {"notifications": {}}
    flow = NotifyLightsOptionsFlow(entry)
    flow.hass = MagicMock()
    result = await flow.async_step_init(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "add"
