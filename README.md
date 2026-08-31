# Notify Lights

Home Assistant custom integration for routing state notifications to LED bars on
smart switches.

## The configuration model

Notify Lights has two user-facing concepts.

### Light groups answer “where?”

Create reusable destinations once, then use them from many rules:

- **Common alerts** — most switches, excluding the kids’ rooms
- **Near garage** — Great Room Entry Lights and Great Room Ceiling Lights
- **Bedrooms HVAC** / **Living HVAC** — the non-kid-bedroom switches in each zone
- **Outside office** and **Outside bathroom** — one nearby switch each

A light group accepts Home Assistant entities, devices, and areas. Its
**Except** field subtracts entities, devices, or areas, making “the whole house
except the kids’ rooms” a first-class configuration rather than a copied list.

Editing a light group updates every notification rule that uses it.

If the same switches belong to a Zigbee2MQTT group, enter that group's friendly
name in **Zigbee2MQTT group** (for example, `notify/security`). Notify Lights
then sends one native Zigbee groupcast whenever every member needs the same LED
layout. If another notification makes member layouts differ, it automatically
falls back to rendering those switches individually. The Home Assistant target
selection and Zigbee2MQTT group membership must describe the same switches.

### Notification rules answer “when and what?”

Every rule has an explicit activation behavior:

| Behavior | Resulting HA entity | Use it for |
|---|---|---|
| Show while an entity is in a state | Binary sensor | Charging, unlocked, door open, heating/cooling, occupied |
| Show for a time when an entity enters a state | Binary sensor with timer | Charger ready, package delivered |
| Manual, stays on until turned off | Switch | Conditions controlled by an existing automation |
| Manual, turns off after a time | Button | Impulses controlled by an existing automation |

There is no hidden “duration 0 changes the entity type” choice in the UI. Timed
rules ask for a duration; while-active rules do not.

Automatic rules ask for a source entity, then show its main state and current
attributes in plain language. A climate rule can watch hvac_action directly;
there is no need to create an intermediate template sensor. Notify Lights
offers values reported by the chosen property (including enum options when
available), while still allowing a custom value.

Each rule chooses one or more light groups, optional additional targets, an
optional exclusion, and its color/effect/brightness/priority. Coverage is an
explicit choice between the full light bar and a one-pixel bottom indicator.

## Tesla example

First create **Near garage** containing:

- light.great_room_entry_lights_2
- light.great_room_ceiling_lights

Then create two rules:

| Rule | Activation | Source | State | Duration |
|---|---|---|---|---|
| Tesla charging | Show while in state | sensor.tesla_wall_connector_status | charging | While charging |
| Tesla charger ready | Show when state is entered | sensor.tesla_wall_connector_status | ready | 300 seconds |

Both rules route to **Near garage**. Charging synchronizes immediately after a
Home Assistant restart. Ready is edge-triggered and deliberately does not replay
merely because Home Assistant starts while the sensor already says ready.

## Suggested rule layout

The use cases below become a small number of groups plus straightforward rules:

| Situation | Light group | Source-state strategy |
|---|---|---|
| Doors unlocked | Common alerts | One while-state rule per lock, or a template binary sensor aggregating locks |
| Backdoors open | Common alerts | While open |
| Heat / cool | HVAC zone group | Follow hvac_action; low priority; one-pixel indicator |
| Tesla charging / ready | Near garage | While charging; 300 seconds on entering ready |
| On a call | Outside office | While on call |
| Bathroom occupied | Outside bathroom | While occupied |
| Fridge door open | Common alerts | While open |
| Package at door | Common alerts | Timed on entering detected/delivered |
| Garage door | Common alerts | Separate opening, closing, and open rules sharing one source and group |

A situation with visually distinct states is intentionally represented by
multiple rules. They share the source and group, but each state owns its
appearance and timeout. That keeps priority arbitration and testing simple.

## Layering on Inovelli Blue switches

The Zigbee2MQTT adapter keeps the two highest-priority active notifications
visible. A full-bar rule uses the native full-bar effect when alone. A one-pixel
rule always stays on the bottom pixel, even when it is the only active rule. If
a full-bar and an indicator are active together, the indicator owns LED 1 and
the full notification owns LEDs 2–7. Two legacy full-bar rules retain the same
layered behavior. Lower-priority notifications remain in the stack and move
into view as higher-priority notifications clear.

The adapter treats the switch like a small shadow DOM: a native full-bar
effect is the base layer and individual LED effects override only the pixels
they occupy. It remembers the last commanded layers for each physical switch
and sends only changes. Adding or removing one indicator normally costs one
Zigbee command; the underlying full-bar animation resumes when that indicator
is cleared. On the first render after startup, and during explicit teardown,
all eight independently latched layers are reconciled so an old notification
cannot leak through.

Zigbee2MQTT has separate `clear_effect` commands for the full bar and for each
of LEDs 1–7; it does not expose a writable clear-all command. The adapter uses
the smallest applicable clear once state is known. Individual blink falls back
to slow or fast (medium uses fast), and chase/falling/rising use the one speed
exposed by Zigbee2MQTT. The bottom priority indicator is always solid.

Priority 30 and below is reserved for minor notifications. These rules always
have a one-pixel footprint in the normal stack, even when their configured
coverage is Full bar. They behave like any other backgrounded, squashed
notification rather than being pinned to a particular LED. This keeps state
such as active heating or cooling visible without taking over the switch.

To preview a stack in a true-color terminal:

    python scripts/preview_inovelli_bar.py \
      urgent:red:90:pulse:fast \
      hvac:blue:30:solid \
      --commands

Each argument is NAME:COLOR:PRIORITY[:EFFECT[:SPEED[:BRIGHTNESS]]]. Add
--no-color for a plain-text preview. --commands prints the exact Zigbee2MQTT
payloads.

## Calling manual rules

Manual rules remain ordinary Home Assistant entities:

    # Manual, stays on
    - action: switch.turn_on
      target:
        entity_id: switch.notify_lights_fridge_ajar

    # Manual, timed
    - action: button.press
      target:
        entity_id: button.notify_lights_package_at_door

Automatic rules need no calling automation. Their binary sensors expose the
source, matching state, duration, priority, and resolved physical targets as
attributes.

## Upgrading to 0.8.0

Entries migrate automatically to config version 3:

- v1 pool targets remain attached to their existing notifications.
- v2 notifications gain explicit activation behavior and an empty reusable
  group list. Existing rules default to full-bar coverage and main-state
  matching.
- Existing entity unique IDs and notification slugs remain unchanged.

The migration does not invent groups from old targets. Existing rules keep
working as before; groups can be introduced gradually through the options flow.

## References

- [Blue Series LED Notifications with MQTT Publish (Zigbee2MQTT)](https://help.inovelli.com/en/articles/11357013-blue-series-led-notifications-with-mqtt-publish-zigbee2mqtt)
- [Blue Series Single LED Notifications with MQTT Publish (Zigbee2MQTT)](https://help.inovelli.com/en/articles/11357275-blue-series-single-led-notifications-with-mqtt-publish-zigbee2mqtt)
- [Blue Series LED Notifications - Home Assistant ZHA](https://help.inovelli.com/en/articles/12933821-blue-series-led-notifications-home-assistant-zha)
- [Zigbee2MQTT VZM31-SN device page](https://www.zigbee2mqtt.io/devices/VZM31-SN.html)
