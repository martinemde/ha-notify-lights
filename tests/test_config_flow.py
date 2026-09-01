"""Tests for the Notify Lights v4 config and options flows.

A catalog is created with a name and one fixed target set (its light group),
editable afterward under "Edit targets". Every notification rule inside it
shares that target set -- there is nothing to route per rule.
"""

from unittest.mock import MagicMock

import pytest

from custom_components.notify_lights.config_flow import (
    NotifyLightsConfigFlow,
    NotifyLightsOptionsFlow,
)

TARGETS = {
    "entity_id": ["light.great_room_entry_lights", "light.great_room_ceiling_lights"]
}


def _flow(options=None):
    entry = MagicMock()
    entry.options = options or {"targets": TARGETS, "notifications": {}}
    flow = NotifyLightsOptionsFlow()
    flow.config_entry = entry
    flow.hass = MagicMock()
    flow.hass.states.get.return_value = None
    return flow


def _details(**overrides):
    data = {
        "color": "green",
        "effect": "pulse",
        "effect_speed": "medium",
        "brightness": 100,
        "priority": 60,
        "display_mode": "full",
    }
    data.update(overrides)
    return data


# --- creating a catalog ------------------------------------------------


@pytest.mark.asyncio
async def test_user_step_shows_form():
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()
    result = await flow.async_step_user(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_user_step_advances_to_targets():
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()
    result = await flow.async_step_user(user_input={"name": "Home Notifications"})
    assert result["type"] == "form"
    assert result["step_id"] == "targets"


@pytest.mark.asyncio
async def test_targets_step_creates_v4_catalog_with_its_target_set():
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()
    await flow.async_step_user(user_input={"name": "Home Notifications"})

    result = await flow.async_step_targets(
        {
            "targets": TARGETS,
            "exclude": {},
            "zigbee2mqtt_group": "notify/near_garage",
        }
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "Home Notifications"
    assert result["data"] == {"name": "Home Notifications"}
    assert result["options"] == {
        "targets": TARGETS,
        "exclude": {},
        "zigbee2mqtt_group": "notify/near_garage",
        "notifications": {},
    }


@pytest.mark.asyncio
async def test_targets_step_requires_at_least_one_target():
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()
    await flow.async_step_user(user_input={"name": "Home Notifications"})

    result = await flow.async_step_targets({"targets": {}, "exclude": {}})

    assert result["type"] == "form"
    assert result["errors"]["base"] == "target_required"


def test_options_flow_factory_uses_current_no_argument_api():
    entry = MagicMock()
    flow = NotifyLightsConfigFlow.async_get_options_flow(entry)
    assert isinstance(flow, NotifyLightsOptionsFlow)


# --- options menu --------------------------------------------------------


@pytest.mark.asyncio
async def test_options_menu_offers_targets_and_notification_rules():
    flow = _flow(
        {
            "targets": TARGETS,
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
        "edit_targets",
        "add_notification",
        "modify_notification",
        "delete_notification",
    ]


@pytest.mark.asyncio
async def test_options_menu_omits_notification_editing_when_empty():
    flow = _flow({"targets": TARGETS, "notifications": {}})
    result = await flow.async_step_init()
    assert result["menu_options"] == ["edit_targets", "add_notification"]


# --- editing a catalog's targets -----------------------------------------


@pytest.mark.asyncio
async def test_edit_targets_saves_the_new_target_set():
    flow = _flow()
    result = await flow.async_step_edit_targets(
        {
            "targets": {"entity_id": ["light.new"]},
            "exclude": {},
            "zigbee2mqtt_group": "notify/updated",
        }
    )
    assert result["type"] == "create_entry"
    assert result["data"]["targets"] == {"entity_id": ["light.new"]}
    assert result["data"]["zigbee2mqtt_group"] == "notify/updated"


@pytest.mark.asyncio
async def test_edit_targets_requires_at_least_one_target():
    flow = _flow()
    result = await flow.async_step_edit_targets({"targets": {}, "exclude": {}})
    assert result["type"] == "form"
    assert result["errors"]["base"] == "target_required"


# --- notification rules ---------------------------------------------------


@pytest.mark.asyncio
async def test_tesla_charging_rule_follows_source_state():
    flow = _flow()
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
    assert "targets" not in config
    assert "groups" not in config


@pytest.mark.asyncio
async def test_tesla_ready_rule_accepts_300_second_source_timer():
    flow = _flow()
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
    flow = _flow()
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
        _details(active_state="heating", display_mode="indicator")
    )

    config = result["data"]["notifications"]["bedrooms_heating"]
    assert config["state_entity"] == "climate.bedrooms"
    assert config["state_attribute"] == "hvac_action"
    assert config["active_state"] == "heating"
    assert config["display_mode"] == "indicator"


@pytest.mark.asyncio
async def test_manual_notification_needs_no_target_selection():
    """The point of the v4 redesign: notifications inherit the catalog's targets."""
    flow = _flow()
    await flow.async_step_add_notification(
        {
            "name": "Fridge ajar",
            "description": "Door may be cracked",
            "activation": "manual_while",
        }
    )
    result = await flow.async_step_notification_details(_details())
    assert result["type"] == "create_entry"
    assert "fridge_ajar" in result["data"]["notifications"]
