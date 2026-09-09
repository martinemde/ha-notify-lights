# Notify Lights

Home Assistant custom integration for routing state notifications to LED bars on
smart switches.

## The configuration model

Notify Lights has two user-facing concepts.

### A catalog is a device group

Each Notify Lights device (config entry) has a name and one fixed target: one
or more native Zigbee2MQTT groups, or a set of physical Inovelli devices. It is chosen
when you create the catalog and editable afterward from its device page under
**Edit notification lights**. Every notification rule inside a catalog shares
that same target set — there is nothing to route per rule. Areas that should
light up differently get their own catalog, for example:

- **Common alerts** — most switches, excluding the kids’ rooms
- **Near garage** — Great Room Entry Lights and Great Room Ceiling Lights
- **Bedrooms HVAC** / **Living HVAC** — the non-kid-bedroom switches in each zone
- **Outside office** and **Outside bathroom** — one nearby switch each

The picker lists Zigbee2MQTT group devices and physical Inovelli devices. Pick
one or more groups to combine their memberships and use one native groupcast
per group, or pick individual devices. For each group, Notify Lights joins the
group's real numeric Zigbee ID to Zigbee2MQTT's retained
`zigbee2mqtt/bridge/groups` registry and uses the exact published
`friendly_name`; there is no manually entered topic or naming convention.

If another notification makes member layouts differ, Notify Lights
automatically falls back to rendering those switches individually. Older
non-Zigbee group/area/entity selectors are expanded to physical devices when
opened.

### Notification rules answer “when?”

Every rule has an explicit activation behavior:

| Behavior | Use it for |
|---|---|
| Show while an entity is in a state | Charging, unlocked, door open, heating/cooling, occupied |
| Show for a time when an entity enters a state | Charger ready, package delivered |
| Manual, stays on until turned off | Conditions controlled by an existing automation |
| Manual, turns off after a time | Impulses controlled by an existing automation |

There is no hidden “duration 0 changes the entity type” choice in the UI. Timed
rules ask for a duration; while-active rules do not.

Automatic rules ask for a source entity, then show its main state and current
attributes in plain language. A climate rule can watch hvac_action directly;
there is no need to create an intermediate template sensor. Notify Lights
offers values reported by the chosen property (including enum options when
available), while still allowing a custom value.

The rule form asks only for priority and coverage — how the rule competes with
other rules, and whether it wants the full light bar or a one-pixel bottom
indicator. Where it shows is decided once, for the whole catalog, under
**Edit notification lights**.

### Every rule is a light

Each notification rule gets its own light entity, in the catalog device's
**Configuration** section. That light *is* the rule's appearance: its
brightness, color, and effect are the settings the notification renders with,
so changing them changes what the notification displays everywhere it
displays. They are set on the wall, against the real switch, rather than
guessed at in a form — and they are written straight back into the catalog,
without reloading it.

- Turning one on activates the notification by hand. Turning several on
  stacks them by priority, exactly as automatic activation does.
- Turning one off clears it, including a rule whose source entity is still
  active — an individual notification can be dismissed.
- A rule bound to a source entity follows that source, and re-syncs the next
  time the source changes state.
- A timed rule turns itself off when its duration runs out.
- Effect and speed are one Home Assistant effect name: `blink fast`,
  `chase slow`. Effects with nothing to vary are bare — `solid`, `pulse`,
  `aurora`, `open_close`, `small_to_big`, each a single value in the
  Zigbee2MQTT enum.
- Dragging saturation to zero asks for white, which is off the hue wheel.

Each light is named with its priority first — `085 Fridge ajar` — so the
configuration section reads in priority order and a re-prioritized rule visibly
moves. The priority is display only: it never enters the entity ID, so
changing it breaks no references.

## Tesla example

Create a **Near garage** catalog with these Inovelli devices:

- Great Room Entry Lights
- Great Room Ceiling Lights

Then add two rules inside it:

| Rule | Activation | Source | State | Duration |
|---|---|---|---|---|
| Tesla charging | Show while in state | sensor.tesla_wall_connector_status | charging | While charging |
| Tesla charger ready | Show when state is entered | sensor.tesla_wall_connector_status | ready | 300 seconds |

Both rules inherit the catalog's **Near garage** targets. Charging synchronizes
immediately after a Home Assistant restart. Ready is edge-triggered and
deliberately does not replay merely because Home Assistant starts while the
sensor already says ready.

## Suggested rule layout

The use cases below become a small number of catalogs plus straightforward rules:

| Situation | Catalog | Source-state strategy |
|---|---|---|
| Doors unlocked | Common alerts | One while-state rule per lock, or a template binary sensor aggregating locks |
| Backdoors open | Common alerts | While open |
| Heat / cool | HVAC zone group | Follow hvac_action; low priority; one-pixel indicator |
| Tesla charging / ready | Near garage | While charging; 300 seconds on entering ready |
| On a call | Outside office | While on call |
| Bathroom occupied | Outside bathroom | While occupied |
| Fridge door open | Common alerts | While open |
| Package at door | Common alerts | Timed on entering detected/delivered |
| Garage door | Common alerts | Separate opening, closing, and open rules sharing one source and catalog |

A situation with visually distinct states is intentionally represented by
multiple rules. They share the source and catalog, but each state owns its
appearance and timeout. That keeps priority arbitration and testing simple.

## Dimming notifications at night

Every catalog gets a companion light entity (`light.<catalog>_brightness`)
alongside its notification lights. Unlike those, it is a control, not
configuration. Its on/off, color, and
effect are a read-only mirror of whichever of that catalog's own
notifications is currently highest priority — there's nothing to command
there. Its **brightness** is the opposite: a live ceiling that scales every
notification the catalog activates, wherever it renders, without touching
any rule's own authored brightness.

Lower that entity's brightness by hand, from a scene, or via an automation to
quiet a bedroom catalog at night. Because it behaves like an ordinary light
that turns on and off with real notification activity, it can also be added
to an [Adaptive Lighting](https://github.com/basnijholt/adaptive-lighting)
light group: Adaptive Lighting pushes its computed brightness to the entity
whenever it turns on and periodically while it stays on, so a long-running
notification (Tesla charging, say) actually dims through the evening instead
of freezing at whatever brightness it started with.

Turning the entity off clears every notification currently active for that
catalog and mutes future ones (ceiling zero) until it's turned back on —
the same as turning the switches off by hand. Clearing, rather than just
muting, matters when catalogs overlap on the same switch: a muted-but-still-
active high-priority notification would otherwise keep occupying its
priority slot rendered black, hiding a lower-priority notification from
another catalog that should be visible instead.

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
the smallest applicable clear once state is known. The bottom priority
indicator is always solid.

The full bar can run every animation the switch has: solid, blink, pulse,
chase, falling, rising, aurora, open/close, small-to-big, and siren.
Zigbee2MQTT's single-pixel enum is much shorter, so a rule shown on one LED
degrades: blink falls back to slow or fast (medium uses fast);
chase/falling/rising use the one speed available; open/close and small-to-big
become a pulse; and a siren becomes a slow or fast blink. Siren has no medium
on either transport — medium renders as fast.

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

Manual rules are ordinary lights:

    # Manual, stays on until turned off
    - action: light.turn_on
      target:
        entity_id: light.common_alerts_fridge_ajar

    # Manual, clears itself after the rule's duration
    - action: light.turn_on
      target:
        entity_id: light.common_alerts_package_at_door

Automatic rules need no calling automation. Every rule's light exposes its
description, activation, source, matching state, duration, priority, coverage,
and resolved physical targets as attributes.

## Upgrading to 0.10.0

Every notification rule is now one light entity instead of a switch, a button,
or a binary sensor:

- The switch, button, and binary sensor entities are removed from the entity
  registry on first setup. Automations that called `switch.turn_on` or
  `button.press` on a rule must call `light.turn_on` on its light instead.
- Color, brightness, effect, and speed are no longer asked for in the options
  flow. Existing values carry over untouched and are now edited on each rule's
  light. New rules start blue, solid, medium, full brightness.
- Nothing else about a catalog changes: config version stays at 4, and
  notification slugs, priorities, sources, durations, and targets are
  untouched.

## Upgrading to 0.9.3

One catalog can now combine multiple native Zigbee2MQTT groups. Their members
form the catalog target union, and notifications use one groupcast per selected
group. Groups and individual Inovelli devices remain separate target modes.

## Upgrading to 0.9.2

Native Zigbee2MQTT groups can be selected directly again. Their membership
remains dynamic, and their exact MQTT friendly names are read from
Zigbee2MQTT's retained group registry instead of being typed manually. Choose
one native group or a set of individual Inovelli devices, but not both.

## Upgrading to 0.9.1

The target form now selects physical Inovelli devices instead of Home
Assistant light entities. Opening **Edit Inovelli devices** expands existing
entity, area, exclusion, and group-light selectors to the physical devices
they currently resolve to. Saving replaces those legacy selectors with the
selected device IDs; no startup migration or entity IDs change.

Version 0.9.2 supersedes the manually entered Zigbee2MQTT group field by
selecting the real group device and deriving its transport name.

## Upgrading to 0.9.0

Entries migrate automatically to config version 4, which makes every catalog
a device group with one fixed target set and adds each catalog's brightness
light entity.

- The migration unions every notification's own targets and every reusable
  group it referenced (including groups that had a Zigbee2MQTT group set)
  into the catalog's new root-level **targets**/**exclude**/**Zigbee2MQTT
  group** fields. Nothing is dropped, but nothing is silently split either.
- If a catalog previously routed different notifications to different areas,
  it now targets the union of all of them. Split it into one catalog per
  area afterward, using **Edit Inovelli devices** on the new catalog and each
  original notification's targets as a guide.
- If a catalog referenced more than one reusable group with *different*
  Zigbee2MQTT groups set, the migrated catalog's Zigbee2MQTT group is left
  blank rather than picking one arbitrarily — re-set it per catalog after
  splitting.
- Existing entity unique IDs and notification slugs remain unchanged.

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
