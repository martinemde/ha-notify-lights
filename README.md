# Notify Lights

Home Assistant custom integration for LED notifications on smart switches.

## The model

A config entry is a **catalog** of notifications. Each notification is a
complete, self-describing thing:

| Field | Meaning |
|---|---|
| `name` | Display name; slugified into the entity ID |
| `description` | What this notification *means* — surfaced as an entity attribute |
| `targets` | Where it shows: any mix of entities, devices and areas |
| `exclude` | Subtracted from `targets` |
| `color`, `effect`, `effect_speed`, `brightness` | What it looks like |
| `duration` | `0` = stateful; `> 0` = momentary button that auto-clears |
| `state_entity`, `active_state` | Optional direct source for stateful notifications |
| `priority` | `0`–`100`; arbitrates when several are active on one light |

Appearance and priority live here rather than at the call site, so callers say
*when* something is true and never *how it looks*. That split is what makes
priority arbitration possible at all: you cannot decide whether a fridge alert
outranks a charge-complete notification by looking at either automation.

### Layering on Inovelli Blue switches

The Zigbee2MQTT adapter keeps the two highest-priority active notifications
visible. With one notification, the switch uses its native full-bar effect.
With two or more, LED 1 (the bottom pixel) becomes a solid indicator in the
second-priority notification's color, while LEDs 2–7 render the top-priority
notification. Notifications below those two stay in the active stack and move
into view as higher-priority notifications clear.

Layered bars use Zigbee2MQTT's `individual_led_effect` command. That command
has a smaller animation set than the full-bar command: blink falls back to slow
or fast (medium uses fast), and chase/falling/rising use the one speed exposed
by Zigbee2MQTT. The bottom priority indicator is intentionally always solid.

To preview a stack in a true-color terminal without a switch:

```console
python scripts/preview_inovelli_bar.py \
  urgent:red:90:pulse:fast \
  hvac:blue:30:solid \
  --commands
```

Each argument is
`NAME:COLOR:PRIORITY[:EFFECT[:SPEED[:BRIGHTNESS]]]`. Add `--no-color` for a
plain-text preview. `--commands` also prints the exact Zigbee2MQTT payloads.

### Calling it

Nothing to configure at the call site — a notification is just an entity:

```yaml
# manually stateful (duration: 0, no source) — held until turned off
- action: switch.turn_on
  target:
    entity_id: switch.notify_fridge_ajar_kitchen

# momentary (duration > 0) — clears itself
- action: button.press
  target:
    entity_id: button.notify_hvac_cooling_bedrooms
```

A stateful notification with a source entity needs no calling automation. It
is exposed as a read-only binary sensor, subscribes to the source, and evaluates
it immediately at setup:

```
state_entity: lock.front_door_lock
active_state: unlocked
```

This is preferable when HA already has an entity representing the fact. It is
restart-safe and avoids duplicating `on`/`off` synchronization in an automation.
Leave the source empty only when the notification must be controlled manually;
that form remains a switch. Impulses remain buttons.

### Why targets live on the notification

A notification entity cannot take call-time target parameters, so its
definition is the only place its targets can live. Before v2 the config entry
was a *pool* of lights holding several notifications, which forced the same
notification to be redefined once per pool. Those copies drifted: `cooling`
existed twice with different durations, and Home Assistant disambiguated the
duplicate names into `notify_cooling` and `notify_cooling_2`, pushing the
ambiguity back onto callers.

### Targeting

Prefer areas or light groups over individual switches. Group entities are
expanded to their members (recursively, up to 3 levels) before activation, so
notifications reaching one physical switch through different selectors share
the same priority stack. Targeting one area light group keeps working as
switches are added to that area and the integration is reloaded.

`exclude` exists for the case enumeration handles badly — "the whole house
except the kids' rooms":

```
targets:  light.magic_areas_light_groups_interior_all_lights
exclude:  areas [Cardiff's Room, Hana's Room]
```

### Naming

Put the zone in the name: "cooling in the bedrooms" is a genuinely different
fact from "cooling in the living area", with a different trigger and different
lights. Pick an ordering and hold it — system-first (`hvac_cooling_bedrooms`,
`hvac_heating_bedrooms`, `fridge_ajar_kitchen`) keeps related notifications
together as the catalog grows.

## Upgrading to 0.4.0

Config entries migrate automatically (v1 → v2): each notification inherits the
targets its pool used to own, and gains an empty `exclude` and `description`.

Entries are migrated **in place**, not merged into a single catalog — slugs are
only unique within an entry, so merging could collide. If you were running one
pool per area, you will end up with one catalog per area, each notification now
carrying its own targets. Consolidating into a single catalog is a manual step:
recreate the notifications in one entry and delete the others.

Manual stateful switches restore their active state after an integration reload
or Home Assistant restart. Source-bound binary sensors re-evaluate their source
at setup. Repeated activation is idempotent in either case.

## References

- [Blue Series LED Notifications with MQTT Publish (Zigbee2MQTT)](https://help.inovelli.com/en/articles/11357013-blue-series-led-notifications-with-mqtt-publish-zigbee2mqtt)
- [Blue Series Single LED Notifications with MQTT Publish (Zigbee2MQTT)](https://help.inovelli.com/en/articles/11357275-blue-series-single-led-notifications-with-mqtt-publish-zigbee2mqtt)
- [Blue Series LED Notifications - Home Assistant ZHA](https://help.inovelli.com/en/articles/12933821-blue-series-led-notifications-home-assistant-zha)
- [Zigbee2MQTT VZM31-SN device page](https://www.zigbee2mqtt.io/devices/VZM31-SN.html)
