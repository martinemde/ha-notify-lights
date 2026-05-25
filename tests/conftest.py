"""Stub out Home Assistant modules so pure-Python unit tests run without HA."""
import sys
from unittest.mock import MagicMock


class _ConfigFlow:
    """Minimal stub for homeassistant.config_entries.ConfigFlow.

    Supports the metaclass-style `domain=` keyword used in subclass definitions:
        class MyFlow(ConfigFlow, domain=DOMAIN): ...
    """

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


# Build a stub module for homeassistant.config_entries that exposes ConfigFlow
_config_entries_stub = MagicMock()
_config_entries_stub.ConfigFlow = _ConfigFlow

# Stub homeassistant modules before any component imports
for module in [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.device_registry",
]:
    sys.modules.setdefault(module, MagicMock())

sys.modules["homeassistant.config_entries"] = _config_entries_stub
