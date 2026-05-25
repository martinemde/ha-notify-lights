"""Tests for the Notify Lights config flow (pool-based)."""
import pytest
from unittest.mock import MagicMock
from custom_components.notify_lights.config_flow import (
    NotifyLightsConfigFlow,
    NotifyLightsOptionsFlow,
)
from custom_components.notify_lights.const import DOMAIN


@pytest.mark.asyncio
async def test_user_step_shows_name_form():
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()
    result = await flow.async_step_user(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_user_step_advances_to_targets():
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()
    result = await flow.async_step_user(
        user_input={"name": "Floor 1 Switches", "area_id": "living_room"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "targets"


@pytest.mark.asyncio
async def test_targets_step_creates_entry():
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()
    await flow.async_step_user(
        user_input={"name": "Floor 1 Switches", "area_id": ""}
    )
    result = await flow.async_step_targets(
        user_input={"targets": ["light.living_room", "light.kitchen"]}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Floor 1 Switches"
    assert result["data"]["name"] == "Floor 1 Switches"
    assert result["data"]["targets"] == ["light.living_room", "light.kitchen"]
    assert result["options"] == {"notifications": {}}


@pytest.mark.asyncio
async def test_options_init_shows_menu():
    entry = MagicMock()
    entry.data = {"name": "Test Pool", "area_id": "", "targets": ["light.x"]}
    entry.options = {"notifications": {"heating": {"slug": "heating", "display_name": "Heating"}}}
    flow = NotifyLightsOptionsFlow(entry)
    flow.hass = MagicMock()
    result = await flow.async_step_init(user_input=None)
    assert result["type"] == "menu"
    assert "add" in result["menu_options"]
    assert "modify" in result["menu_options"]
    assert "delete" in result["menu_options"]
    assert "basics" in result["menu_options"]


@pytest.mark.asyncio
async def test_options_init_redirects_to_add_when_empty():
    entry = MagicMock()
    entry.data = {"name": "Test Pool", "area_id": "", "targets": ["light.x"]}
    entry.options = {"notifications": {}}
    flow = NotifyLightsOptionsFlow(entry)
    flow.hass = MagicMock()
    result = await flow.async_step_init(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "add"
