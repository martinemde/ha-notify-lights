# Notify Lights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Home Assistant custom integration that exposes LED notifications as entities (switch/button), targeting Inovelli Blue Series via Zigbee2MQTT as the first adapter.

**Architecture:** Notifications are dataclasses stored as HA config sub-entries. Each notification becomes a `switch` (stateful, duration=0) or `button` (momentary, duration>0) entity. On activation, the active-set tracker computes per-target ordering by priority/recency, then the adapter registry dispatches to the matched adapter, which publishes MQTT payloads to Zigbee2MQTT. The adapter layer is pluggable — Blue/Z2M is the first; Z-Wave adapters come later.

**Tech Stack:** Python 3.11+, Home Assistant 2024+ custom component API, pytest, pytest-homeassistant-custom-component, Zigbee2MQTT via `mqtt.publish`

**Spec:** `docs/superpowers/specs/2026-05-24-notify-lights-design.md`

---

## Key Design Decisions

### Zigbee2MQTT as first adapter (not Z-Wave JS)
The Blue Series adapter publishes JSON to `zigbee2mqtt/{device_name}/set` via HA's `mqtt.publish` service. This avoids Z-Wave parameter encoding complexity and gives us the richest effect set.

### Effect + Speed → Z2M effect string mapping
Our `Effect` enum stays small (solid, blink, pulse, chase, falling, rising, aurora). The adapter combines `effect` + `effect_speed` to select the Z2M effect string:

| Effect | Slow | Medium | Fast |
|--------|------|--------|------|
| solid | solid | solid | solid |
| blink | slow_blink | medium_blink | fast_blink |
| pulse | pulse | pulse | pulse |
| chase | slow_chase | chase | fast_chase |
| falling | slow_falling | medium_falling | fast_falling |
| rising | slow_rising | medium_rising | fast_rising |
| aurora | aurora | aurora | aurora |

### Color conversion
Spec hue 0-360 → Z2M 0-255: `z2m_color = round(hue * 255 / 360)`. Named colors resolve to hues first, then convert.

Z2M named color reference: Red(0)=1, Orange(21)=21, Yellow(42)=42, Green(85)=85, Cyan(127)=127, Blue(170)=170, Purple(195)=195, Pink(234)=234, White=255.

### Duration encoding
Spec uses seconds. Z2M encoding: 1-60 = seconds, 61-120 = minutes (value-60), 121-254 = hours (value-120), 255 = indefinite. Adapter converts from raw seconds.

### Multi-LED stacking (deferred)
Blue has 7 individually addressable LEDs via `individual_led_effect`, but v1 renders only the top-priority notification using full-bar `led_effect`. The adapter interface accepts the full ordered active set, so stacking can be added later without changing the core or entity layer.

### Target entity resolution
Targets can be entity IDs, `area_id:*` refs, or `group.*` refs. The adapter needs the Z2M device friendly name for the MQTT topic. This is derived from the HA device registry — Z2M devices have identifiers like `("mqtt", "0x...")` and a `name` field that corresponds to the Z2M friendly name.

### Config sub-entries
Each notification is a sub-entry of the main integration config entry, per the spec. HA 2024.x supports this via `ConfigSubEntry`.

---

## File Structure

```
custom_components/notify_lights/
├── __init__.py              # Integration setup, adapter loading
├── manifest.json            # HACS/HA metadata
├── const.py                 # Domain, effect/speed/color enums, defaults
├── strings.json             # UI strings for config flow
├── notification.py          # Notification dataclass + validation
├── active_set.py            # Ordering policy (pure, no HA imports)
├── adapter.py               # Adapter ABC + registry
├── adapters/
│   ├── __init__.py
│   └── inovelli_blue_z2m.py # Blue Series via Zigbee2MQTT
├── config_flow.py           # Config flow + options flow
├── switch.py                # Stateful notification entities
└── button.py                # Momentary notification entities
tests/
├── conftest.py
├── test_notification.py
├── test_active_set.py
├── test_adapter_registry.py
├── test_inovelli_blue_z2m.py
├── test_config_flow.py
├── test_switch.py
└── test_button.py
```

Note: entities live at `switch.py` / `button.py` (top-level, not in `entities/` subdirectory) — HA discovers entity platforms by looking for `{domain}/{platform}.py` and the platform name must match the HA domain (`switch`, `button`).

---

## Task 1: Project Scaffolding

**Files:**
- Create: `custom_components/notify_lights/manifest.json`
- Create: `custom_components/notify_lights/const.py`
- Create: `custom_components/notify_lights/__init__.py` (minimal stub)
- Create: `custom_components/notify_lights/strings.json` (skeleton)
- Create: `README.md`

- [ ] **Step 1: Create manifest.json**

```json
{
  "domain": "notify_lights",
  "name": "Notify Lights",
  "codeowners": ["@martinemde"],
  "config_flow": true,
  "dependencies": ["mqtt"],
  "documentation": "https://github.com/martinemde/ha-notify-lights",
  "iot_class": "local_push",
  "issue_tracker": "https://github.com/martinemde/ha-notify-lights/issues",
  "requirements": [],
  "version": "0.1.0"
}
```

- [ ] **Step 2: Create const.py with enums and constants**

```python
from enum import StrEnum

DOMAIN = "notify_lights"

class Effect(StrEnum):
    SOLID = "solid"
    BLINK = "blink"
    PULSE = "pulse"
    CHASE = "chase"
    FALLING = "falling"
    RISING = "rising"
    AURORA = "aurora"

class Speed(StrEnum):
    SLOW = "slow"
    MEDIUM = "medium"
    FAST = "fast"

NAMED_COLORS: dict[str, int] = {
    "red": 0,
    "orange": 21,
    "yellow": 60,
    "green": 120,
    "cyan": 180,
    "blue": 240,
    "purple": 270,
    "magenta": 300,
    "white": 360,
}

DEFAULT_BRIGHTNESS = 100
DEFAULT_SPEED = Speed.MEDIUM
DEFAULT_PRIORITY = 50
```

- [ ] **Step 3: Create minimal __init__.py stub**

```python
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True
```

- [ ] **Step 4: Create strings.json skeleton**

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Notify Lights",
        "description": "Set up Notify Lights to control LED notifications on your smart switches."
      }
    }
  }
}
```

- [ ] **Step 5: Create README.md with reference links**

Include the Inovelli Z2M notification references:
- https://help.inovelli.com/en/articles/11357013-blue-series-led-notifications-with-mqtt-publish-zigbee2mqtt
- https://help.inovelli.com/en/articles/11357275-blue-series-single-led-notifications-with-mqtt-publish-zigbee2mqtt
- https://help.inovelli.com/en/articles/12933821-blue-series-led-notifications-home-assistant-zha
- https://www.zigbee2mqtt.io/devices/VZM31-SN.html

- [ ] **Step 6: Commit**

```
Add project scaffolding for Notify Lights integration
```

---

## Task 2: Notification Model

**Files:**
- Create: `custom_components/notify_lights/notification.py`
- Create: `tests/test_notification.py`

- [ ] **Step 1: Write failing tests for Notification dataclass**

Test cases:
- Create notification with all fields → valid
- Create notification with named color → resolves to hue
- Create notification with numeric hue → stored as-is
- Hue out of range (< 0 or > 360) → raises ValueError
- Brightness out of range → raises ValueError
- Priority out of range → raises ValueError
- Empty targets list → raises ValueError
- Duration 0 → `is_stateful` returns True
- Duration > 0 → `is_momentary` returns True

```python
import pytest
from custom_components.notify_lights.notification import Notification
from custom_components.notify_lights.const import Effect, Speed

def test_create_notification_with_all_fields():
    n = Notification(
        name="heating",
        color=120,
        brightness=80,
        effect=Effect.PULSE,
        effect_speed=Speed.FAST,
        duration=0,
        priority=50,
        targets=["light.living_room"],
    )
    assert n.name == "heating"
    assert n.color == 120
    assert n.brightness == 80

def test_named_color_resolves_to_hue():
    n = Notification(
        name="test",
        color="blue",
        brightness=100,
        effect=Effect.SOLID,
        effect_speed=Speed.MEDIUM,
        duration=0,
        priority=50,
        targets=["light.living_room"],
    )
    assert n.color == 240

def test_hue_out_of_range_raises():
    with pytest.raises(ValueError):
        Notification(
            name="test", color=400, brightness=100,
            effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
            duration=0, priority=50, targets=["light.lr"],
        )

def test_empty_targets_raises():
    with pytest.raises(ValueError):
        Notification(
            name="test", color=0, brightness=100,
            effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
            duration=0, priority=50, targets=[],
        )

def test_stateful_when_duration_zero():
    n = Notification(
        name="test", color=0, brightness=100,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=0, priority=50, targets=["light.lr"],
    )
    assert n.is_stateful
    assert not n.is_momentary

def test_momentary_when_duration_positive():
    n = Notification(
        name="test", color=0, brightness=100,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=10, priority=50, targets=["light.lr"],
    )
    assert n.is_momentary
    assert not n.is_stateful
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_notification.py -v`

- [ ] **Step 3: Implement Notification dataclass**

```python
from __future__ import annotations
from dataclasses import dataclass
from .const import Effect, Speed, NAMED_COLORS

@dataclass(frozen=True)
class Notification:
    name: str
    color: int | str
    brightness: int
    effect: Effect
    effect_speed: Speed
    duration: int
    priority: int
    targets: list[str]

    def __post_init__(self):
        color = self.color
        if isinstance(color, str):
            resolved = NAMED_COLORS.get(color.lower())
            if resolved is None:
                raise ValueError(f"Unknown color name: {color}")
            object.__setattr__(self, "color", resolved)
            color = resolved
        if not 0 <= color <= 360:
            raise ValueError(f"Color hue must be 0-360, got {color}")
        if not 0 <= self.brightness <= 100:
            raise ValueError(f"Brightness must be 0-100, got {self.brightness}")
        if not 0 <= self.priority <= 100:
            raise ValueError(f"Priority must be 0-100, got {self.priority}")
        if not self.targets:
            raise ValueError("At least one target is required")

    @property
    def is_stateful(self) -> bool:
        return self.duration == 0

    @property
    def is_momentary(self) -> bool:
        return self.duration > 0
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_notification.py -v`

- [ ] **Step 5: Commit**

```
Add Notification dataclass with validation
```

---

## Task 3: Active Set Tracker

**Files:**
- Create: `custom_components/notify_lights/active_set.py`
- Create: `tests/test_active_set.py`

Pure Python, no HA imports. The active set is a per-target ordered list of active notifications.

- [ ] **Step 1: Write failing tests**

Test cases:
- Single notification → returns it
- Higher priority first
- Equal priority: momentary before stateful
- Equal priority and kind: most recently activated first
- Add/remove recomputes order
- Empty set → empty list

```python
from custom_components.notify_lights.active_set import compute_active_set
from custom_components.notify_lights.notification import Notification
from custom_components.notify_lights.const import Effect, Speed

def _notif(name, priority=50, duration=0, activated_at=0.0):
    return (
        Notification(
            name=name, color=0, brightness=100,
            effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
            duration=duration, priority=priority,
            targets=["light.lr"],
        ),
        activated_at,
    )

def test_single_notification():
    items = [_notif("a")]
    result = compute_active_set(items)
    assert [n.name for n, _ in result] == ["a"]

def test_higher_priority_first():
    items = [_notif("low", priority=10), _notif("high", priority=90)]
    result = compute_active_set(items)
    assert [n.name for n, _ in result] == ["high", "low"]

def test_momentary_before_stateful_at_equal_priority():
    items = [
        _notif("stateful", duration=0),
        _notif("momentary", duration=5),
    ]
    result = compute_active_set(items)
    assert [n.name for n, _ in result] == ["momentary", "stateful"]

def test_most_recent_first_at_equal_priority_and_kind():
    items = [
        _notif("old", activated_at=1.0),
        _notif("new", activated_at=2.0),
    ]
    result = compute_active_set(items)
    assert [n.name for n, _ in result] == ["new", "old"]

def test_empty_set():
    assert compute_active_set([]) == []
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_active_set.py -v`

- [ ] **Step 3: Implement compute_active_set**

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .notification import Notification

type ActiveEntry = tuple[Notification, float]

def compute_active_set(entries: list[ActiveEntry]) -> list[ActiveEntry]:
    return sorted(entries, key=_sort_key)

def _sort_key(entry: ActiveEntry) -> tuple[int, int, float]:
    notification, activated_at = entry
    return (
        -notification.priority,
        0 if notification.is_momentary else 1,
        -activated_at,
    )
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_active_set.py -v`

- [ ] **Step 5: Commit**

```
Add active set tracker with priority ordering
```

---

## Task 4: Adapter Interface and Registry

**Files:**
- Create: `custom_components/notify_lights/adapter.py`
- Create: `tests/test_adapter_registry.py`

- [ ] **Step 1: Write failing tests for adapter registry**

Test cases:
- Register an adapter, look up by manufacturer+model → returns it
- Model glob matching works (e.g., `VZM31*`)
- No match → returns None
- Multiple adapters, correct one selected

```python
from custom_components.notify_lights.adapter import (
    AdapterRegistry,
    NotificationAdapter,
)

class FakeAdapter(NotificationAdapter):
    manufacturer = "Inovelli"
    model_patterns = ["VZM31*"]
    max_concurrent = 7
    supported_effects = set()
    effect_fallbacks = {}

    async def render(self, target, active):
        pass

    async def clear(self, target):
        pass

def test_register_and_lookup():
    registry = AdapterRegistry()
    adapter = FakeAdapter()
    registry.register(adapter)
    assert registry.get_adapter("Inovelli", "VZM31-SN") is adapter

def test_no_match_returns_none():
    registry = AdapterRegistry()
    assert registry.get_adapter("Unknown", "XYZ") is None

def test_glob_matching():
    registry = AdapterRegistry()
    adapter = FakeAdapter()
    registry.register(adapter)
    assert registry.get_adapter("Inovelli", "VZM31-SN v2.18") is adapter
    assert registry.get_adapter("Inovelli", "VZM35-SN") is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_adapter_registry.py -v`

- [ ] **Step 3: Implement adapter ABC and registry**

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from fnmatch import fnmatch
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .active_set import ActiveEntry
    from .const import Effect

class NotificationAdapter(ABC):
    manufacturer: str
    model_patterns: list[str]
    max_concurrent: int
    supported_effects: set[Effect]
    effect_fallbacks: dict[Effect, Effect]

    @abstractmethod
    async def render(self, target: str, active: list[ActiveEntry]) -> None: ...

    @abstractmethod
    async def clear(self, target: str) -> None: ...

class AdapterRegistry:
    def __init__(self):
        self._adapters: list[NotificationAdapter] = []

    def register(self, adapter: NotificationAdapter) -> None:
        self._adapters.append(adapter)

    def get_adapter(self, manufacturer: str, model: str) -> NotificationAdapter | None:
        for adapter in self._adapters:
            if adapter.manufacturer != manufacturer:
                continue
            if any(fnmatch(model, pat) for pat in adapter.model_patterns):
                return adapter
        return None
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_adapter_registry.py -v`

- [ ] **Step 5: Commit**

```
Add adapter interface and registry with glob matching
```

---

## Task 5: Inovelli Blue Z2M Adapter

**Files:**
- Create: `custom_components/notify_lights/adapters/__init__.py`
- Create: `custom_components/notify_lights/adapters/inovelli_blue_z2m.py`
- Create: `tests/test_inovelli_blue_z2m.py`

This is the core hardware adapter. It converts notifications to MQTT payloads and publishes them via `mqtt.publish`.

### Z2M Technical Reference

**MQTT topic:** `zigbee2mqtt/{friendly_name}/set`

**Full-bar payload:** `{"led_effect": {"effect": "...", "color": 0-255, "level": 0-100, "duration": 1-255}}`

**Per-LED payload:** `{"individual_led_effect": {"led": 1-7, "effect": "...", "color": 0-255, "level": 0-100, "duration": 1-255}}`

**Duration encoding:** 1-60=seconds, 61-120=minutes(value-60), 121-254=hours(value-120), 255=indefinite

**Color:** 0-255 hue wheel. value/255*360=degrees. 255=white.

**Full-bar effects:** off, solid, fast_blink, slow_blink, pulse, chase, open_close, small_to_big, aurora, slow_falling, medium_falling, fast_falling, slow_rising, medium_rising, fast_rising, medium_blink, slow_chase, fast_chase, fast_siren, slow_siren, clear_effect

**Per-LED effects:** off, solid, fast_blink, slow_blink, pulse, chase, falling, rising, aurora, clear_effect

- [ ] **Step 1: Write failing tests for color/duration/effect conversion helpers**

```python
from custom_components.notify_lights.adapters.inovelli_blue_z2m import (
    hue_to_z2m_color,
    seconds_to_z2m_duration,
    effect_to_z2m_string,
)
from custom_components.notify_lights.const import Effect, Speed

def test_hue_to_z2m_color():
    assert hue_to_z2m_color(0) == 0
    assert hue_to_z2m_color(120) == 85
    assert hue_to_z2m_color(240) == 170
    assert hue_to_z2m_color(360) == 255

def test_seconds_to_z2m_duration():
    assert seconds_to_z2m_duration(0) == 255  # indefinite for stateful
    assert seconds_to_z2m_duration(30) == 30  # direct seconds
    assert seconds_to_z2m_duration(60) == 60
    assert seconds_to_z2m_duration(120) == 62  # 2 minutes → 60 + 2
    assert seconds_to_z2m_duration(3600) == 121  # 1 hour → 120 + 1
    assert seconds_to_z2m_duration(86400) == 144  # 24 hours → 120 + 24

def test_effect_to_z2m_string():
    assert effect_to_z2m_string(Effect.SOLID, Speed.MEDIUM) == "solid"
    assert effect_to_z2m_string(Effect.BLINK, Speed.SLOW) == "slow_blink"
    assert effect_to_z2m_string(Effect.BLINK, Speed.MEDIUM) == "medium_blink"
    assert effect_to_z2m_string(Effect.BLINK, Speed.FAST) == "fast_blink"
    assert effect_to_z2m_string(Effect.CHASE, Speed.SLOW) == "slow_chase"
    assert effect_to_z2m_string(Effect.CHASE, Speed.MEDIUM) == "chase"
    assert effect_to_z2m_string(Effect.CHASE, Speed.FAST) == "fast_chase"
    assert effect_to_z2m_string(Effect.FALLING, Speed.FAST) == "fast_falling"
    assert effect_to_z2m_string(Effect.AURORA, Speed.FAST) == "aurora"
```

- [ ] **Step 2: Run tests, verify they fail**

- [ ] **Step 3: Implement conversion helpers**

```python
from ..const import Effect, Speed

Z2M_EFFECT_MAP: dict[tuple[Effect, Speed], str] = {
    (Effect.SOLID, Speed.SLOW): "solid",
    (Effect.SOLID, Speed.MEDIUM): "solid",
    (Effect.SOLID, Speed.FAST): "solid",
    (Effect.BLINK, Speed.SLOW): "slow_blink",
    (Effect.BLINK, Speed.MEDIUM): "medium_blink",
    (Effect.BLINK, Speed.FAST): "fast_blink",
    (Effect.PULSE, Speed.SLOW): "pulse",
    (Effect.PULSE, Speed.MEDIUM): "pulse",
    (Effect.PULSE, Speed.FAST): "pulse",
    (Effect.CHASE, Speed.SLOW): "slow_chase",
    (Effect.CHASE, Speed.MEDIUM): "chase",
    (Effect.CHASE, Speed.FAST): "fast_chase",
    (Effect.FALLING, Speed.SLOW): "slow_falling",
    (Effect.FALLING, Speed.MEDIUM): "medium_falling",
    (Effect.FALLING, Speed.FAST): "fast_falling",
    (Effect.RISING, Speed.SLOW): "slow_rising",
    (Effect.RISING, Speed.MEDIUM): "medium_rising",
    (Effect.RISING, Speed.FAST): "fast_rising",
    (Effect.AURORA, Speed.SLOW): "aurora",
    (Effect.AURORA, Speed.MEDIUM): "aurora",
    (Effect.AURORA, Speed.FAST): "aurora",
}

def hue_to_z2m_color(hue: int) -> int:
    return round(hue * 255 / 360)

def seconds_to_z2m_duration(seconds: int) -> int:
    if seconds == 0:
        return 255  # indefinite
    if seconds <= 60:
        return seconds
    minutes = seconds // 60
    if minutes <= 60:
        return 60 + minutes
    hours = seconds // 3600
    return min(120 + hours, 254)

def effect_to_z2m_string(effect: Effect, speed: Speed) -> str:
    return Z2M_EFFECT_MAP[(effect, speed)]
```

- [ ] **Step 4: Run tests, verify they pass**

- [ ] **Step 5: Write failing tests for MQTT payload building and render**

Test the adapter's `render` method builds correct payloads and calls `mqtt.publish`. Use a mock for `hass.services.async_call`.

```python
from unittest.mock import AsyncMock, MagicMock
from custom_components.notify_lights.adapters.inovelli_blue_z2m import InovelliBluZ2MAdapter
from custom_components.notify_lights.notification import Notification
from custom_components.notify_lights.const import Effect, Speed

def _make_notif(name="test", color=0, effect=Effect.SOLID, speed=Speed.MEDIUM,
                duration=0, priority=50):
    return Notification(
        name=name, color=color, brightness=100,
        effect=effect, effect_speed=speed,
        duration=duration, priority=priority,
        targets=["light.lr"],
    )

async def test_render_single_notification_uses_full_bar():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBluZ2MAdapter(hass)
    active = [(_make_notif(color=120, effect=Effect.PULSE), 1.0)]

    await adapter.render("inovelli_dimmer", active)

    hass.services.async_call.assert_called_once()
    call = hass.services.async_call.call_args
    assert call[0][0] == "mqtt"
    assert call[0][1] == "publish"
    payload = call[1]["service_data"] if "service_data" in call[1] else call[0][2]
    assert payload["topic"] == "zigbee2mqtt/inovelli_dimmer/set"

async def test_render_multiple_uses_top_priority_only():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBluZ2MAdapter(hass)
    active = [
        (_make_notif("high", priority=90), 1.0),
        (_make_notif("low", priority=10, color=120), 2.0),
    ]

    await adapter.render("inovelli_dimmer", active)

    # v1: only top-priority notification rendered on full bar
    hass.services.async_call.assert_called_once()

async def test_clear_sends_clear_effect():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    adapter = InovelliBluZ2MAdapter(hass)

    await adapter.clear("inovelli_dimmer")

    hass.services.async_call.assert_called_once()
```

- [ ] **Step 6: Run tests, verify they fail**

- [ ] **Step 7: Implement InovelliBlueZ2MAdapter**

The adapter takes `hass` in its constructor and publishes via `hass.services.async_call("mqtt", "publish", ...)`.

Key logic:
- Render top-priority notification using full-bar `led_effect` (v1 — individual LED stacking deferred)
- `clear` sends `{"led_effect": {"effect": "clear_effect"}}`

- [ ] **Step 8: Run tests, verify they pass**

- [ ] **Step 9: Commit**

```
Add Inovelli Blue Z2M adapter with MQTT payload generation
```

---

## Task 6: Integration Coordinator and Setup

**Files:**
- Modify: `custom_components/notify_lights/__init__.py`
- Create: `tests/conftest.py`

Wire up the adapter registry, active-set tracking per target, and entity platform forwarding. This is the central coordinator that entities call into when activated/deactivated.

- [ ] **Step 1: Write failing tests for the coordinator**

Test that the coordinator:
- Tracks active notifications per target
- Recomputes active set and calls adapter.render on activate/deactivate
- Resolves area/group targets to entity IDs
- Handles adapter lookup failures gracefully (logs, skips)

- [ ] **Step 2: Run tests, verify they fail**

- [ ] **Step 3: Implement NotifyLightsCoordinator**

The coordinator lives in `__init__.py` and is stored in `hass.data[DOMAIN]`. It holds:
- `AdapterRegistry` (with loaded adapters)
- Per-target active sets: `dict[str, list[ActiveEntry]]`
- Methods: `async_activate(notification)`, `async_deactivate(notification)`, `async_render_target(target_entity_id)`

`async_render_target` does:
1. Look up device from entity registry → device registry
2. Get adapter from registry using manufacturer/model
3. Get Z2M friendly name from device name
4. Call `adapter.render(friendly_name, active_set)`

- [ ] **Step 4: Run tests, verify they pass**

- [ ] **Step 5: Update __init__.py with async_setup_entry**

`async_setup_entry`:
1. Create coordinator, store in `hass.data[DOMAIN]`
2. Register adapters (import and instantiate InovelliBlueZ2MAdapter)
3. Forward entry setup to `switch` and `button` platforms

- [ ] **Step 6: Commit**

```
Add coordinator with active set tracking and adapter dispatch
```

---

## Task 7: Config Flow

**Files:**
- Create: `custom_components/notify_lights/config_flow.py`
- Modify: `custom_components/notify_lights/strings.json`
- Create: `tests/test_config_flow.py`

Two-phase flow:
1. First add → creates the integration container (main config entry, no data)
2. Subsequent adds → each creates a notification as a sub-entry with name, color, effect, speed, duration, priority, targets

- [ ] **Step 1: Write failing tests for config flow**

Test the initial setup flow and notification sub-entry creation. Use `pytest-homeassistant-custom-component` fixtures.

- [ ] **Step 2: Run tests, verify they fail**

- [ ] **Step 3: Implement config_flow.py**

ConfigFlow with:
- `async_step_user` → creates the main entry (one-time)
- Sub-entry flow for adding notifications with fields: name, color (named dropdown + custom hue), effect, speed, duration, priority, brightness, targets (entity selector for switch/light domains + area selector)

- [ ] **Step 4: Update strings.json with all flow step labels**

- [ ] **Step 5: Run tests, verify they pass**

- [ ] **Step 6: Commit**

```
Add config flow for integration setup and notification creation
```

---

## Task 8: Switch Entity (Stateful Notifications)

**Files:**
- Create: `custom_components/notify_lights/switch.py`
- Create: `tests/test_switch.py`

- [ ] **Step 1: Write failing tests**

Test:
- Entity created for duration=0 notifications
- `turn_on` activates the notification via coordinator
- `turn_off` deactivates via coordinator
- State restored on HA restart (via RestoreEntity)

- [ ] **Step 2: Run tests, verify they fail**

- [ ] **Step 3: Implement NotificationSwitch entity**

Extends `SwitchEntity` and `RestoreEntity`. On `turn_on`, calls `coordinator.async_activate(notification)`. On `turn_off`, calls `coordinator.async_deactivate(notification)`.

Entity ID: `switch.notify_{name}` (derived from notification name).

- [ ] **Step 4: Run tests, verify they pass**

- [ ] **Step 5: Commit**

```
Add switch entity for stateful notifications
```

---

## Task 9: Button Entity (Momentary Notifications)

**Files:**
- Create: `custom_components/notify_lights/button.py`
- Create: `tests/test_button.py`

- [ ] **Step 1: Write failing tests**

Test:
- Entity created for duration>0 notifications
- `press` activates the notification via coordinator
- Auto-deactivates after `duration` seconds
- Multiple presses reset the timer

- [ ] **Step 2: Run tests, verify they fail**

- [ ] **Step 3: Implement NotificationButton entity**

Extends `ButtonEntity`. On `press`, calls `coordinator.async_activate(notification)` and schedules `async_deactivate` after `duration` seconds using `async_call_later`. Cancels any existing timer on re-press.

Entity ID: `button.notify_{name}`.

- [ ] **Step 4: Run tests, verify they pass**

- [ ] **Step 5: Commit**

```
Add button entity for momentary notifications
```

---

## Task 10: End-to-End Wiring and Smoke Test

**Files:**
- Modify: `custom_components/notify_lights/__init__.py` (finalize platform forwarding)
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test**

Full round-trip: set up integration → create notification sub-entry → turn on switch entity → verify MQTT publish called with correct payload → turn off → verify clear_effect sent.

- [ ] **Step 2: Run test, verify it fails**

- [ ] **Step 3: Wire up remaining pieces in __init__.py**

Ensure `async_setup_entry` loads sub-entries, creates Notification objects from stored config, registers entities, and connects everything to the coordinator.

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/ -v`

- [ ] **Step 5: Commit**

```
Wire up end-to-end integration with smoke test
```

---

## Verification

1. **Unit tests:** `pytest tests/ -v` — all pass
2. **Type checking:** `mypy custom_components/notify_lights/` (if configured)
3. **Manual test (deferred):** Install in HA dev instance, add integration, create notification targeting a Blue Series switch, toggle the switch entity, verify LED responds via Z2M
