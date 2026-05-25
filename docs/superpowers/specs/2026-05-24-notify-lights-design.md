# Notify Lights — Design

**Date:** 2026-05-24
**Status:** Approved for planning
**Author:** Martin Emde (with Claude)

**Integration name:** Notify Lights
**Repo / HACS slug:** `ha-notify-lights`
**Python package:** `custom_components/notify_lights`

## Summary

Notify Lights is a new Home Assistant custom integration, distributed via HACS, that introduces a brand-neutral status notification system rendered on smart-switch LEDs (Inovelli Blue, Red, and White in v1). Each notification is exposed as a first-class HA entity — a `switch` for stateful notifications, a `button` for momentary ones — so it can be triggered from ordinary HA automations exactly like turning on a light. A pluggable adapter layer translates a generic high-fidelity notification object into the hardware-specific LED commands each switch family understands. Multiple active notifications stack via a shared ordering policy; the per-device adapter decides how many slots its hardware can render and gracefully degrades effects it doesn't support.

## Goals

- "Notifications as entities" — turn on `switch.notify_heating` from any HA automation and the configured switches reflect it.
- Decouple intent (the notification) from rendering (the hardware), like Adaptive Lighting intercepts `light.turn_on`.
- Support multiple Inovelli families on day one (Blue, Red, White) via distinct adapters behind one stable interface.
- High-fidelity notification vocabulary that adapters reduce — Blue gets richer effects, Red/White get sensible fallbacks.
- UI-only configuration, no YAML, no restart to edit.
- New hardware families can be added later as new adapter modules with no changes to the core.

## Non-goals

- Schedule- or condition-based auto-activation — use HA automations.
- Declarative bindings ("when entity X changes state, fire notification Y") — same reason; HA automations already do this.
- Non-LED notification surfaces (TTS, push, mobile, etc.).
- Per-target color/effect overrides on a single notification (one notification = one appearance everywhere it renders).
- Notification templates or inheritance.
- Custom Lovelace card.
- Two-way reflection of physical switch state into notification entities.

## Architecture

```
HA automation ──► switch.notify_heating (on)
                    │
                    ▼
            Notification core
            (definitions, entities)
                    │
                    ▼
            Active-set tracker  ◄── per target: ordered list of active notifications
                    │
                    ▼
            Adapter registry  ──► matches device manufacturer/model
                    │
                    ▼
            Adapter (Blue / Red / White)
                    │
                    ▼
            Z-Wave service calls
```

Four internal layers:

1. **Notification core** — owns notification definitions and entity state. Imports nothing hardware-specific.
2. **Entity layer** — surfaces each notification as `switch.notify_<name>` (stateful) or `button.notify_<name>` (momentary).
3. **Active-set tracker** — per target, maintains the ordered set of currently-active notifications. Recomputed on any activation, deactivation, auto-clear, or config change.
4. **Adapter registry** — adapters register at integration setup, declaring which devices they handle by manufacturer + model glob. The registry picks an adapter per target switch and hands it the full ordered active set on every change.

**Decoupling guarantee:** The notification core never imports from any adapter module. Adapters depend on a small interface module from the core; the core depends on nothing hardware-specific. Adding a brand = adding one adapter module.

### Repo layout

This integration and its spec/plan documents live in their own repo: `~/src/martinemde/ha-notify-lights`. (Distinct from the `magic_climate` convention, where the spec lived in the esphome repo and only the code lived in the sibling. Notify Lights keeps spec, plan, and code together.)

```
ha-notify-lights/
├── docs/superpowers/
│   ├── specs/2026-05-24-notify-lights-design.md   # this file
│   └── plans/                                      # implementation plan(s)
└── custom_components/notify_lights/
    ├── __init__.py
    ├── config_flow.py
    ├── const.py
    ├── notification.py         # Notification dataclass + validation
    ├── active_set.py           # ordering policy (pure, unit-testable)
    ├── entities/
    │   ├── switch.py           # stateful notification entities
    │   └── button.py           # momentary notification entities
    ├── adapter.py              # Adapter interface + registry
    └── adapters/
        ├── inovelli_blue.py
        ├── inovelli_red.py
        └── inovelli_white.py
```

## Notification model

```python
@dataclass
class Notification:
    name: str                    # unique; drives entity id
    color: int | str             # hue 0–360, or one of the named-color set
    brightness: int              # 0–100, default 100
    effect: Effect               # enum
    effect_speed: Speed          # slow | medium | fast, default medium
    duration: int                # seconds. 0 = stateful, >0 = momentary
    priority: int                # default 50
    targets: list[str]           # entity ids, area refs (area_id:*), group refs
```

**Entity platform** is derived at config-entry creation: `duration == 0` → `switch.*`, `duration > 0` → `button.*`. There is no `kind` field; the duration is the kind.

**Effect enum:** `solid`, `blink`, `pulse`, `chase`, `falling`, `rising`, `aurora`.

This is the high-fidelity superset. Each adapter declares which effects it supports natively and provides a fallback table mapping unsupported effects to the closest available. Reductions live in adapters, never the core.

**Named colors** (preset hues, accepted in place of a numeric hue): `red`, `orange`, `yellow`, `green`, `cyan`, `blue`, `purple`, `magenta`, `white`. No separate code path — resolved to canonical hues internally.

**Targets:** at least one is required; an empty target list is a config-flow validation error. Targets may be:

- Specific `switch.*` entity ids
- HA areas (`area_id:<id>` — resolved to member switches at activation time)
- HA `group.*` entities (resolved at activation time)

Area and group membership is re-evaluated every activation, not cached at config time. Adding a switch to a configured area later picks up notifications targeting that area automatically.

**Common priority bands** (advisory, not enforced):

- `10` — background / informational
- `50` — normal (default)
- `90` — alert / urgent

## Active set and ordering

For each target switch, the core maintains an ordered list of currently-active notifications affecting it. Recomputed on every activation, deactivation, auto-clear, or config change.

**Sort key**, applied in order:

1. `priority` (higher first)
2. Momentary before stateful at equal priority — transient items deserve foreground while they're brief
3. Activation timestamp (most recent first)

Implemented as a pure function in `active_set.py` with no HA imports, fully unit-testable. Adapters consume the ordered output; they never compute ordering themselves.

## Adapter interface

```python
class NotificationAdapter:
    manufacturer: str
    model_patterns: list[str]            # glob-matched against device model
    max_concurrent: int                  # device's simultaneous-effect capacity
    supported_effects: set[Effect]
    effect_fallbacks: dict[Effect, Effect]

    def render(self, target: str, active: list[Notification]) -> None:
        """Apply the active set to this target.
        Called whenever the active set for this target changes."""

    def clear(self, target: str) -> None:
        """Reset device LEDs to default. Called on integration unload."""
```

**Selection** happens at notification activation time. The registry inspects each target switch's `device_registry` entry (manufacturer + model) and picks the adapter whose `model_patterns` match. Inovelli Blue takes `active[:7]` and uses multiple LED-bar slots; Red and White take `active[:1]` and render only the top of the ordered list. Effects unsupported by a device flow through that adapter's `effect_fallbacks` before being sent to Z-Wave.

**Registration** is via a `@register_adapter` decorator at module import; adapters in `adapters/` are auto-loaded at integration startup.

**Per-target override:** an optional config setting can force a specific adapter for a given entity id, for when auto-detection picks the wrong one or you want to try an experimental adapter against unfamiliar hardware.

**Unmatched devices:** logged once per target, skipped. Notifications still render to other targets in the same group.

## Config flow

UI only, no YAML.

1. **Add Integration → "Notify Lights"** creates the integration container on first add.
2. **One config entry per notification.** Subsequent adds create individual notifications inside the container, visible as sub-entries on the integration card. Editable via "Configure" without restart.
3. **Targets picker** uses HA's entity selector (`domain: switch`), area selector, and group selector — mixed targets supported.
4. **Color picker** defaults to the named-color dropdown; a "custom hue" toggle reveals a 0–360 slider.
5. **Effect, speed, duration, priority, brightness** are plain form fields with the constraints from the Notification model section.

## Testing

- **`active_set.py`** — pure-Python `pytest` unit tests, no HA imports. Cover priority ties, momentary-vs-stateful preference, recency tie-breaking, add/remove transitions.
- **Adapters** — unit tests for each adapter's `effect_fallbacks` table and slot allocation logic, with fake `Notification` objects and a mocked Z-Wave service call sink. No real hardware required.
- **HA-integrated tests** — `pytest-homeassistant-custom-component` for the entity layer: switch on/off updates the active set, momentary buttons auto-clear after `duration`, config-flow round-trip.
- **Live verification** — manual checklist against real Blue / Red / White hardware: each effect, stacking on Blue, fallbacks on Red/White, area-based target resolution after adding a switch to an area, restart restoration of stateful notifications.

## Edge cases and error handling

- **Target switch unavailable** at activation: log warning, skip that target, render to the rest. Re-render automatically on availability restore.
- **No adapter matches a target device**: warning logged once per target. Skipped; other targets render normally.
- **Notification deleted while active**: cleared from all targets' active sets; affected targets re-render.
- **Empty active set after clear**: adapter receives empty list. Its `render` implementation must restore the device to its default state (LED bar reflects the load's on/off state).
- **HA restart**: stateful notification entity states restored via standard HA state restoration. Momentary notifications do not restore; they are transient by nature.
- **Adapter exceptions during render**: caught at the registry, logged, do not crash other targets' renders or the integration as a whole.

## Tech stack and dependencies

- Python 3.11+
- Home Assistant 2024+ custom-component API
- `pytest` for `active_set.py` and adapter unit tests
- `pytest-homeassistant-custom-component` for HA-integrated tests
- Inovelli Z-Wave devices in v1 (Blue 2-1, Red Series, White Series), via the `zwave_js` integration
- Repo uses `jj` on top of git, matching `magic_climate` conventions

## Open questions deferred to plan

- Exact `zwave_js.set_config_parameter` argument shapes per Inovelli family (lookup during implementation).
- Whether HA's `homeassistant.start` event is the right hook for restoring active sets vs. doing it lazily on first interaction.
- Final HACS metadata (display name, description, documentation URL).
