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
| `duration` | `0` = stateful (switch); `> 0` = momentary (button, auto-clears) |
| `priority` | `0`–`100`; arbitrates when several are active on one light |

Appearance and priority live here rather than at the call site, so callers say
*when* something is true and never *how it looks*. That split is what makes
priority arbitration possible at all: you cannot decide whether a fridge alert
outranks a charge-complete notification by looking at either automation.

### Calling it

Nothing to configure at the call site — a notification is just an entity:

```yaml
# stateful (duration: 0) — held until you turn it off
- action: switch.turn_on
  target:
    entity_id: switch.notify_fridge_ajar_kitchen

# momentary (duration > 0) — clears itself
- action: button.press
  target:
    entity_id: button.notify_hvac_cooling_bedrooms
```

### Why targets live on the notification

A stateful notification is a `switch` entity, and a switch cannot take
call-time parameters — so its definition is the only place its targets can
live. Before v2 the config entry was a *pool* of lights holding several
notifications, which forced the same notification to be redefined once per
pool. Those copies drifted: `cooling` existed twice with different durations,
and Home Assistant disambiguated the duplicate names into `notify_cooling` and
`notify_cooling_2`, pushing the ambiguity back onto callers.

### Targeting

Prefer areas or light groups over individual switches. Group entities are
expanded to their members (recursively, up to 3 levels), so targeting one area
light group keeps working as switches are added to that area.

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

## References

- [Blue Series LED Notifications with MQTT Publish (Zigbee2MQTT)](https://help.inovelli.com/en/articles/11357013-blue-series-led-notifications-with-mqtt-publish-zigbee2mqtt)
- [Blue Series Single LED Notifications with MQTT Publish (Zigbee2MQTT)](https://help.inovelli.com/en/articles/11357275-blue-series-single-led-notifications-with-mqtt-publish-zigbee2mqtt)
- [Blue Series LED Notifications - Home Assistant ZHA](https://help.inovelli.com/en/articles/12933821-blue-series-led-notifications-home-assistant-zha)
- [Zigbee2MQTT VZM31-SN device page](https://www.zigbee2mqtt.io/devices/VZM31-SN.html)
