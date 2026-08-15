"""Tests for per-notification targets, exclusion, and the v1 -> v2 migration."""
import pytest
from unittest.mock import MagicMock

from custom_components.notify_lights import (
    async_migrate_entry,
    notifications_from_options,
    resolve_notification_targets,
    targets_from_options,
)
from custom_components.notify_lights.config_flow import notification_config


def _hass():
    return MagicMock()


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


def test_notification_config_defaults_optional_fields():
    form = _form()
    del form["description"]
    del form["exclude"]
    cfg = notification_config("fridge_ajar", form)
    assert cfg["description"] == ""
    assert cfg["exclude"] == {}


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


def test_targets_from_options_keys_by_slug():
    options = {
        "notifications": {
            "one": {"targets": {"entity_id": ["light.a", "light.b"]},
                    "exclude": {"entity_id": ["light.b"]}},
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


# --- description passthrough -----------------------------------------------


def test_description_reaches_the_notification():
    options = {"notifications": {"fridge_ajar": notification_config(
        "fridge_ajar", _form()
    )}}
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
    entry = _v1_entry(targets, {
        "cooling": {"slug": "cooling", "display_name": "Cooling"},
        "heating": {"slug": "heating", "display_name": "Heating"},
    })
    hass = MagicMock()

    assert await async_migrate_entry(hass, entry) is True

    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["version"] == 2
    migrated = kwargs["options"]["notifications"]
    assert migrated["cooling"]["targets"] == targets
    assert migrated["heating"]["targets"] == targets
    # The pool no longer owns targets.
    assert "targets" not in kwargs["data"]
    assert kwargs["data"]["name"] == "Bedrooms Notify Lights"


@pytest.mark.asyncio
async def test_migration_adds_empty_exclude_and_description():
    entry = _v1_entry({"entity_id": ["light.x"]}, {
        "cooling": {"slug": "cooling", "display_name": "Cooling"},
    })
    hass = MagicMock()
    await async_migrate_entry(hass, entry)

    _, kwargs = hass.config_entries.async_update_entry.call_args
    cooling = kwargs["options"]["notifications"]["cooling"]
    assert cooling["exclude"] == {}
    assert cooling["description"] == ""


@pytest.mark.asyncio
async def test_migration_preserves_existing_notification_fields():
    entry = _v1_entry({"entity_id": ["light.x"]}, {
        "cooling": {
            "slug": "cooling", "display_name": "Cooling",
            "color": "blue", "duration": 5, "priority": 50,
        },
    })
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
    entry = _v1_entry({"entity_id": ["light.pool"]}, {
        "cooling": {"slug": "cooling", "display_name": "Cooling", "targets": own},
    })
    hass = MagicMock()
    await async_migrate_entry(hass, entry)

    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["options"]["notifications"]["cooling"]["targets"] == own


@pytest.mark.asyncio
async def test_migration_is_a_noop_for_v2_entries():
    entry = MagicMock()
    entry.version = 2
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
