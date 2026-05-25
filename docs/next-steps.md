# Notify Lights — Next Steps

## Current State (v0.2.0)

Working integration with:
- Options flow to add/remove notifications via Configure button
- Switch entities for stateful notifications (duration=0)
- Button entities for momentary notifications (duration>0)
- Inovelli Blue Z2M adapter (MQTT publish to Zigbee2MQTT)
- Priority-based active set ordering
- 44 unit/integration tests passing

## What to Test on Real Hardware

1. **Install and configure**
   - Add integration via HACS, restart HA
   - Click Configure → Add notification targeting a Blue Series switch
   - Verify the switch/button entity appears after reload

2. **Verify MQTT payload**
   - Turn on a notification switch entity
   - Monitor MQTT traffic: `mosquitto_sub -t "zigbee2mqtt/#" -v`
   - Confirm payload matches: `{"led_effect": {"effect": "solid", "color": 170, "level": 100, "duration": 255}}`
   - Turn off → confirm `{"led_effect": {"effect": "clear_effect"}}` is sent

3. **Test each effect**
   - Create notifications with each effect + speed combo
   - Verify LED behavior matches expectations on real hardware
   - Note any effects that don't work or look wrong

4. **Test priority stacking**
   - Create two notifications targeting the same switch with different priorities
   - Turn on low priority, then high priority → high should render
   - Turn off high → low should render
   - Turn off low → LEDs should clear

5. **Test momentary (button) entities**
   - Create a notification with duration=10
   - Press the button entity
   - Verify LED activates, then auto-clears after 10 seconds

## Implementation Gaps to Address

### Must fix before daily use

- **Target entity resolution**: The coordinator currently passes entity IDs through as-is and uses the device name from the device registry as the Z2M friendly name. This needs real-world validation — the Z2M device name in HA's device registry may not match the Z2M friendly name used in MQTT topics. May need to extract the friendly name from the device's MQTT identifier instead.

- **State restoration**: Stateful switch entities don't restore their state after HA restart. Need to add `RestoreEntity` mixin so active notifications survive restarts.

- **Entity creation without restart**: Currently requires a full integration reload when options change. Could use `async_forward_entry_setup` more dynamically.

### Feature gaps from the spec

- **Area and group target resolution**: Spec says targets can be `area_id:*` refs and `group.*` entities, resolved at activation time. Currently only entity IDs work.

- **Multi-LED stacking (Blue Series)**: Blue has 7 individually addressable LEDs via `individual_led_effect`. Currently only renders the top-priority notification on the full bar. Stacking would assign each active notification to its own LED (7=top priority, 6=second, etc.).

- **Edit existing notifications**: Options flow only has add/remove. Need an edit flow to modify notifications without deleting and recreating.

- **Per-target adapter override**: Spec mentions optional config to force a specific adapter for a device, bypassing auto-detection.

### Additional adapters

- **Inovelli Blue via ZHA**: Same hardware, different protocol path. Would use `zha.set_zigbee_cluster_attribute` instead of MQTT publish.

- **Inovelli Blue via Z-Wave (800 series Z-Wave variant)**: Uses `zwave_js.set_config_parameter` with parameter 99. Different value encoding (color + level*256 + duration*65536 + effect*16777216).

- **Inovelli Red Series**: Z-Wave only, parameter 16, older effect set (solid, blink, pulse, chase — no aurora/falling/rising). Needs effect fallback table.

- **Inovelli White Series**: Z-Wave only, single LED (no bar), very limited effects. Probably just solid + blink.

### Nice to have

- **Custom Lovelace card**: Visual management of notifications (out of spec scope but useful)
- **Diagnostics**: `diagnostics.py` for debugging adapter matching and active set state
- **HACS metadata polish**: Better README with install instructions, badges, screenshots
