"""Notify Lights — LED notifications as HA entities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

# Home Assistant is present when the integration is loaded. Keeping these
# optional at import time also lets pure model tooling (such as the LED bar
# preview script) import the package in an ordinary development environment.
try:
    from homeassistant.helpers import (
        device_registry as dr,
    )
    from homeassistant.helpers import (
        entity_registry as er,
    )
    from homeassistant.helpers.event import async_track_state_change_event
except ModuleNotFoundError:  # pragma: no cover - exercised by the preview CLI
    dr = None
    er = None
    async_track_state_change_event = None

from .adapter import AdapterRegistry
from .adapters.inovelli_blue_z2m import InovelliBlueZ2MAdapter
from .const import DOMAIN, NAMED_COLORS, DisplayMode, Effect, Speed
from .coordinator import NotifyLightsCoordinator, TransportGroup
from .notification import Notification

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "button", "binary_sensor", "light"]


def _get_or_create_coordinator(hass: HomeAssistant) -> NotifyLightsCoordinator:
    """Return the global coordinator singleton, creating it if needed."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "coordinator" not in domain_data:
        entity_registry = er.async_get(hass)
        device_registry = dr.async_get(hass)

        adapter_registry = AdapterRegistry()
        adapter_registry.register(InovelliBlueZ2MAdapter(hass))

        domain_data["coordinator"] = NotifyLightsCoordinator(
            hass, adapter_registry, entity_registry, device_registry
        )
        _LOGGER.info("Created global NotifyLightsCoordinator")

    return domain_data["coordinator"]


SUPPORTED_DOMAINS = {"light", "switch"}
MAX_GROUP_DEPTH = 3


def _expand_group_members(
    hass: HomeAssistant,
    entity_id: str,
    *,
    _depth: int = 0,
    _seen: set[str] | None = None,
) -> set[str]:
    """Expand a group entity recursively into concrete target entities.

    Target selectors are normalized before notifications enter the
    coordinator. That gives every physical entity one shared stack even when
    different notifications reach it through different groups, and makes
    exclusions work across selector types.
    """
    seen = set() if _seen is None else _seen
    if entity_id in seen:
        _LOGGER.warning("Target group cycle detected at %s", entity_id)
        return set()
    if _depth > MAX_GROUP_DEPTH:
        _LOGGER.warning(
            "Target group nesting is deeper than %d at %s", MAX_GROUP_DEPTH, entity_id
        )
        return {entity_id}

    state = hass.states.get(entity_id)
    members = (
        state.attributes.get("entity_id") or state.attributes.get("group_entities")
        if state is not None
        else None
    )
    if not members:
        return {entity_id}

    seen.add(entity_id)
    result: set[str] = set()
    for member_id in members:
        result.update(
            _expand_group_members(
                hass,
                member_id,
                _depth=_depth + 1,
                _seen=seen,
            )
        )
    seen.remove(entity_id)
    return result


def resolve_targets(hass: HomeAssistant, targets: dict | list) -> list[str]:
    """Resolve a TargetSelector to concrete light/switch entity IDs."""
    if isinstance(targets, list):
        selected = set(targets)
    else:
        selected: set[str] = set()
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)

        def add_device_entities(device_id: str) -> None:
            """Add enabled, user-facing light/switch entities for a device."""
            for entry in er.async_entries_for_device(ent_reg, device_id):
                if (
                    entry.domain in SUPPORTED_DOMAINS
                    and entry.disabled_by is None
                    and entry.entity_category is None
                ):
                    selected.add(entry.entity_id)

        for entity_id in targets.get("entity_id", []):
            selected.add(entity_id)

        for device_id in targets.get("device_id", []):
            add_device_entities(device_id)

        for area_id in targets.get("area_id", []):
            # An entity may override its device's area. Include those direct
            # assignments, then include entities whose device inherits the
            # area. Home Assistant stores the common case only on the device.
            for entry in er.async_entries_for_area(ent_reg, area_id):
                if (
                    entry.domain in SUPPORTED_DOMAINS
                    and entry.disabled_by is None
                    and entry.entity_category is None
                ):
                    selected.add(entry.entity_id)
            for device in dr.async_entries_for_area(dev_reg, area_id):
                add_device_entities(device.id)

    expanded: set[str] = set()
    for entity_id in selected:
        expanded.update(_expand_group_members(hass, entity_id))

    return sorted(
        entity_id
        for entity_id in expanded
        if entity_id.split(".", 1)[0] in SUPPORTED_DOMAINS
    )


def notifications_from_options(options: dict) -> dict[str, Notification]:
    """Build Notification objects from config entry options."""
    result: dict[str, Notification] = {}
    for slug, config in options.get("notifications", {}).items():
        color = config["color"]
        if isinstance(color, str) and color in NAMED_COLORS:
            color = NAMED_COLORS[color]
        result[slug] = Notification(
            name=slug,
            display_name=config.get("display_name", slug.replace("_", " ")),
            color=color,
            brightness=int(config["brightness"]),
            effect=Effect(config["effect"]),
            effect_speed=Speed(config["effect_speed"]),
            duration=int(config["duration"]),
            priority=int(config["priority"]),
            description=config.get("description", ""),
            state_entity=config.get("state_entity") or None,
            active_state=config.get("active_state", "on"),
            state_attribute=config.get("state_attribute") or None,
            display_mode=DisplayMode(config.get("display_mode", "full")),
        )
    _LOGGER.info("Loaded %d notifications from options", len(result))
    return result


def resolve_entry_targets(hass: HomeAssistant, options: dict) -> list[str]:
    """Resolve one catalog's fixed target set, minus anything it excludes.

    `targets` and `exclude` are both TargetSelector values, so each may name
    entities, devices and areas at once. This is what lets a catalog say
    "the whole house except the kids' rooms" without enumerating every
    switch that should light up. Every notification in the catalog shares
    this same target set -- a catalog is a light group.
    """
    included = set(resolve_targets(hass, options.get("targets", {})))
    excluded = set(resolve_targets(hass, options.get("exclude", {})))
    if not excluded:
        return sorted(included)
    kept = sorted(entity_id for entity_id in included if entity_id not in excluded)
    _LOGGER.debug(
        "Resolved catalog targets: %d included, %d excluded, %d kept",
        len(included),
        len(excluded),
        len(kept),
    )
    return kept


def targets_from_options(hass: HomeAssistant, options: dict) -> dict[str, list[str]]:
    """Resolve the catalog's targets, keyed by notification slug.

    Every notification in a catalog shares one target set, so every value
    here is the same list -- keyed by slug only because switch/button/
    binary_sensor setup already expects that shape.
    """
    entry_targets = resolve_entry_targets(hass, options)
    return {slug: entry_targets for slug in options.get("notifications", {})}


def transport_groups_from_options(
    hass: HomeAssistant,
    coordinator: NotifyLightsCoordinator,
    options: dict,
    *,
    name: str = "Notify Lights",
) -> list[TransportGroup]:
    """Build the adapter-native delivery group for one catalog, if configured."""
    target = str(options.get("zigbee2mqtt_group", "")).strip()
    if not target:
        return []
    if target.startswith("zigbee2mqtt/"):
        target = target.removeprefix("zigbee2mqtt/")
    if target.endswith("/set"):
        target = target.removesuffix("/set")

    members = set(resolve_targets(hass, options.get("targets", {})))
    members.difference_update(resolve_targets(hass, options.get("exclude", {})))
    supported = frozenset(coordinator.supported_targets(sorted(members)))
    if not supported:
        return []
    return [TransportGroup(name=name, target=target, members=supported)]


def _state_group_members(state) -> list[str]:
    """Return group members exposed by either HA group implementation."""
    if state is None:
        return []
    return list(
        state.attributes.get("entity_id")
        or state.attributes.get("group_entities")
        or []
    )


def _pending_native_group_entities(hass: HomeAssistant, options: dict) -> set[str]:
    """Find a native transport group whose single HA group is not ready yet.

    Zigbee2MQTT group light entities can be registered after Notify Lights
    during startup. A single entity target on a native transport group is the
    group-entity configuration; explicit multi-entity groups (such as the
    security group) already describe their physical members directly.
    """
    if not str(options.get("zigbee2mqtt_group", "")).strip():
        return set()
    entity_ids = options.get("targets", {}).get("entity_id", [])
    if len(entity_ids) != 1:
        return set()
    entity_id = entity_ids[0]
    if _state_group_members(hass.states.get(entity_id)):
        return set()
    return {entity_id}


def _migrate_to_v3(entry: ConfigEntry) -> dict:
    """Return v3-shaped options: targets on each notification, plus groups.

    v1 modelled a config entry as a pool of lights. v2 moved targets onto each
    notification. v3 adds reusable light groups and explicit activation
    labels while retaining the compact duration/source runtime representation.
    """
    pool_targets = entry.data.get("targets", {}) if entry.version < 2 else {}
    notifications = {
        slug: {
            **config,
            "targets": config.get("targets", pool_targets),
            "exclude": config.get("exclude", {}),
            "description": config.get("description", ""),
            "groups": config.get("groups", []),
            "state_attribute": config.get("state_attribute"),
            "display_mode": config.get("display_mode", "full"),
            "activation": config.get(
                "activation",
                (
                    "state_entered"
                    if config.get("state_entity") and int(config.get("duration", 0)) > 0
                    else "state_while"
                    if config.get("state_entity")
                    else "manual_timed"
                    if int(config.get("duration", 0)) > 0
                    else "manual_while"
                ),
            ),
        }
        for slug, config in entry.options.get("notifications", {}).items()
    }
    return {
        **entry.options,
        "groups": entry.options.get("groups", {}),
        "notifications": notifications,
    }


def _merge_target_selectors(*selectors: dict | list) -> dict[str, list[str]]:
    """Union any number of TargetSelector values into one."""
    merged: dict[str, list[str]] = {}
    for selector_value in selectors:
        if not selector_value:
            continue
        normalized = (
            {"entity_id": selector_value}
            if isinstance(selector_value, list)
            else selector_value
        )
        for key, values in normalized.items():
            if not values:
                continue
            merged[key] = sorted(set(merged.get(key, [])) | set(values))
    return merged


def _migrate_v3_to_v4(entry_id: str, options: dict) -> dict:
    """Collapse per-notification targets and reusable groups into one set.

    v4 makes a catalog itself a light group: every notification in it shares
    one fixed target set, so a single brightness/effect light entity can
    represent the whole catalog. This merge is best-effort -- it unions every
    target selector the catalog used to reference. Catalogs that previously
    routed different notifications to different areas end up targeting the
    union of all of them; split such a catalog into one per area afterward
    using each notification's original targets as a guide.
    """
    groups = options.get("groups", {})
    notifications = options.get("notifications", {})

    target_selectors = []
    exclude_selectors = []
    zigbee_groups: set[str] = set()

    def _collect_group(group: dict) -> None:
        target_selectors.append(group.get("targets", {}))
        exclude_selectors.append(group.get("exclude", {}))
        zigbee_group = str(group.get("zigbee2mqtt_group", "")).strip()
        if zigbee_group:
            zigbee_groups.add(zigbee_group)

    for config in notifications.values():
        target_selectors.append(config.get("targets", {}))
        exclude_selectors.append(config.get("exclude", {}))
        for group_slug in config.get("groups", []):
            group = groups.get(group_slug)
            if group is not None:
                _collect_group(group)

    for group in groups.values():
        _collect_group(group)

    if len(zigbee_groups) > 1:
        _LOGGER.warning(
            "Catalog %s merges %d distinct Zigbee2MQTT groups (%s) into one "
            "entry-level target set; leaving zigbee2mqtt_group blank. Split "
            "this catalog and re-set each one's group under Edit targets.",
            entry_id,
            len(zigbee_groups),
            sorted(zigbee_groups),
        )

    migrated_notifications = {
        slug: {
            k: v for k, v in config.items() if k not in {"targets", "exclude", "groups"}
        }
        for slug, config in notifications.items()
    }

    return {
        "targets": _merge_target_selectors(*target_selectors),
        "exclude": _merge_target_selectors(*exclude_selectors),
        "zigbee2mqtt_group": (
            next(iter(zigbee_groups)) if len(zigbee_groups) == 1 else ""
        ),
        "notifications": migrated_notifications,
    }


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old target storage up to v4's entry-level target set.

    Entries are migrated in place and existing notification slugs remain
    stable, preserving entity unique IDs and automation references.
    """
    if entry.version >= 4:
        return True

    options = _migrate_to_v3(entry) if entry.version < 3 else dict(entry.options)
    options = _migrate_v3_to_v4(entry.entry_id, options)
    new_data = {k: v for k, v in entry.data.items() if k != "targets"}

    _LOGGER.info(
        "Migrating entry %s to v4 with %d notification rule(s)",
        entry.entry_id,
        len(options["notifications"]),
    )
    hass.config_entries.async_update_entry(
        entry,
        data=new_data,
        options=options,
        version=4,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Setting up entry %s (%s)", entry.entry_id, entry.data.get("name"))

    pending_native_groups = _pending_native_group_entities(hass, entry.options)
    coordinator = _get_or_create_coordinator(hass)
    notifications = notifications_from_options(entry.options)
    targets = {
        slug: coordinator.supported_targets(resolved)
        for slug, resolved in targets_from_options(hass, entry.options).items()
    }
    coordinator.register_transport_groups(
        entry.entry_id,
        transport_groups_from_options(
            hass,
            coordinator,
            entry.options,
            name=entry.data.get("name", "Notify Lights"),
        ),
    )

    # One device per config entry; every notification entity hangs off it.
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get("name", "Notify Lights"),
    )

    entry_targets = coordinator.supported_targets(
        resolve_entry_targets(hass, entry.options)
    )
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "notifications": notifications,
        "targets": targets,
        "entry_targets": entry_targets,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    if pending_native_groups:
        reload_requested = False

        async def _async_native_group_ready(event) -> None:
            """Reload this catalog once its native HA group has members."""
            nonlocal reload_requested
            if reload_requested or not _state_group_members(
                event.data.get("new_state")
            ):
                return
            reload_requested = True
            _LOGGER.info(
                "Native group %s became ready; reloading catalog %s",
                event.data.get("entity_id"),
                entry.entry_id,
            )
            await hass.config_entries.async_reload(entry.entry_id)

        cancel_group_watcher = async_track_state_change_event(
            hass,
            sorted(pending_native_groups),
            _async_native_group_ready,
        )
        entry.async_on_unload(cancel_group_watcher)

        # Close the gap between initial target resolution and listener setup.
        ready_now = next(
            (
                entity_id
                for entity_id in pending_native_groups
                if _state_group_members(hass.states.get(entity_id))
            ),
            None,
        )
        if ready_now is not None:
            reload_requested = True
            _LOGGER.info(
                "Native group %s became ready during setup; scheduling catalog reload",
                ready_now,
            )
            hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))

    _LOGGER.info("Setup complete for catalog %s", entry.entry_id)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _LOGGER.info("Options updated for catalog %s, reloading", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Unloading catalog %s", entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
        await coordinator.async_deactivate_entry(entry.entry_id)
        coordinator.unregister_transport_groups(entry.entry_id)
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
