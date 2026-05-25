"""Tests for the Notify Lights config flow."""
import pytest
from unittest.mock import MagicMock
from custom_components.notify_lights.config_flow import NotifyLightsConfigFlow
from custom_components.notify_lights.const import DOMAIN


@pytest.mark.asyncio
async def test_user_step_creates_entry():
    """Test that the user step creates a config entry."""
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()

    result = await flow.async_step_user(user_input={})

    assert result["type"] == "create_entry"
    assert result["title"] == "Notify Lights"
    assert result["data"] == {}


@pytest.mark.asyncio
async def test_user_step_shows_form_first():
    """Test that user step shows confirmation form when no input."""
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()

    result = await flow.async_step_user(user_input=None)

    assert result["type"] == "form"
    assert result["step_id"] == "user"
