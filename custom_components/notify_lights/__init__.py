"""Notify Lights — LED notifications as HA entities."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .adapter import AdapterRegistry
from .adapters.inovelli_blue_z2m import InovelliBlueZ2MAdapter
from .const import DOMAIN, Effect, Speed, NAMED_COLORS
from .coordinator import NotifyLightsCoordinator
from .notification import Notification

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "button"]


def notifications_from_options(options: dict) -> dict[str, Notification]:
    """Build Notification objects from config entry options."""
    _LOGGER.debug("Parsing options: %s", options)
    result: dict[str, Notification] = {}
    for name, config in options.get("notifications", {}).items():
        color = config["color"]
        if color in NAMED_COLORS:
            color = NAMED_COLORS[color]
        result[name] = Notification(
            name=name,
            color=color,
            brightness=int(config["brightness"]),
            effect=Effect(config["effect"]),
            effect_speed=Speed(config["effect_speed"]),
            duration=int(config["duration"]),
            priority=int(config["priority"]),
            targets=config["targets"],
        )
        _LOGGER.debug(
            "Parsed notification %s: color=%s effect=%s targets=%s",
            name, color, config["effect"], config["targets"],
        )
    _LOGGER.info("Loaded %d notifications from options", len(result))
    return result


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Setting up entry %s", entry.entry_id)
    _LOGGER.debug("Entry data=%s options=%s", entry.data, entry.options)

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    adapter_registry = AdapterRegistry()
    adapter_registry.register(InovelliBlueZ2MAdapter(hass))

    coordinator = NotifyLightsCoordinator(
        hass, adapter_registry, entity_registry, device_registry
    )

    notifications = notifications_from_options(entry.options)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "notifications": notifications,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _LOGGER.info("Setup complete for entry %s", entry.entry_id)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _LOGGER.info(
        "Options updated for entry %s, reloading. options=%s",
        entry.entry_id, entry.options,
    )
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Unloading entry %s", entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    _LOGGER.info("Unload %s: %s", entry.entry_id, "ok" if unload_ok else "FAILED")
    return unload_ok
