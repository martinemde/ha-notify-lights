"""Stub out Home Assistant modules so pure-Python unit tests run without HA."""
import sys
from unittest.mock import MagicMock

# Stub homeassistant modules before any component imports
for module in [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.device_registry",
]:
    sys.modules.setdefault(module, MagicMock())
