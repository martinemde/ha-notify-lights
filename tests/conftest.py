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
        return {"type": "form", "step_id": step_id}

    def async_create_entry(self, *, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    async def async_set_unique_id(self, unique_id):
        self._unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        pass


class _OptionsFlowWithConfigEntry:
    """Minimal stub for OptionsFlowWithConfigEntry."""

    def __init__(self, config_entry=None):
        self.config_entry = config_entry
        self.options = getattr(config_entry, "options", {}) if config_entry else {}

    def async_show_form(self, *, step_id, data_schema=None, errors=None):
        return {"type": "form", "step_id": step_id}

    def async_create_entry(self, *, data, title=""):
        return {"type": "create_entry", "data": data}

    def async_show_menu(self, *, step_id, menu_options):
        return {"type": "menu", "step_id": step_id, "menu_options": menu_options}


_config_entries_stub = types.ModuleType("homeassistant.config_entries")
_config_entries_stub.ConfigFlow = _ConfigFlow
_config_entries_stub.ConfigEntry = MagicMock
_config_entries_stub.OptionsFlowWithConfigEntry = _OptionsFlowWithConfigEntry

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

# Stub voluptuous (used by config_flow for form schemas)
if "voluptuous" not in sys.modules:
    _vol = MagicMock()
    _vol.Schema = MagicMock(side_effect=lambda schema: schema)
    _vol.Required = MagicMock(side_effect=lambda key, **kw: key)
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
sys.modules["homeassistant.helpers.event"] = _event_module
