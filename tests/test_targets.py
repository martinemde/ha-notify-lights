"""Tests for catalog-level targets, exclusions, and config-entry migrations."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.notify_lights import (
    _pending_native_group_entities,
    async_migrate_entry,
    notifications_from_options,
    only_appearance_changed,
    resolve_entry_targets,
    targets_from_options,
    transport_groups_from_options,
)
from custom_components.notify_lights.config_flow import notification_config


def _hass():
    hass = MagicMock()
    hass.states.get.return_value = None
    return hass


def _form(name="Fridge Ajar", **overrides):
    """A submitted add/modify notification-details form."""
    data = {
        "name": name,
        "description": "A fridge has not cycled off; door may be cracked.",
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


def test_notification_config_stores_appearance_and_description():
    cfg = notification_config("fridge_ajar", _form())
    assert cfg["slug"] == "fridge_ajar"
    assert cfg["color"] == "red"
    assert cfg["description"].startswith("A fridge has not cycled off")
    assert "targets" not in cfg
    assert "groups" not in cfg


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
    cfg = notification_config("fridge_ajar", form)
    assert cfg["description"] == ""
    assert cfg["state_entity"] is None
    assert cfg["active_state"] == "on"
    assert cfg["state_attribute"] is None
    assert cfg["display_mode"] == "full"


# --- catalog target resolution ----------------------------------------------


def test_resolve_entry_targets_without_exclusion():
    options = {"targets": {"entity_id": ["light.a", "light.b"]}}
    assert resolve_entry_targets(_hass(), options) == ["light.a", "light.b"]


def test_resolve_entry_targets_subtracts_exclusion():
    """'The whole house except the kids' rooms' is the motivating case."""
    options = {
        "targets": {"entity_id": ["light.a", "light.b", "light.kid"]},
        "exclude": {"entity_id": ["light.kid"]},
    }
    assert resolve_entry_targets(_hass(), options) == ["light.a", "light.b"]


def test_exclusion_of_untargeted_entity_is_harmless():
    options = {
        "targets": {"entity_id": ["light.a"]},
        "exclude": {"entity_id": ["light.not_targeted"]},
    }
    assert resolve_entry_targets(_hass(), options) == ["light.a"]


def test_excluding_everything_yields_no_targets():
    options = {
        "targets": {"entity_id": ["light.a"]},
        "exclude": {"entity_id": ["light.a"]},
    }
    assert resolve_entry_targets(_hass(), options) == []


def test_missing_targets_yields_no_targets():
    assert resolve_entry_targets(_hass(), {}) == []


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
        assert resolve_entry_targets(hass, {"targets": {"area_id": ["kitchen"]}}) == [
            "light.kitchen_dimmer"
        ]


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
        assert resolve_entry_targets(hass, {"targets": {"area_id": ["kitchen"]}}) == [
            "light.main"
        ]


def test_targets_from_options_shares_one_target_set_across_notifications():
    """The point of the v4 redesign: a catalog is one light group."""
    options = {
        "targets": {"entity_id": ["light.a", "light.b"]},
        "exclude": {"entity_id": ["light.b"]},
        "notifications": {
            "one": {},
            "two": {},
        },
    }
    resolved = targets_from_options(_hass(), options)
    assert resolved == {
        "one": ["light.a"],
        "two": ["light.a"],
    }


def test_overlapping_targets_normalize_to_shared_physical_entity(monkeypatch):
    """Different selectors must converge on one coordinator stack key."""
    hass = _hass()

    def state(entity_id):
        members = {
            "light.bedrooms": ["light.shared", "light.bed"],
        }.get(entity_id)
        if members is None:
            return None
        result = MagicMock()
        result.attributes = {"entity_id": members}
        return result

    hass.states.get.side_effect = state
    options = {"targets": {"entity_id": ["light.bedrooms"]}}

    resolved = resolve_entry_targets(hass, options)
    assert "light.shared" in resolved
    assert "light.bedrooms" not in resolved


def test_group_target_can_exclude_concrete_member():
    hass = _hass()
    group = MagicMock()
    group.attributes = {"entity_id": ["light.keep", "light.exclude"]}
    hass.states.get.side_effect = lambda entity_id: (
        group if entity_id == "light.all" else None
    )
    options = {
        "targets": {"entity_id": ["light.all"]},
        "exclude": {"entity_id": ["light.exclude"]},
    }
    assert resolve_entry_targets(hass, options) == ["light.keep"]


def test_zigbee2mqtt_group_entities_are_expanded():
    hass = _hass()
    group = MagicMock()
    group.attributes = {
        "group_entities": ["light.entry", "light.ceiling", "switch.dimmer"]
    }
    hass.states.get.side_effect = lambda entity_id: (
        group if entity_id == "light.notify_area" else None
    )

    assert resolve_entry_targets(
        hass, {"targets": {"entity_id": ["light.notify_area"]}}
    ) == ["light.ceiling", "light.entry", "switch.dimmer"]


def test_multiple_native_groups_build_independent_transport_groups():
    hass = _hass()
    coordinator = MagicMock()
    coordinator.supported_targets.side_effect = lambda members: members
    options = {
        "targets": {"device_id": ["bedroom", "living", "great"]},
        "zigbee2mqtt_groups": {
            "bedroom": "notify/area/bedroom_area",
            "living": "notify/area/living_area",
            "great": "notify/area/great_area",
        },
    }
    members = {
        "bedroom": ["light.bed_1", "light.bed_2"],
        "living": ["light.living_1"],
        "great": ["light.great_1", "light.great_2"],
    }

    def resolve(_hass, targets):
        if not targets:
            return []
        return members[targets["device_id"][0]]

    with patch("custom_components.notify_lights.resolve_targets", side_effect=resolve):
        groups = transport_groups_from_options(
            hass, coordinator, options, name="Security"
        )

    assert {group.target for group in groups} == {
        "notify/area/bedroom_area",
        "notify/area/living_area",
        "notify/area/great_area",
    }
    assert {group.members for group in groups} == {
        frozenset({"light.bed_1", "light.bed_2"}),
        frozenset({"light.living_1"}),
        frozenset({"light.great_1", "light.great_2"}),
    }


def test_unavailable_single_entity_native_group_is_pending():
    options = {
        "targets": {"entity_id": ["light.notify_area_bedrooms"]},
        "zigbee2mqtt_group": "notify/area/bedroom_area",
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
        "targets": {"entity_id": ["light.notify_area_living_area"]},
        "zigbee2mqtt_group": "notify/area/living_area",
    }
    assert _pending_native_group_entities(hass, options) == set()


def test_explicit_multi_entity_native_group_does_not_wait_for_group_attributes():
    options = {
        "targets": {"entity_id": ["light.entry", "light.ceiling"]},
        "zigbee2mqtt_group": "notify/security",
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
    assert resolve_entry_targets(hass, {"targets": {"entity_id": ["light.house"]}}) == [
        "light.shared",
        "switch.dimmer",
    ]


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


# --- migration ---------------------------------------------------------


def _v1_entry(targets, notifications):
    entry = MagicMock()
    entry.version = 1
    entry.data = {"name": "Bedrooms Notify Lights", "targets": targets}
    entry.options = {"notifications": notifications}
    return entry


@pytest.mark.asyncio
async def test_migration_moves_pool_targets_to_the_entry_root():
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
    assert kwargs["version"] == 4
    assert kwargs["options"]["targets"]["entity_id"] == sorted(targets["entity_id"])
    # Notifications no longer carry their own targets.
    assert "targets" not in kwargs["options"]["notifications"]["cooling"]
    assert "targets" not in kwargs["options"]["notifications"]["heating"]
    assert "targets" not in kwargs["data"]
    assert kwargs["data"]["name"] == "Bedrooms Notify Lights"


@pytest.mark.asyncio
async def test_migration_upgrades_v2_entries_with_activation():
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
    assert kwargs["version"] == 4
    assert kwargs["options"]["notifications"]["charging"]["activation"] == "state_while"


@pytest.mark.asyncio
async def test_migration_is_a_noop_for_v4_entries():
    entry = MagicMock()
    entry.version = 4
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


@pytest.mark.asyncio
async def test_migration_merges_per_notification_targets_into_the_entry():
    """v3 entries could send different notifications to different areas.

    v4 can't represent that split, so the merge is a union: nothing gets
    silently dropped, but the user needs to re-split the catalog by hand.
    """
    entry = MagicMock()
    entry.version = 3
    entry.data = {"name": "Multi-area catalog"}
    entry.options = {
        "groups": {},
        "notifications": {
            "bedrooms": {
                "slug": "bedrooms",
                "display_name": "Bedrooms",
                "targets": {"entity_id": ["light.bed"]},
            },
            "living": {
                "slug": "living",
                "display_name": "Living",
                "targets": {"entity_id": ["light.liv"]},
            },
        },
    }
    hass = MagicMock()

    assert await async_migrate_entry(hass, entry) is True
    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["options"]["targets"]["entity_id"] == ["light.bed", "light.liv"]


@pytest.mark.asyncio
async def test_migration_merges_reusable_groups_into_the_entry():
    entry = MagicMock()
    entry.version = 3
    entry.data = {"name": "Catalog"}
    entry.options = {
        "groups": {
            "near_garage": {
                "slug": "near_garage",
                "display_name": "Near garage",
                "targets": {"entity_id": ["light.garage"]},
                "zigbee2mqtt_group": "notify/near_garage",
            }
        },
        "notifications": {
            "tesla_charging": {
                "slug": "tesla_charging",
                "display_name": "Tesla charging",
                "groups": ["near_garage"],
            }
        },
    }
    hass = MagicMock()

    assert await async_migrate_entry(hass, entry) is True
    _, kwargs = hass.config_entries.async_update_entry.call_args
    options = kwargs["options"]
    assert options["targets"]["entity_id"] == ["light.garage"]
    assert options["zigbee2mqtt_group"] == "notify/near_garage"
    assert "groups" not in options["notifications"]["tesla_charging"]


@pytest.mark.asyncio
async def test_migration_blanks_zigbee2mqtt_group_when_groups_disagree():
    entry = MagicMock()
    entry.version = 3
    entry.data = {"name": "Catalog"}
    entry.options = {
        "groups": {
            "a": {
                "slug": "a",
                "display_name": "A",
                "targets": {"entity_id": ["light.a"]},
                "zigbee2mqtt_group": "notify/a",
            },
            "b": {
                "slug": "b",
                "display_name": "B",
                "targets": {"entity_id": ["light.b"]},
                "zigbee2mqtt_group": "notify/b",
            },
        },
        "notifications": {},
    }
    hass = MagicMock()

    assert await async_migrate_entry(hass, entry) is True
    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["options"]["zigbee2mqtt_group"] == ""
    assert set(kwargs["options"]["targets"]["entity_id"]) == {"light.a", "light.b"}


# --- restyling vs. reconfiguring -------------------------------------------


def _options(**overrides):
    notification = {
        "slug": "fridge_ajar",
        "display_name": "Fridge ajar",
        "activation": "manual_while",
        "color": 21,
        "brightness": 100,
        "effect": "pulse",
        "effect_speed": "medium",
        "duration": 0,
        "priority": 75,
        "display_mode": "full",
    }
    notification.update(overrides)
    return {
        "targets": {"area_id": ["kitchen"]},
        "exclude": {},
        "zigbee2mqtt_group": "",
        "notifications": {"fridge_ajar": notification},
    }


def test_a_restyled_notification_does_not_reload_the_catalog():
    assert only_appearance_changed(
        _options(), _options(color=240, effect="blink", effect_speed="fast")
    )


def test_a_reprioritized_notification_reloads_the_catalog():
    assert not only_appearance_changed(_options(), _options(priority=20))


def test_a_new_notification_reloads_the_catalog():
    changed = _options()
    changed["notifications"]["heating"] = dict(changed["notifications"]["fridge_ajar"])
    assert not only_appearance_changed(_options(), changed)


def test_retargeting_the_catalog_reloads_it():
    changed = _options()
    changed["targets"] = {"area_id": ["kitchen", "pantry"]}
    assert not only_appearance_changed(_options(), changed)
