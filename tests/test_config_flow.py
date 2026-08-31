"""Tests for the Notify Lights v3 options flow."""

from unittest.mock import MagicMock

import pytest

from custom_components.notify_lights.config_flow import (
    NotifyLightsConfigFlow,
    NotifyLightsOptionsFlow,
)


def _flow(options=None):
    entry = MagicMock()
    entry.options = options or {"groups": {}, "notifications": {}}
    flow = NotifyLightsOptionsFlow()
    flow.config_entry = entry
    flow.hass = MagicMock()
    flow.hass.states.get.return_value = None
    return flow


def _details(**overrides):
    data = {
        "groups": ["near_garage"],
        "targets": {},
        "exclude": {},
        "color": "green",
        "effect": "pulse",
        "effect_speed": "medium",
        "brightness": 100,
        "priority": 60,
        "display_mode": "full",
    }
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_user_step_shows_form():
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()
    result = await flow.async_step_user(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_user_step_creates_empty_v3_catalog():
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()
    result = await flow.async_step_user(user_input={"name": "Home Notifications"})
    assert result["type"] == "create_entry"
    assert result["title"] == "Home Notifications"
    assert result["data"] == {"name": "Home Notifications"}
    assert result["options"] == {"groups": {}, "notifications": {}}


def test_options_flow_factory_uses_current_no_argument_api():
    entry = MagicMock()
    flow = NotifyLightsConfigFlow.async_get_options_flow(entry)
    assert isinstance(flow, NotifyLightsOptionsFlow)


@pytest.mark.asyncio
async def test_options_menu_separates_groups_and_notification_rules():
    flow = _flow(
        {
            "groups": {
                "near_garage": {
                    "slug": "near_garage",
                    "display_name": "Near garage",
                }
            },
            "notifications": {
                "tesla_charging": {
                    "slug": "tesla_charging",
                    "display_name": "Tesla charging",
                }
            },
        }
    )
    result = await flow.async_step_init()
    assert result["type"] == "menu"
    assert result["menu_options"] == [
        "add_group",
        "modify_group",
        "delete_group",
        "add_notification",
        "modify_notification",
        "delete_notification",
    ]


@pytest.mark.asyncio
async def test_add_group_saves_reusable_targets():
    flow = _flow()
    result = await flow.async_step_add_group(
        {
            "name": "Near garage",
            "description": "Entry lights beside the garage",
            "targets": {
                "entity_id": [
                    "light.great_room_entry_lights",
                    "light.great_room_ceiling_lights",
                ]
            },
            "exclude": {},
            "zigbee2mqtt_group": "notify/near_garage",
        }
    )
    assert result["type"] == "create_entry"
    group = result["data"]["groups"]["near_garage"]
    assert group["targets"]["entity_id"] == [
        "light.great_room_entry_lights",
        "light.great_room_ceiling_lights",
    ]
    assert group["zigbee2mqtt_group"] == "notify/near_garage"


@pytest.mark.asyncio
async def test_tesla_charging_rule_follows_source_state():
    flow = _flow(
        {
            "groups": {
                "near_garage": {
                    "slug": "near_garage",
                    "display_name": "Near garage",
                }
            },
            "notifications": {},
        }
    )
    result = await flow.async_step_add_notification(
        {
            "name": "Tesla charging",
            "description": "Car is actively charging",
            "activation": "state_while",
        }
    )
    assert result["step_id"] == "notification_source"

    result = await flow.async_step_notification_source(
        {"state_entity": "sensor.tesla_wall_connector_status"}
    )
    assert result["step_id"] == "notification_property"
    result = await flow.async_step_notification_property(
        {"source_property": "__state__"}
    )
    assert result["step_id"] == "notification_details"

    result = await flow.async_step_notification_details(
        _details(active_state="charging")
    )
    config = result["data"]["notifications"]["tesla_charging"]
    assert config["activation"] == "state_while"
    assert config["state_entity"] == "sensor.tesla_wall_connector_status"
    assert config["active_state"] == "charging"
    assert config["duration"] == 0
    assert config["groups"] == ["near_garage"]


@pytest.mark.asyncio
async def test_tesla_ready_rule_accepts_300_second_source_timer():
    flow = _flow(
        {
            "groups": {
                "near_garage": {
                    "slug": "near_garage",
                    "display_name": "Near garage",
                }
            },
            "notifications": {},
        }
    )
    await flow.async_step_add_notification(
        {
            "name": "Tesla charger ready",
            "description": "Charging has completed",
            "activation": "state_entered",
        }
    )
    await flow.async_step_notification_source(
        {"state_entity": "sensor.tesla_wall_connector_status"}
    )
    await flow.async_step_notification_property({"source_property": "__state__"})
    result = await flow.async_step_notification_details(
        _details(active_state="ready", duration=300)
    )
    config = result["data"]["notifications"]["tesla_charger_ready"]
    assert config["activation"] == "state_entered"
    assert config["active_state"] == "ready"
    assert config["duration"] == 300


@pytest.mark.asyncio
async def test_hvac_rule_can_watch_attribute_as_one_pixel_indicator():
    flow = _flow(
        {
            "groups": {
                "bedrooms_hvac": {
                    "slug": "bedrooms_hvac",
                    "display_name": "Bedrooms HVAC",
                }
            },
            "notifications": {},
        }
    )
    await flow.async_step_add_notification(
        {
            "name": "Bedrooms heating",
            "description": "Bedroom zone is heating",
            "activation": "state_while",
        }
    )
    await flow.async_step_notification_source({"state_entity": "climate.bedrooms"})
    await flow.async_step_notification_property({"source_property": "hvac_action"})
    result = await flow.async_step_notification_details(
        _details(
            groups=["bedrooms_hvac"],
            active_state="heating",
            display_mode="indicator",
        )
    )

    config = result["data"]["notifications"]["bedrooms_heating"]
    assert config["state_entity"] == "climate.bedrooms"
    assert config["state_attribute"] == "hvac_action"
    assert config["active_state"] == "heating"
    assert config["display_mode"] == "indicator"


@pytest.mark.asyncio
async def test_notification_requires_a_group_or_direct_target():
    flow = _flow()
    await flow.async_step_add_notification(
        {
            "name": "Nowhere",
            "description": "Invalid rule",
            "activation": "manual_while",
        }
    )
    result = await flow.async_step_notification_details(_details(groups=[], targets={}))
    assert result["type"] == "form"
    assert result["errors"]["base"] == "target_required"
