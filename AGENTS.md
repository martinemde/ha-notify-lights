# Repository Notes

## Live Home Assistant access

The development Home Assistant instance is reachable over SSH at
`homeassistant.local` using the current workstation's normal SSH identity:

```console
ssh homeassistant.local
```

This opens the Advanced SSH & Web Terminal app container. Home Assistant's
configuration is mounted at `/config` (a symlink to `/homeassistant`), including
the deployed integration at `/config/custom_components/notify_lights`.

The `ha` command does not automatically receive a Supervisor token in this SSH
session. Load the app container's existing token into the remote shell without
printing, copying, or committing it:

```console
export SUPERVISOR_TOKEN="$(cat /run/s6/container_environment/SUPERVISOR_TOKEN)"
ha core info
```

Never enable shell tracing while the token is set, and never display or persist
the token. It can authenticate requests through the Supervisor's Core API
proxy:

```console
curl -fsS \
  -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  http://supervisor/core/api/states
```

Useful read-only diagnostics:

```console
ha core logs --lines 1000
ha apps list --raw-json
jq -c '[.data.entries[] | select(.domain == "notify_lights")]' \
  /config/.storage/core.config_entries
jq -c '[.data.entities[] | select(.platform == "notify_lights")]' \
  /config/.storage/core.entity_registry
```

Before pressing a notification button, inspect its live `targets` attribute.
An empty list means the integration resolved no supported devices and pressing
it cannot display anything. Use the Core API to press a known momentary button:

```console
curl -fsS \
  -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"entity_id":"button.great_room_desk_notify_lights_cardiff_dinnertime"}' \
  http://supervisor/core/api/services/button/press
```

Prefer short-duration, single-device notifications for initial live tests.
Check Home Assistant and Zigbee2MQTT logs for the resulting MQTT command, and
clear any indefinite notification before finishing.
