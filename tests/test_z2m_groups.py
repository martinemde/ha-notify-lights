"""Tests for authoritative Zigbee2MQTT group discovery."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.notify_lights.z2m_groups import (
    async_friendly_name_for_device,
    group_id_from_device,
    parse_groups,
)


def test_parse_groups_uses_published_id_and_friendly_name():
    groups = parse_groups(
        """[
          {
            "friendly_name": "notify/area/living_area",
            "id": 16,
            "members": [
              {"endpoint": 1, "ieee_address": "0x001"},
              {"endpoint": 1, "ieee_address": "0x002"}
            ]
          }
        ]"""
    )

    assert groups[16].friendly_name == "notify/area/living_area"
    assert groups[16].members == frozenset({"0x001", "0x002"})


def test_group_id_comes_from_mqtt_group_device_identifier():
    device = SimpleNamespace(
        manufacturer="Zigbee2MQTT",
        model="Group",
        identifiers={("mqtt", "zigbee2mqtt_network_identifier_18")},
    )

    assert group_id_from_device(device) == 18


def test_physical_device_is_not_mistaken_for_group():
    device = SimpleNamespace(
        manufacturer="Inovelli",
        model="2-in-1 switch + dimmer",
        identifiers={("mqtt", "zigbee2mqtt_0x123")},
    )

    assert group_id_from_device(device) is None


@pytest.mark.asyncio
async def test_friendly_name_is_read_from_retained_registry(monkeypatch):
    payload = '[{"id":16,"friendly_name":"notify/area/living_area"}]'
    remove = MagicMock()

    async def async_subscribe(hass, topic, callback, qos):
        assert topic == "zigbee2mqtt/bridge/groups"
        hass.loop.call_soon(callback, SimpleNamespace(payload=payload))
        return remove

    mqtt = SimpleNamespace(
        async_subscribe=async_subscribe,
        is_connected=lambda hass: True,
    )

    monkeypatch.setattr(
        sys.modules["homeassistant.components"],
        "mqtt",
        mqtt,
        raising=False,
    )
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    device = SimpleNamespace(
        manufacturer="Zigbee2MQTT",
        model="Group",
        identifiers={("mqtt", "zigbee2mqtt_network_identifier_16")},
    )

    assert (
        await async_friendly_name_for_device(hass, device)
        == "notify/area/living_area"
    )
    remove.assert_called_once_with()


@pytest.mark.asyncio
async def test_registry_lookup_waits_for_mqtt_connection(monkeypatch):
    payload = '[{"id":18,"friendly_name":"notify/area/great_area"}]'
    state = {"connected": False}
    status_callback = None

    def async_subscribe_connection_status(hass, callback):
        nonlocal status_callback
        status_callback = callback
        return MagicMock()

    async def async_subscribe(hass, topic, callback, qos):
        hass.loop.call_soon(callback, SimpleNamespace(payload=payload))
        return MagicMock()

    mqtt = SimpleNamespace(
        async_subscribe=async_subscribe,
        async_subscribe_connection_status=async_subscribe_connection_status,
        is_connected=lambda hass: state["connected"],
    )
    monkeypatch.setattr(
        sys.modules["homeassistant.components"], "mqtt", mqtt, raising=False
    )
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    device = SimpleNamespace(
        manufacturer="Zigbee2MQTT",
        model="Group",
        identifiers={("mqtt", "zigbee2mqtt_network_identifier_18")},
    )

    task = asyncio.create_task(async_friendly_name_for_device(hass, device))
    await asyncio.sleep(0)
    assert status_callback is not None
    state["connected"] = True
    status_callback(True)

    assert await task == "notify/area/great_area"
