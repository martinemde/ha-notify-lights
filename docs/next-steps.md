# Notify Lights — Ideas not yet built

- **Inovelli Blue via ZHA**: same hardware, different path —
  `zha.set_zigbee_cluster_attribute` instead of an MQTT publish.
- **Inovelli Blue via Z-Wave (800 series)**: `zwave_js.set_config_parameter`, parameter 99;
  value = color + level·256 + duration·65536 + effect·16777216.
- **Inovelli Red Series**: Z-Wave only, parameter 16, older effect set (solid, blink, pulse,
  chase); needs an effect fallback table.
- **Inovelli White Series**: Z-Wave only, single LED; probably solid and blink only.
- **Per-target adapter override**: force an adapter for a device instead of auto-detection.
- **Diagnostics** (`diagnostics.py`) for adapter matching and active-set state.
