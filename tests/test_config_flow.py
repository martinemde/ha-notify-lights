"""Tests for the Notify Lights config and options flows.

A catalog is created with one native Zigbee2MQTT group or one fixed set of
physical Inovelli devices. Every notification rule shares that target set.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from custom_components.notify_lights.config_flow import (
    NotifyLightsConfigFlow,
    NotifyLightsOptionsFlow,
    _device_ids_from_options,
)

DEVICE_IDS = ["device-ceiling", "device-entry"]
TARGETS = {"device_id": DEVICE_IDS}


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
        {"targets": DEVICE_IDS}
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "Home Notifications"
    assert result["data"] == {"name": "Home Notifications"}
    assert result["options"] == {
        "targets": TARGETS,
        "exclude": {},
        "zigbee2mqtt_group": "",
        "zigbee2mqtt_groups": {},
        "notifications": {},
    }


@pytest.mark.asyncio
async def test_targets_step_requires_at_least_one_target():
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()
    await flow.async_step_user(user_input={"name": "Home Notifications"})

    result = await flow.async_step_targets({"targets": []})

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


def test_options_menu_translations_cover_every_emitted_option():
    """A missing menu translation renders as an empty row in Home Assistant."""
    strings = json.loads(
        (Path(__file__).parents[1] / "custom_components/notify_lights/strings.json")
        .read_text()
    )
    menu_options = strings["options"]["step"]["init"]["menu_options"]

    assert menu_options == {
        "edit_targets": "Edit notification lights",
        "add_notification": "Add notification rule",
        "modify_notification": "Edit notification rule",
        "delete_notification": "Delete notification rule",
    }


def test_existing_entity_targets_are_presented_as_physical_devices():
    hass = MagicMock()
    entity_registry = MagicMock()
    device_registry = MagicMock()
    entry = MagicMock()
    entry.device_id = "inovelli-device"
    entity_registry.async_get.return_value = entry
    device = MagicMock()
    device.id = "inovelli-device"
    device.manufacturer = "Inovelli"
    device.model = "2-in-1 switch + dimmer"
    device_registry.async_get.return_value = device

    with (
        patch(
            "custom_components.notify_lights.config_flow.resolve_entry_targets",
            return_value=["light.inovelli"],
        ),
        patch(
            "custom_components.notify_lights.config_flow.er.async_get",
            return_value=entity_registry,
        ),
        patch(
            "custom_components.notify_lights.config_flow.dr.async_get",
            return_value=device_registry,
        ),
    ):
        assert _device_ids_from_options(
            hass, {"targets": {"entity_id": ["light.inovelli"]}}
        ) == ["inovelli-device"]


def test_native_z2m_group_is_presented_intact_in_target_picker():
    hass = MagicMock()
    group_device = MagicMock(id="z2m-group-device")
    with patch(
        "custom_components.notify_lights.config_flow.group_devices_from_targets",
        return_value=[group_device],
    ):
        assert _device_ids_from_options(
            hass, {"targets": {"entity_id": ["light.notify_area_living_area"]}}
        ) == ["z2m-group-device"]


# --- editing a catalog's targets -----------------------------------------


@pytest.mark.asyncio
async def test_edit_targets_saves_the_new_target_set():
    flow = _flow()
    result = await flow.async_step_edit_targets({"targets": ["device-new"]})
    assert result["type"] == "create_entry"
    assert result["data"]["targets"] == {"device_id": ["device-new"]}
    assert result["data"]["exclude"] == {}
    assert result["data"]["zigbee2mqtt_group"] == ""
    assert result["data"]["zigbee2mqtt_groups"] == {}


@pytest.mark.asyncio
async def test_edit_targets_derives_exact_z2m_group_name_from_registry():
    flow = _flow()
    group_device = MagicMock(
        id="z2m-group-device",
        manufacturer="Zigbee2MQTT",
        model="Group",
        identifiers={("mqtt", "zigbee2mqtt_network_16")},
    )
    with (
        patch(
            "custom_components.notify_lights.config_flow.group_devices_from_targets",
            return_value=[group_device],
        ),
        patch(
            "custom_components.notify_lights.config_flow.async_groups_for_devices",
            return_value={
                "z2m-group-device": MagicMock(
                    friendly_name="notify/area/living_area"
                )
            },
        ) as resolve_groups,
    ):
        result = await flow.async_step_edit_targets(
            {"targets": ["z2m-group-device"]}
        )

    assert result["type"] == "create_entry"
    assert result["data"]["targets"] == {"device_id": ["z2m-group-device"]}
    assert result["data"]["zigbee2mqtt_group"] == ""
    assert result["data"]["zigbee2mqtt_groups"] == {
        "z2m-group-device": "notify/area/living_area"
    }
    resolve_groups.assert_awaited_once_with(flow.hass, [group_device])


@pytest.mark.asyncio
async def test_edit_targets_accepts_multiple_native_groups():
    flow = _flow()
    living = MagicMock(id="living-group")
    great = MagicMock(id="great-group")
    bedroom = MagicMock(id="bedroom-group")
    devices = [bedroom, great, living]
    resolved = {
        "bedroom-group": MagicMock(friendly_name="notify/area/bedroom_area"),
        "great-group": MagicMock(friendly_name="notify/area/great_area"),
        "living-group": MagicMock(friendly_name="notify/area/living_area"),
    }
    with (
        patch(
            "custom_components.notify_lights.config_flow.group_devices_from_targets",
            return_value=devices,
        ),
        patch(
            "custom_components.notify_lights.config_flow.async_groups_for_devices",
            return_value=resolved,
        ),
    ):
        result = await flow.async_step_edit_targets(
            {"targets": ["living-group", "great-group", "bedroom-group"]}
        )

    assert result["type"] == "create_entry"
    assert result["data"]["targets"] == {
        "device_id": ["bedroom-group", "great-group", "living-group"]
    }
    assert result["data"]["zigbee2mqtt_groups"] == {
        device_id: group.friendly_name for device_id, group in resolved.items()
    }


@pytest.mark.asyncio
async def test_edit_targets_rejects_mixing_native_group_and_devices():
    flow = _flow()
    group_device = MagicMock(id="z2m-group-device")
    with patch(
        "custom_components.notify_lights.config_flow.group_devices_from_targets",
        return_value=[group_device],
    ):
        result = await flow.async_step_edit_targets(
            {"targets": ["z2m-group-device", "device-new"]}
        )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "group_or_devices"


@pytest.mark.asyncio
async def test_edit_targets_requires_at_least_one_target():
    flow = _flow()
    result = await flow.async_step_edit_targets({"targets": []})
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
