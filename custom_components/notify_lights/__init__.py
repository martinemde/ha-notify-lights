"""Notify Lights — LED notifications as HA entities."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)

from .adapter import AdapterRegistry
from .adapters.inovelli_blue_z2m import InovelliBlueZ2MAdapter
from .const import DOMAIN, Effect, Speed, NAMED_COLORS
from .coordinator import NotifyLightsCoordinator
from .notification import Notification

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "button"]


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


def resolve_targets(hass: HomeAssistant, targets: dict | list) -> list[str]:
    """Resolve a TargetSelector dict to a flat list of entity IDs."""
    if isinstance(targets, list):
        return targets

    entity_ids: set[str] = set()
    ent_reg = er.async_get(hass)

    for entity_id in targets.get("entity_id", []):
        entity_ids.add(entity_id)

    for device_id in targets.get("device_id", []):
        for entry in er.async_entries_for_device(ent_reg, device_id):
            if entry.domain in SUPPORTED_DOMAINS:
                entity_ids.add(entry.entity_id)

    for area_id in targets.get("area_id", []):
        for entry in er.async_entries_for_area(ent_reg, area_id):
            if entry.domain in SUPPORTED_DOMAINS:
                entity_ids.add(entry.entity_id)

    return sorted(entity_ids)


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
        )
    _LOGGER.info("Loaded %d notifications from options", len(result))
    return result


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Setting up pool entry %s (%s)", entry.entry_id, entry.data.get("name"))

    coordinator = _get_or_create_coordinator(hass)
    notifications = notifications_from_options(entry.options)
    targets = resolve_targets(hass, entry.data.get("targets", {}))

    # Register device for this pool
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get("name", "Notify Lights Pool"),
    )

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "notifications": notifications,
        "targets": targets,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _LOGGER.info("Setup complete for pool %s", entry.entry_id)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _LOGGER.info("Options updated for pool %s, reloading", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Unloading pool %s", entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
