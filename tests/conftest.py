"""Stub out Home Assistant modules so pure-Python unit tests run without HA."""

import sys
import types
from unittest.mock import MagicMock


class _ConfigFlow:
    """Minimal stub for homeassistant.config_entries.ConfigFlow."""

    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if domain:
            cls.domain = domain

    def async_show_form(self, *, step_id, data_schema=None, errors=None):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
        }

    def async_create_entry(self, *, title, data, options=None):
        return {
            "type": "create_entry",
            "title": title,
            "data": data,
            "options": options or {},
        }

    async def async_set_unique_id(self, unique_id):
        self._unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        pass


class _OptionsFlow:
    """Minimal stub for the current Home Assistant OptionsFlow API."""

    def __init__(self):
        self.config_entry = None
        self.hass = None

    def async_show_form(
        self, *, step_id, data_schema=None, errors=None, description_placeholders=None
    ):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
        }

    def async_create_entry(self, *, data, title=""):
        return {"type": "create_entry", "data": data}

    def async_show_menu(self, *, step_id, menu_options):
        return {"type": "menu", "step_id": step_id, "menu_options": menu_options}


_config_entries_stub = types.ModuleType("homeassistant.config_entries")
_config_entries_stub.ConfigFlow = _ConfigFlow
_config_entries_stub.ConfigEntry = MagicMock
_config_entries_stub.OptionsFlow = _OptionsFlow
_config_entries_stub.OptionsFlowWithConfigEntry = _OptionsFlow

_core_module = types.ModuleType("homeassistant.core")
_core_module.callback = lambda func: func
_core_module.Event = MagicMock
_core_module.HomeAssistant = MagicMock
_core_module.State = MagicMock
sys.modules["homeassistant.core"] = _core_module

# Stub homeassistant modules before any component imports
for module in [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.selector",
]:
    sys.modules.setdefault(module, MagicMock())

sys.modules["homeassistant.config_entries"] = _config_entries_stub

# Core constants used by restorable stateful switches.
_const_module = types.ModuleType("homeassistant.const")
_const_module.STATE_ON = "on"
_const_module.STATE_UNKNOWN = "unknown"
_const_module.STATE_UNAVAILABLE = "unavailable"
sys.modules["homeassistant.const"] = _const_module

# Stub voluptuous (used by config_flow for form schemas)
if "voluptuous" not in sys.modules:
    _vol = MagicMock()
    _vol.Schema = MagicMock(side_effect=lambda schema: schema)
    _vol.Required = MagicMock(side_effect=lambda key, **kw: key)
    _vol.Optional = MagicMock(side_effect=lambda key, **kw: key)
    sys.modules["voluptuous"] = _vol

# Switch entity stub
_switch_module = types.ModuleType("homeassistant.components.switch")


class _SwitchEntity:
    _attr_unique_id = None
    _attr_name = None
    _attr_has_entity_name = False

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def name(self):
        return self._attr_name


_switch_module.SwitchEntity = _SwitchEntity
sys.modules.setdefault(
    "homeassistant.components", types.ModuleType("homeassistant.components")
)
sys.modules["homeassistant.components.switch"] = _switch_module

# Binary sensor entity stub
_binary_sensor_module = types.ModuleType("homeassistant.components.binary_sensor")


class _BinarySensorEntity:
    _attr_unique_id = None
    _attr_name = None
    _attr_is_on = None
    _attr_available = True

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def name(self):
        return self._attr_name

    @property
    def is_on(self):
        return self._attr_is_on

    @property
    def available(self):
        return self._attr_available

    async def async_added_to_hass(self):
        pass

    def async_on_remove(self, callback):
        self._remove_callback = callback

    def async_write_ha_state(self):
        pass


_binary_sensor_module.BinarySensorEntity = _BinarySensorEntity
sys.modules["homeassistant.components.binary_sensor"] = _binary_sensor_module

# Button entity stub
_button_module = types.ModuleType("homeassistant.components.button")


class _ButtonEntity:
    _attr_unique_id = None
    _attr_name = None
    _attr_has_entity_name = False

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def name(self):
        return self._attr_name


_button_module.ButtonEntity = _ButtonEntity
sys.modules["homeassistant.components.button"] = _button_module

# Event helpers stub
_event_module = types.ModuleType("homeassistant.helpers.event")


def _async_call_later(hass, delay, callback):
    return MagicMock()


_event_module.async_call_later = _async_call_later


def _async_track_state_change_event(hass, entity_ids, callback):
    return MagicMock()


_event_module.async_track_state_change_event = _async_track_state_change_event
sys.modules["homeassistant.helpers.event"] = _event_module

# Restore-state mixin stub
_restore_state_module = types.ModuleType("homeassistant.helpers.restore_state")


class _RestoreEntity:
    async def async_get_last_state(self):
        return None


_restore_state_module.RestoreEntity = _RestoreEntity
sys.modules["homeassistant.helpers.restore_state"] = _restore_state_module
