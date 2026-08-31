"""Tests for reusable targets, exclusions, and config-entry migrations."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.notify_lights import (
    _pending_native_group_entities,
    async_migrate_entry,
    notifications_from_options,
    resolve_notification_targets,
    targets_from_options,
)
from custom_components.notify_lights.config_flow import notification_config


def _hass():
    hass = MagicMock()
    hass.states.get.return_value = None
    return hass


def _form(name="Fridge Ajar", **overrides):
    """A submitted add/modify form."""
    data = {
        "name": name,
        "description": "A fridge has not cycled off; door may be cracked.",
        "targets": {"entity_id": ["light.kitchen", "light.pantry"]},
        "exclude": {},
        "color": "red",
        "effect": "pulse",
        "effect_speed": "medium",
        "brightness": 100,
        "duration": 0,
        "priority": 75,
        "activation": "manual_while",
        "display_mode": "full",
    }
    data.update(overrides)
    return data


# --- notification_config ---------------------------------------------------


def test_notification_config_stores_targets_and_description():
    cfg = notification_config("fridge_ajar", _form())
    assert cfg["slug"] == "fridge_ajar"
    assert cfg["targets"] == {"entity_id": ["light.kitchen", "light.pantry"]}
    assert cfg["exclude"] == {}
    assert cfg["description"].startswith("A fridge has not cycled off")


def test_notification_config_stores_optional_state_binding():
    cfg = notification_config(
        "front_door_unlocked",
        _form(
            name="Front door unlocked",
            state_entity="lock.front_door_lock",
            active_state="unlocked",
            activation="state_while",
        ),
    )
    assert cfg["state_entity"] == "lock.front_door_lock"
    assert cfg["active_state"] == "unlocked"


def test_notification_config_defaults_optional_fields():
    form = _form()
    del form["description"]
    del form["exclude"]
    cfg = notification_config("fridge_ajar", form)
    assert cfg["description"] == ""
    assert cfg["exclude"] == {}
    assert cfg["state_entity"] is None
    assert cfg["active_state"] == "on"
    assert cfg["state_attribute"] is None
    assert cfg["display_mode"] == "full"


# --- target resolution -----------------------------------------------------


def test_resolve_targets_without_exclusion():
    cfg = {"targets": {"entity_id": ["light.a", "light.b"]}}
    assert resolve_notification_targets(_hass(), cfg) == ["light.a", "light.b"]


def test_resolve_targets_subtracts_exclusion():
    """'The whole house except the kids' rooms' is the motivating case."""
    cfg = {
        "targets": {"entity_id": ["light.a", "light.b", "light.kid"]},
        "exclude": {"entity_id": ["light.kid"]},
    }
    assert resolve_notification_targets(_hass(), cfg) == ["light.a", "light.b"]


def test_exclusion_of_untargeted_entity_is_harmless():
    cfg = {
        "targets": {"entity_id": ["light.a"]},
        "exclude": {"entity_id": ["light.not_targeted"]},
    }
    assert resolve_notification_targets(_hass(), cfg) == ["light.a"]


def test_excluding_everything_yields_no_targets():
    cfg = {
        "targets": {"entity_id": ["light.a"]},
        "exclude": {"entity_id": ["light.a"]},
    }
    assert resolve_notification_targets(_hass(), cfg) == []


def test_missing_targets_yields_no_targets():
    assert resolve_notification_targets(_hass(), {}) == []


def test_notification_uses_reusable_group_targets_and_exclusions():
    groups = {
        "common_alerts": {
            "targets": {"entity_id": ["light.entry", "light.kitchen", "light.kid"]},
            "exclude": {"entity_id": ["light.kid"]},
        }
    }
    config = {
        "slug": "doors_unlocked",
        "groups": ["common_alerts"],
        "targets": {"entity_id": ["light.garage"]},
        "exclude": {"entity_id": ["light.kitchen"]},
    }
    assert resolve_notification_targets(_hass(), config, groups) == [
        "light.entry",
        "light.garage",
    ]


def test_area_target_includes_entities_inheriting_device_area():
    """Most HA entities inherit area from their device, not their own row."""
    hass = _hass()
    ent_reg = MagicMock()
    dev_reg = MagicMock()

    device = MagicMock()
    device.id = "inovelli_kitchen"
    light = MagicMock()
    light.domain = "light"
    light.entity_id = "light.kitchen_dimmer"
    light.disabled_by = None
    light.entity_category = None

    with (
        patch("custom_components.notify_lights.er.async_get", return_value=ent_reg),
        patch("custom_components.notify_lights.dr.async_get", return_value=dev_reg),
        patch(
            "custom_components.notify_lights.er.async_entries_for_area",
            return_value=[],
        ),
        patch(
            "custom_components.notify_lights.dr.async_entries_for_area",
            return_value=[device],
        ),
        patch(
            "custom_components.notify_lights.er.async_entries_for_device",
            return_value=[light],
        ),
    ):
        assert resolve_notification_targets(
            hass, {"targets": {"area_id": ["kitchen"]}}
        ) == ["light.kitchen_dimmer"]


def test_area_target_skips_disabled_and_config_entities():
    hass = _hass()
    ent_reg = MagicMock()
    dev_reg = MagicMock()
    device = MagicMock()
    device.id = "device_1"

    main = MagicMock()
    main.domain = "light"
    main.entity_id = "light.main"
    main.disabled_by = None
    main.entity_category = None
    disabled = MagicMock()
    disabled.domain = "switch"
    disabled.entity_id = "switch.disabled"
    disabled.disabled_by = "user"
    disabled.entity_category = None
    config = MagicMock()
    config.domain = "switch"
    config.entity_id = "switch.config"
    config.disabled_by = None
    config.entity_category = "config"

    with (
        patch("custom_components.notify_lights.er.async_get", return_value=ent_reg),
        patch("custom_components.notify_lights.dr.async_get", return_value=dev_reg),
        patch(
            "custom_components.notify_lights.er.async_entries_for_area",
            return_value=[],
        ),
        patch(
            "custom_components.notify_lights.dr.async_entries_for_area",
            return_value=[device],
        ),
        patch(
            "custom_components.notify_lights.er.async_entries_for_device",
            return_value=[main, disabled, config],
        ),
    ):
        assert resolve_notification_targets(
            hass, {"targets": {"area_id": ["kitchen"]}}
        ) == ["light.main"]


def test_targets_from_options_keys_by_slug():
    options = {
        "notifications": {
            "one": {
                "targets": {"entity_id": ["light.a", "light.b"]},
                "exclude": {"entity_id": ["light.b"]},
            },
            "two": {"targets": {"entity_id": ["light.c"]}},
        }
    }
    assert targets_from_options(_hass(), options) == {
        "one": ["light.a"],
        "two": ["light.c"],
    }


def test_notifications_can_target_different_lights():
    """The point of the refactor: one catalog, per-notification targets."""
    options = {
        "notifications": {
            "hvac_cooling_bedrooms": {"targets": {"entity_id": ["light.bed"]}},
            "hvac_cooling_living_area": {"targets": {"entity_id": ["light.liv"]}},
        }
    }
    resolved = targets_from_options(_hass(), options)
    assert resolved["hvac_cooling_bedrooms"] != resolved["hvac_cooling_living_area"]


def test_overlapping_groups_normalize_to_shared_physical_entity(monkeypatch):
    """Different selectors must converge on one coordinator stack key."""
    hass = _hass()

    def state(entity_id):
        members = {
            "light.bedrooms": ["light.shared", "light.bed"],
            "light.downstairs": ["light.shared", "light.kitchen"],
        }.get(entity_id)
        if members is None:
            return None
        result = MagicMock()
        result.attributes = {"entity_id": members}
        return result

    hass.states.get.side_effect = state
    options = {
        "notifications": {
            "bedrooms": {"targets": {"entity_id": ["light.bedrooms"]}},
            "downstairs": {"targets": {"entity_id": ["light.downstairs"]}},
        }
    }

    resolved = targets_from_options(hass, options)
    assert "light.shared" in resolved["bedrooms"]
    assert "light.shared" in resolved["downstairs"]
    assert "light.bedrooms" not in resolved["bedrooms"]
    assert "light.downstairs" not in resolved["downstairs"]


def test_group_target_can_exclude_concrete_member():
    hass = _hass()
    group = MagicMock()
    group.attributes = {"entity_id": ["light.keep", "light.exclude"]}
    hass.states.get.side_effect = lambda entity_id: (
        group if entity_id == "light.all" else None
    )
    cfg = {
        "targets": {"entity_id": ["light.all"]},
        "exclude": {"entity_id": ["light.exclude"]},
    }
    assert resolve_notification_targets(hass, cfg) == ["light.keep"]


def test_zigbee2mqtt_group_entities_are_expanded():
    hass = _hass()
    group = MagicMock()
    group.attributes = {
        "group_entities": ["light.entry", "light.ceiling", "switch.dimmer"]
    }
    hass.states.get.side_effect = lambda entity_id: (
        group if entity_id == "light.notify_area" else None
    )

    assert resolve_notification_targets(
        hass, {"targets": {"entity_id": ["light.notify_area"]}}
    ) == ["light.ceiling", "light.entry", "switch.dimmer"]


def test_unavailable_single_entity_native_group_is_pending():
    options = {
        "groups": {
            "bedroom_area": {
                "targets": {"entity_id": ["light.notify_area_bedrooms"]},
                "zigbee2mqtt_group": "notify/area/bedroom_area",
            }
        }
    }
    assert _pending_native_group_entities(_hass(), options) == {
        "light.notify_area_bedrooms"
    }


def test_ready_single_entity_native_group_is_not_pending():
    hass = _hass()
    group = MagicMock()
    group.attributes = {"group_entities": ["light.entry", "light.ceiling"]}
    hass.states.get.return_value = group
    options = {
        "groups": {
            "living_area": {
                "targets": {"entity_id": ["light.notify_area_living_area"]},
                "zigbee2mqtt_group": "notify/area/living_area",
            }
        }
    }
    assert _pending_native_group_entities(hass, options) == set()


def test_explicit_multi_entity_native_group_does_not_wait_for_group_attributes():
    options = {
        "groups": {
            "security": {
                "targets": {"entity_id": ["light.entry", "light.ceiling"]},
                "zigbee2mqtt_group": "notify/security",
            }
        }
    }
    assert _pending_native_group_entities(_hass(), options) == set()


def test_nested_groups_are_expanded_and_deduplicated():
    hass = _hass()

    def state(entity_id):
        members = {
            "light.house": ["light.floor", "light.shared"],
            "light.floor": ["light.shared", "switch.dimmer"],
        }.get(entity_id)
        if members is None:
            return None
        result = MagicMock()
        result.attributes = {"entity_id": members}
        return result

    hass.states.get.side_effect = state
    assert resolve_notification_targets(
        hass, {"targets": {"entity_id": ["light.house"]}}
    ) == ["light.shared", "switch.dimmer"]


# --- description passthrough -----------------------------------------------


def test_description_reaches_the_notification():
    options = {
        "notifications": {"fridge_ajar": notification_config("fridge_ajar", _form())}
    }
    notif = notifications_from_options(options)["fridge_ajar"]
    assert notif.description.startswith("A fridge has not cycled off")


def test_description_defaults_to_empty():
    cfg = notification_config("x", _form())
    del cfg["description"]
    notif = notifications_from_options({"notifications": {"x": cfg}})["x"]
    assert notif.description == ""


# --- migration -------------------------------------------------------------


def _v1_entry(targets, notifications):
    entry = MagicMock()
    entry.version = 1
    entry.data = {"name": "Bedrooms Notify Lights", "targets": targets}
    entry.options = {"notifications": notifications}
    return entry


@pytest.mark.asyncio
async def test_migration_pushes_pool_targets_into_each_notification():
    targets = {"entity_id": ["light.bedroom", "light.bathroom"]}
    entry = _v1_entry(
        targets,
        {
            "cooling": {"slug": "cooling", "display_name": "Cooling"},
            "heating": {"slug": "heating", "display_name": "Heating"},
        },
    )
    hass = MagicMock()

    assert await async_migrate_entry(hass, entry) is True

    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["version"] == 3
    migrated = kwargs["options"]["notifications"]
    assert migrated["cooling"]["targets"] == targets
    assert migrated["heating"]["targets"] == targets
    # The pool no longer owns targets.
    assert "targets" not in kwargs["data"]
    assert kwargs["data"]["name"] == "Bedrooms Notify Lights"


@pytest.mark.asyncio
async def test_migration_adds_empty_exclude_and_description():
    entry = _v1_entry(
        {"entity_id": ["light.x"]},
        {
            "cooling": {"slug": "cooling", "display_name": "Cooling"},
        },
    )
    hass = MagicMock()
    await async_migrate_entry(hass, entry)

    _, kwargs = hass.config_entries.async_update_entry.call_args
    cooling = kwargs["options"]["notifications"]["cooling"]
    assert cooling["exclude"] == {}
    assert cooling["description"] == ""
    assert cooling["display_mode"] == "full"


@pytest.mark.asyncio
async def test_migration_preserves_existing_notification_fields():
    entry = _v1_entry(
        {"entity_id": ["light.x"]},
        {
            "cooling": {
                "slug": "cooling",
                "display_name": "Cooling",
                "color": "blue",
                "duration": 5,
                "priority": 50,
            },
        },
    )
    hass = MagicMock()
    await async_migrate_entry(hass, entry)

    _, kwargs = hass.config_entries.async_update_entry.call_args
    cooling = kwargs["options"]["notifications"]["cooling"]
    assert cooling["color"] == "blue"
    assert cooling["duration"] == 5
    assert cooling["priority"] == 50


@pytest.mark.asyncio
async def test_migration_does_not_clobber_targets_already_set():
    own = {"entity_id": ["light.own"]}
    entry = _v1_entry(
        {"entity_id": ["light.pool"]},
        {
            "cooling": {"slug": "cooling", "display_name": "Cooling", "targets": own},
        },
    )
    hass = MagicMock()
    await async_migrate_entry(hass, entry)

    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["options"]["notifications"]["cooling"]["targets"] == own


@pytest.mark.asyncio
async def test_migration_upgrades_v2_entries_with_groups_and_activation():
    entry = MagicMock()
    entry.version = 2
    entry.data = {"name": "Notify Lights"}
    entry.options = {
        "notifications": {
            "charging": {
                "slug": "charging",
                "display_name": "Charging",
                "duration": 0,
                "state_entity": "sensor.charger",
            }
        }
    }
    hass = MagicMock()

    assert await async_migrate_entry(hass, entry) is True
    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["version"] == 3
    assert kwargs["options"]["groups"] == {}
    assert kwargs["options"]["notifications"]["charging"]["activation"] == "state_while"


@pytest.mark.asyncio
async def test_migration_is_a_noop_for_v3_entries():
    entry = MagicMock()
    entry.version = 3
    hass = MagicMock()

    assert await async_migrate_entry(hass, entry) is True
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_migration_handles_entry_with_no_notifications():
    entry = _v1_entry({"entity_id": ["light.x"]}, {})
    hass = MagicMock()

    assert await async_migrate_entry(hass, entry) is True
    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["options"]["notifications"] == {}
