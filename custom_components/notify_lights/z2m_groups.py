"""Authoritative Zigbee2MQTT group discovery.

Zigbee2MQTT publishes a retained registry on ``zigbee2mqtt/bridge/groups``.
The MQTT device created for each discovered group carries the corresponding
numeric group ID. Joining those two values gives us the real MQTT friendly
name; no entity-ID or display-name convention is involved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

GROUPS_TOPIC = "zigbee2mqtt/bridge/groups"
Z2M_MANUFACTURER = "Zigbee2MQTT"
Z2M_GROUP_MODEL = "Group"
_MQTT_GROUP_IDENTIFIER = re.compile(r"^zigbee2mqtt_.+_(\d+)$")


@dataclass(frozen=True)
class Z2MGroup:
    """One entry from Zigbee2MQTT's retained group registry."""

    id: int
    friendly_name: str
    members: frozenset[str]


def parse_groups(payload: str | bytes) -> dict[int, Z2MGroup]:
    """Parse the retained Zigbee2MQTT group registry by numeric group ID."""
    raw = json.loads(payload)
    if not isinstance(raw, list):
        raise ValueError("Zigbee2MQTT group registry is not a list")

    groups: dict[int, Z2MGroup] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        group_id = item.get("id")
        friendly_name = item.get("friendly_name")
        if not isinstance(group_id, int) or not isinstance(friendly_name, str):
            continue
        members = frozenset(
            str(member["ieee_address"])
            for member in item.get("members", [])
            if isinstance(member, dict) and member.get("ieee_address")
        )
        groups[group_id] = Z2MGroup(group_id, friendly_name, members)
    return groups


def group_id_from_device(device: Any) -> int | None:
    """Return the Zigbee group ID carried by an HA MQTT group device."""
    if (
        device is None
        or device.manufacturer != Z2M_MANUFACTURER
        or device.model != Z2M_GROUP_MODEL
    ):
        return None

    for domain, identifier in device.identifiers:
        if domain != "mqtt":
            continue
        match = _MQTT_GROUP_IDENTIFIER.fullmatch(identifier)
        if match is not None:
            return int(match.group(1))
    return None


def group_devices_from_targets(hass: HomeAssistant, targets: dict) -> list[Any]:
    """Return genuine Z2M group devices named directly by a target selector."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    device_ids = set(targets.get("device_id", []))
    for entity_id in targets.get("entity_id", []):
        entity = entity_registry.async_get(entity_id)
        if entity is not None and entity.device_id is not None:
            device_ids.add(entity.device_id)

    return sorted(
        (
            device
            for device_id in device_ids
            if (device := device_registry.async_get(device_id)) is not None
            and group_id_from_device(device) is not None
        ),
        key=lambda device: device.id,
    )


async def async_get_groups(
    hass: HomeAssistant, *, timeout: float = 15.0
) -> dict[int, Z2MGroup]:
    """Read Zigbee2MQTT's retained group registry from MQTT once."""
    # Import lazily so the package's pure model modules remain usable without
    # a Home Assistant installation (including the preview tooling).
    from homeassistant.components import mqtt

    async with asyncio.timeout(timeout):
        if not mqtt.is_connected(hass):
            connected: asyncio.Future[None] = hass.loop.create_future()

            def _connection_changed(is_connected: bool) -> None:
                if is_connected and not connected.done():
                    connected.set_result(None)

            remove_connection_listener = mqtt.async_subscribe_connection_status(
                hass, _connection_changed
            )
            try:
                # Close the race between the initial state check and listener
                # registration.
                if mqtt.is_connected(hass):
                    connected.set_result(None)
                await connected
            finally:
                remove_connection_listener()

        result: asyncio.Future[dict[int, Z2MGroup]] = hass.loop.create_future()

        def _receive(message) -> None:
            if result.done():
                return
            try:
                result.set_result(parse_groups(message.payload))
            except (json.JSONDecodeError, TypeError, ValueError) as err:
                result.set_exception(err)

        remove = await mqtt.async_subscribe(hass, GROUPS_TOPIC, _receive, qos=0)
        try:
            return await result
        finally:
            remove()


async def async_friendly_name_for_device(
    hass: HomeAssistant, device: Any, *, timeout: float = 15.0
) -> str | None:
    """Resolve one HA MQTT group device to its exact Z2M friendly name."""
    group_id = group_id_from_device(device)
    if group_id is None:
        return None
    group = (await async_get_groups(hass, timeout=timeout)).get(group_id)
    if group is None:
        _LOGGER.warning(
            "Zigbee2MQTT group ID %d is absent from %s", group_id, GROUPS_TOPIC
        )
        return None
    return group.friendly_name


async def async_groups_for_devices(
    hass: HomeAssistant, devices: list[Any], *, timeout: float = 15.0
) -> dict[str, Z2MGroup]:
    """Resolve several HA group devices with one retained-registry read."""
    registry = await async_get_groups(hass, timeout=timeout)
    resolved: dict[str, Z2MGroup] = {}
    for device in devices:
        group_id = group_id_from_device(device)
        if group_id is not None and (group := registry.get(group_id)) is not None:
            resolved[device.id] = group
    return resolved
