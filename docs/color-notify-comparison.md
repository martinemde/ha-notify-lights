# Lessons from ha-color-notify

Comparison with [cobryan05/ha-color-notify](https://github.com/cobryan05/ha-color-notify)
and features worth adopting in notify-lights.

## Architecture Validation

Our adapter-based approach is fundamentally stronger for the hardware-native LED
use case. Color-notify wraps HA light entities and does software animation via
rapid `light.turn_on` calls — it can't access hardware effects at all. Their
Matter issue (#3) confirms this limitation: they can't support Inovelli Matter
switches because the LED effect is exposed as a Select entity, not a light
effect. Our adapter pattern handles this naturally — a Matter adapter just calls
whatever service is needed.

We should stay the course on: adapter registry, direct MQTT/protocol access,
hardware-native effects, priority-based active set in the coordinator.

---

## Features to Adopt

### 1. State Restoration (RestoreEntity)

**What they do:** Their light entity extends `RestoreEntity` so active
notifications survive HA restarts. On startup, it reads the last known state
and re-activates notifications.

**Why it matters:** Already noted in next-steps.md as a must-fix. Without this,
every HA restart silently drops active notifications while the switch LEDs may
still be showing the last effect (they persist on hardware until cleared).

**Implementation:**
- Add `RestoreEntity` mixin to the Switch entity
- In `async_added_to_hass`, call `self.async_get_last_state()` and
  `self.async_get_last_extra_data()` to recover on/off state
- If restored as ON, call `coordinator.async_activate(notification)` to
  re-render on the hardware
- Store the activated timestamp in extra state attributes so priority
  tie-breaking (FIFO) is preserved across restarts

### 2. Peek Behavior (Temporary Priority Boost)

**What they do:** When a notification first activates, it gets a temporary
priority boost (peek) that overrides even higher-priority notifications for a
configured duration. After the peek window, normal priority sorting resumes.

**Why it matters:** Draws immediate attention to new events. If you have a
persistent "door unlocked" notification at priority 50, and a "motion detected"
at priority 30 fires, peek lets the motion notification briefly show before
the door-unlocked notification resumes.

**Implementation:**
- Add optional `peek_duration` field to Notification (seconds, 0=disabled)
- In `ActiveEntry`, track `activated_at` (already done) and compute an
  effective priority: if `now - activated_at < peek_duration`, use
  `MAX_PRIORITY` (or a configurable boost); otherwise use normal priority
- `compute_active_set` already sorts by priority — just needs to use
  effective priority at sort time
- After peek expires, the coordinator needs to re-render. Options:
  - Timer callback per-target that fires after the peek window
  - Lazy re-evaluation: next activate/deactivate call re-sorts correctly
  (lazy is simpler; timer is more correct for single-notification scenarios)

### 3. Notification Expiration Delay

**What they do:** Configurable delay before a deactivated notification is
removed from the display. If you turn a notification off, it stays visible
for N seconds before clearing. If it's re-activated within that window,
it never disappears.

**Why it matters:** Prevents flicker for notifications driven by sensors that
toggle rapidly (e.g., motion sensor going inactive for 2 seconds between
detections).

**Implementation:**
- Add optional `clear_delay` field to Notification (seconds, 0=immediate)
- In `async_deactivate`, instead of immediately removing from active set,
  mark the entry as "pending removal" with a deadline
- Schedule a callback via `async_call_later` to actually remove it
- If `async_activate` is called for the same notification before the deadline,
  cancel the pending removal
- This keeps the adapter from receiving rapid render/clear/render cycles

### 4. Config Flow: Edit Existing Notifications

**What they do:** Full CRUD in options flow — add, copy, modify, delete
notifications. Users pick from a list of existing notifications to edit.

**Why it matters:** Currently we only have add/remove. Editing means deleting
and recreating. This is clunky for adjusting a color or priority.

**Implementation:**
- Options flow menu: Add Notification / Edit Notification / Remove Notification
- Edit step: present a select list of existing notification names
- Pre-populate form fields with current values from the selected notification
- On submit, update the notification in `entry.options["notifications"]` in
  place (same key) and trigger reload
- Copy: same as edit but save under a new name (user provides new name)

### 5. Notification Grouping / Pools

**What they do:** Notifications live in named pools. A light subscribes to
one or more pools. This separates "what notifications exist" from "which
devices show them."

**Why it matters:** We currently embed targets directly in each notification.
Pools would let you define a "security" pool with 5 notifications and subscribe
multiple switches to it without duplicating target lists.

**Evaluation:** This is a bigger architectural change and may not be worth it
yet. Our current model (targets on the notification) is simpler and the
coordinator already handles per-target rendering. Revisit if users need to
manage many notifications across many devices.

**If adopted:**
- Pool = a config entry with type "pool", containing notification definitions
- Device subscription = a config entry with type "device", referencing pools
- Coordinator resolves pool memberships at activation time
- Breaking change to config schema — would need migration

---

## Features to Skip

### Software Animation / Color Sequences

Color-notify's pattern DSL (JSON arrays with loop markers and delays) makes
sense for dumb lights but adds no value for hardware with built-in effects.
Our hardware already has solid, blink, pulse, chase, aurora, falling, rising.

### Protocol Abstraction via HA Service Layer

Their "works with any HA light" approach sacrifices hardware-native features.
We explicitly reject this tradeoff — the whole point is using the switch's
built-in LED controller.

### Virtual Wrapper Entities

They create a wrapper `light.*` entity that sits between the user and the real
light. This adds complexity and forces exclusive control. Our switch/button
entities exist alongside the device and only touch the notification LED, not
the main light function.

---

## Priority Order for Implementation

1. **State restoration** — Required for basic reliability
2. **Edit notifications in options flow** — QoL, low effort
3. **Clear delay** — Prevents sensor flicker, moderate effort
4. **Peek behavior** — Nice UX, moderate effort, needs timer management
5. **Pools/grouping** — Evaluate after the above are done
