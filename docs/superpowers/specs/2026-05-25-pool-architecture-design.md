# Pool-Based Notification Architecture

Rearchitect ha-notify-lights so each "notification pool" (target group) is a separate config entry creating its own HA device. Pools own targets; notifications inherit them.

## Data Model

### Pool (config entry data + options)

Stored in `entry.data`:
- `name`: display name (e.g. "Floor 1 Switches")
- `area_id`: optional HA area ID to assign the device to
- `targets`: list of entity IDs (light/switch domains)

Stored in `entry.options`:
- `notifications`: dict keyed by slug, each value contains:
  - `slug`: stable internal ID (generated from initial name, immutable)
  - `display_name`: user-facing name (editable)
  - `color`: named color string or hue int (0-360)
  - `effect`: Effect enum value
  - `effect_speed`: Speed enum value
  - `brightness`: int 0-100
  - `duration`: int seconds (0 = stateful, >0 = momentary)
  - `priority`: int 0-100

### Notification dataclass

Remove `targets` field. When activating, the pool provides its target list to the coordinator.

## Config Entry & Device Lifecycle

### Config flow (adding a pool)

1. Step "user": Enter pool name, optionally pick area (standard HA naming UX)
2. Step "targets": Select target entities (entity picker, light/switch domain, multi-select, additive)
3. Creates entry with `data={"name": ..., "area_id": ..., "targets": [...]}`, `options={"notifications": {}}`

No unique_id constraint — multiple pools are expected.

### Device creation

Each config entry registers one device:
- `identifiers={(DOMAIN, entry.entry_id)}`
- `name` = pool name
- Area assigned via device registry using `area_id` from data

### Options flow (gear icon)

Menu with four options:
- **Basics**: edit name, area, target entities
- **Add Notification**: form with name, color, effect, speed, brightness, duration, priority
- **Modify Notification**: dropdown to pick notification → pre-filled edit form (all fields editable, name changes display_name only, slug stays)
- **Delete Notification**: dropdown to pick notification → removes it

### Entry lifecycle

- On load: create/get global coordinator, register pool's active notifications
- On unload: deregister all notifications from this pool; if last pool, coordinator remains (stateless when empty)
- On options update: reload entry (existing pattern via update listener)

## Global Coordinator

### Singleton

- Created when first pool entry loads: `hass.data[DOMAIN]["coordinator"]`
- Shared across all pool config entries
- Never destroyed while any entry is loaded

### Per-switch notification stack

```python
_stacks: dict[str, list[StackEntry]]
# key = target entity_id (physical switch)
# StackEntry = (notification: Notification, pool_entry_id: str, activated_at: float)
```

Operations:
- `activate(notification, targets, pool_entry_id)`: push to each target's stack, re-render
- `deactivate(notification, targets, pool_entry_id)`: remove from each target's stack, re-render
- On re-render: sort stack by priority desc, then activated_at desc for ties; pass full stack to adapter

### Target resolution

At render time for each entity_id in a stack:
1. Resolve entity_id → entity registry entry
2. Get device from entity's device_id
3. Match adapter from device manufacturer/model
4. Skip silently if any step fails (incompatible target)

### Adapter interface

Change from `render(friendly_name, active_set)` to:

```python
async def render(self, friendly_name: str, stack: list[Notification]) -> None
```

The coordinator internally tracks `(notification, pool_entry_id, activated_at)` per stack entry for bookkeeping, but the adapter receives only the sorted `list[Notification]` (priority desc, then activated_at desc). Adapter decides what to display:
- Today: render top notification, clear if stack is empty
- Future: multi-pixel rendering from multiple stack entries

## Entities

### Per-pool device entities

Each notification in a pool becomes an entity under that pool's device:
- **Stateful (duration=0):** `SwitchEntity` — toggle on/off
- **Momentary (duration>0):** `ButtonEntity` — press to fire, auto-clears

### Entity identity

- `unique_id`: `notify_lights_{entry_id}_{notification_slug}`
- Display name: notification's `display_name`
- `device_info`: ties to pool device via `identifiers={(DOMAIN, entry_id)}`

### Entity behavior

- Switch on → `coordinator.activate(notification, pool_targets, entry_id)`
- Switch off → `coordinator.deactivate(notification, pool_targets, entry_id)`
- Button press → activate with auto-deactivate scheduled after duration seconds

## Migration

Existing single-entry installations will need migration. Strategy:
- Detect old-format entry (has `options.notifications` with per-notification `targets`)
- For each notification, collect unique target sets
- Create new pool entries grouped by target set (or one pool per notification if targets differ)
- Remove old entry

This can be a one-time migration in `async_migrate_entry` or handled manually (user reconfigures). Given the integration is pre-1.0 and likely has few users, manual reconfiguration is acceptable.

## Testing Strategy

- Unit tests for coordinator stack operations (activate, deactivate, priority resolution)
- Unit tests for config flow (create pool, options CRUD)
- Integration tests for multi-pool scenarios (same switch in two pools, priority resolution)
- Adapter tests updated for new `render(name, stack)` signature
