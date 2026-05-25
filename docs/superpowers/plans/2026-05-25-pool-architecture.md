# Pool-Based Notification Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rearchitect ha-notify-lights so each notification pool is a separate config entry with its own device, shared global coordinator with per-switch priority stacks.

**Architecture:** Multiple config entries (one per pool), each creating a device with switch/button entities. A global coordinator singleton tracks per-physical-switch notification stacks across all pools. Notifications no longer own targets — pools do.

**Tech Stack:** Python 3.13, Home Assistant config entries API, pytest with HA stubs

---

## File Structure

| File | Responsibility |
|------|---------------|
| `custom_components/notify_lights/notification.py` | Notification dataclass — remove `targets` field |
| `custom_components/notify_lights/coordinator.py` | Global coordinator — per-switch stacks, accepts targets at call site |
| `custom_components/notify_lights/config_flow.py` | Config flow (create pool) + options flow (basics/add/modify/delete) |
| `custom_components/notify_lights/__init__.py` | Entry setup — global coordinator singleton, per-pool device registration |
| `custom_components/notify_lights/switch.py` | Switch entity — passes pool targets to coordinator |
| `custom_components/notify_lights/button.py` | Button entity — passes pool targets to coordinator |
| `custom_components/notify_lights/strings.json` | UI strings for new flow steps |
| `custom_components/notify_lights/const.py` | No changes needed |
| `custom_components/notify_lights/active_set.py` | No changes needed |
| `custom_components/notify_lights/adapter.py` | No interface change (already receives `list[ActiveEntry]`) |
| `tests/conftest.py` | Update stubs for new config flow patterns |
| `tests/test_notification.py` | Update for removed `targets` field |
| `tests/test_coordinator.py` | Update for new `activate(notif, targets, pool_id)` signature |
| `tests/test_switch.py` | Update for new entity init + targets passing |
| `tests/test_config_flow.py` | Rewrite for new multi-step pool flow |
| `tests/test_integration.py` | Update round-trip tests for pool-based architecture |

---

### Task 1: Update Notification Dataclass (remove targets)

**Files:**
- Modify: `custom_components/notify_lights/notification.py`
- Modify: `tests/test_notification.py`

- [ ] **Step 1: Update test file — remove targets from all Notification constructors, remove targets validation test**

```python
# tests/test_notification.py
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
    )
    assert n.color == 240


def test_hue_out_of_range_raises():
    with pytest.raises(ValueError):
        Notification(
            name="test", color=400, brightness=100,
            effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
            duration=0, priority=50,
        )


def test_stateful_when_duration_zero():
    n = Notification(
        name="test", color=0, brightness=100,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=0, priority=50,
    )
    assert n.is_stateful
    assert not n.is_momentary


def test_momentary_when_duration_positive():
    n = Notification(
        name="test", color=0, brightness=100,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=10, priority=50,
    )
    assert n.is_momentary
    assert not n.is_stateful
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_notification.py -v`
Expected: FAIL — `Notification.__init__() missing 1 required positional argument: 'targets'`

- [ ] **Step 3: Update Notification dataclass — remove targets field and validation**

```python
# custom_components/notify_lights/notification.py
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

    def __post_init__(self) -> None:
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
            raise ValueError(
                f"Brightness must be 0-100, got {self.brightness}"
            )
        if not 0 <= self.priority <= 100:
            raise ValueError(f"Priority must be 0-100, got {self.priority}")

    @property
    def is_stateful(self) -> bool:
        """True when the notification persists until explicitly cleared."""
        return self.duration == 0

    @property
    def is_momentary(self) -> bool:
        """True when the notification auto-clears after a fixed duration."""
        return self.duration > 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_notification.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
jj commit -m "Remove targets field from Notification dataclass

Pools now own targets. Notifications inherit them at activation time
rather than carrying their own target list."
```

---

### Task 2: Update Coordinator to Accept Targets at Call Site

**Files:**
- Modify: `custom_components/notify_lights/coordinator.py`
- Modify: `tests/test_coordinator.py`

- [ ] **Step 1: Rewrite coordinator tests for new signature**

The coordinator's `async_activate` and `async_deactivate` now accept `(notification, targets, pool_entry_id)` instead of reading targets from the notification.

```python
# tests/test_coordinator.py
"""Tests for NotifyLightsCoordinator."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.notify_lights.coordinator import NotifyLightsCoordinator
from custom_components.notify_lights.adapter import AdapterRegistry
from custom_components.notify_lights.notification import Notification
from custom_components.notify_lights.const import Effect, Speed


def _make_notif(name="test", priority=50, color=0, effect=Effect.SOLID):
    return Notification(
        name=name,
        color=color,
        brightness=100,
        effect=effect,
        effect_speed=Speed.MEDIUM,
        duration=0,
        priority=priority,
    )


TARGETS = ["light.test_switch"]
POOL_ID = "pool_entry_1"


def _mock_hass_with_device(
    manufacturer="Inovelli", model="VZM31-SN", device_name="office_dimmer"
):
    """Create mock hass with entity/device registry entries for a target."""
    hass = MagicMock()

    entity_entry = MagicMock()
    entity_entry.device_id = "device_123"

    entity_registry = MagicMock()
    entity_registry.async_get.return_value = entity_entry

    device_entry = MagicMock()
    device_entry.manufacturer = manufacturer
    device_entry.model = model
    device_entry.name = device_name

    device_registry = MagicMock()
    device_registry.async_get.return_value = device_entry

    return hass, entity_registry, device_registry


def _make_adapter(manufacturer="Inovelli", model_patterns=None):
    mock_adapter = AsyncMock()
    mock_adapter.manufacturer = manufacturer
    mock_adapter.model_patterns = model_patterns or ["VZM31*"]
    return mock_adapter


@pytest.mark.asyncio
async def test_activate_calls_adapter_render():
    """activate should call adapter.render with friendly name and active set."""
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif()

    await coordinator.async_activate(notif, TARGETS, POOL_ID)

    mock_adapter.render.assert_called_once()
    call_args = mock_adapter.render.call_args
    assert call_args[0][0] == "office_dimmer"
    assert len(call_args[0][1]) == 1


@pytest.mark.asyncio
async def test_activate_passes_notification_in_active_set():
    """activate should include the notification in the active set passed to render."""
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif(name="my_notif")

    await coordinator.async_activate(notif, TARGETS, POOL_ID)

    active_set = mock_adapter.render.call_args[0][1]
    assert active_set[0][0].name == "my_notif"


@pytest.mark.asyncio
async def test_deactivate_clears_when_empty():
    """deactivate with empty resulting set should call render with empty active set."""
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif()

    await coordinator.async_activate(notif, TARGETS, POOL_ID)
    mock_adapter.render.reset_mock()
    await coordinator.async_deactivate(notif, TARGETS, POOL_ID)

    mock_adapter.render.assert_called_once()
    assert len(mock_adapter.render.call_args[0][1]) == 0


@pytest.mark.asyncio
async def test_deactivate_only_removes_matching_notification():
    """deactivate should only remove the named notification, not others."""
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif_a = _make_notif(name="alpha")
    notif_b = _make_notif(name="beta")

    await coordinator.async_activate(notif_a, TARGETS, POOL_ID)
    await coordinator.async_activate(notif_b, TARGETS, POOL_ID)
    mock_adapter.render.reset_mock()

    await coordinator.async_deactivate(notif_a, TARGETS, POOL_ID)

    active_set = mock_adapter.render.call_args[0][1]
    names = [entry[0].name for entry in active_set]
    assert "alpha" not in names
    assert "beta" in names


@pytest.mark.asyncio
async def test_cross_pool_priority_resolution():
    """Notifications from different pools resolve by priority on the same switch."""
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    low = _make_notif(name="low", priority=10)
    high = _make_notif(name="high", priority=90)

    await coordinator.async_activate(low, TARGETS, "pool_a")
    await coordinator.async_activate(high, TARGETS, "pool_b")

    active_set = mock_adapter.render.call_args[0][1]
    assert active_set[0][0].name == "high"
    assert active_set[1][0].name == "low"


@pytest.mark.asyncio
async def test_deactivate_scoped_to_pool():
    """Deactivating from one pool doesn't affect same-name notification from another pool."""
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    registry.register(mock_adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif(name="heating")

    await coordinator.async_activate(notif, TARGETS, "pool_a")
    await coordinator.async_activate(notif, TARGETS, "pool_b")
    mock_adapter.render.reset_mock()

    await coordinator.async_deactivate(notif, TARGETS, "pool_a")

    active_set = mock_adapter.render.call_args[0][1]
    assert len(active_set) == 1


@pytest.mark.asyncio
async def test_unmatched_device_logs_and_skips():
    """Targets with no matching adapter should log a warning without raising."""
    hass, entity_reg, device_reg = _mock_hass_with_device(
        manufacturer="Unknown", model="XYZ"
    )
    registry = AdapterRegistry()

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif()

    await coordinator.async_activate(notif, TARGETS, POOL_ID)


@pytest.mark.asyncio
async def test_missing_entity_entry_logs_and_skips():
    """Targets with no entity registry entry should be skipped gracefully."""
    hass = MagicMock()
    entity_registry = MagicMock()
    entity_registry.async_get.return_value = None
    device_registry = MagicMock()

    registry = AdapterRegistry()
    coordinator = NotifyLightsCoordinator(hass, registry, entity_registry, device_registry)
    notif = _make_notif()

    await coordinator.async_activate(notif, TARGETS, POOL_ID)
    device_registry.async_get.assert_not_called()


@pytest.mark.asyncio
async def test_missing_device_entry_skips():
    """Targets where device lookup returns None should be skipped gracefully."""
    hass = MagicMock()

    entity_entry = MagicMock()
    entity_entry.device_id = "device_123"
    entity_registry = MagicMock()
    entity_registry.async_get.return_value = entity_entry

    device_registry = MagicMock()
    device_registry.async_get.return_value = None

    registry = AdapterRegistry()
    coordinator = NotifyLightsCoordinator(hass, registry, entity_registry, device_registry)
    notif = _make_notif()

    await coordinator.async_activate(notif, TARGETS, POOL_ID)


@pytest.mark.asyncio
async def test_adapter_render_exception_is_caught():
    """An exception raised by adapter.render should be caught and logged."""
    hass, entity_reg, device_reg = _mock_hass_with_device()
    registry = AdapterRegistry()
    mock_adapter = _make_adapter()
    mock_adapter.render.side_effect = RuntimeError("adapter exploded")
    registry.register(mock_adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)
    notif = _make_notif()

    await coordinator.async_activate(notif, TARGETS, POOL_ID)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_coordinator.py -v`
Expected: FAIL — `async_activate() takes 2 positional arguments but 4 were given`

- [ ] **Step 3: Update coordinator implementation**

```python
# custom_components/notify_lights/coordinator.py
"""Central coordinator for Notify Lights.

Tracks per-target active notification stacks, resolves entity IDs to device
info, matches adapters from the registry, and dispatches render calls.
"""
from __future__ import annotations

import logging
import time

from .adapter import AdapterRegistry
from .active_set import ActiveEntry, compute_active_set
from .notification import Notification

_LOGGER = logging.getLogger(__name__)

# (Notification, pool_entry_id, activated_at)
StackEntry = tuple[Notification, str, float]


class NotifyLightsCoordinator:
    """Coordinate notifications across targets and adapters.

    Holds the AdapterRegistry, tracks per-target notification stacks,
    resolves target references to entity IDs, looks up device info from HA
    registries, and dispatches render calls to matched adapters.
    """

    def __init__(
        self,
        hass,
        adapter_registry: AdapterRegistry,
        entity_registry,
        device_registry,
    ) -> None:
        self._hass = hass
        self._adapter_registry = adapter_registry
        self._entity_registry = entity_registry
        self._device_registry = device_registry
        self._stacks: dict[str, list[StackEntry]] = {}
        self._warned_targets: set[str] = set()

    async def async_activate(
        self, notification: Notification, targets: list[str], pool_entry_id: str
    ) -> None:
        """Add notification to each target's stack and re-render."""
        activated_at = time.monotonic()
        _LOGGER.info(
            "Activating %s (pool=%s) on %d targets: %s",
            notification.name, pool_entry_id, len(targets), targets,
        )
        for target in targets:
            stack = self._stacks.setdefault(target, [])
            stack.append((notification, pool_entry_id, activated_at))
            await self._render_target(target)

    async def async_deactivate(
        self, notification: Notification, targets: list[str], pool_entry_id: str
    ) -> None:
        """Remove notification from each target's stack and re-render."""
        _LOGGER.info(
            "Deactivating %s (pool=%s) on %d targets: %s",
            notification.name, pool_entry_id, len(targets), targets,
        )
        for target in targets:
            stack = self._stacks.get(target, [])
            self._stacks[target] = [
                (n, pid, t) for n, pid, t in stack
                if not (n.name == notification.name and pid == pool_entry_id)
            ]
            await self._render_target(target)

    async def _render_target(self, target_entity_id: str) -> None:
        """Look up device info, match adapter, and call render for one target."""
        entity_entry = self._entity_registry.async_get(target_entity_id)
        if entity_entry is None or entity_entry.device_id is None:
            if target_entity_id not in self._warned_targets:
                _LOGGER.warning(
                    "Target %s has no device entry, skipping", target_entity_id
                )
                self._warned_targets.add(target_entity_id)
            return

        device_entry = self._device_registry.async_get(entity_entry.device_id)
        if device_entry is None:
            if target_entity_id not in self._warned_targets:
                _LOGGER.warning(
                    "No device found for target %s (device_id=%s), skipping",
                    target_entity_id, entity_entry.device_id,
                )
                self._warned_targets.add(target_entity_id)
            return

        adapter = self._adapter_registry.get_adapter(
            device_entry.manufacturer or "", device_entry.model or ""
        )
        if adapter is None:
            if target_entity_id not in self._warned_targets:
                _LOGGER.warning(
                    "No adapter for %s (manufacturer=%s, model=%s), skipping",
                    target_entity_id, device_entry.manufacturer, device_entry.model,
                )
                self._warned_targets.add(target_entity_id)
            return

        # Convert StackEntry to ActiveEntry for the adapter
        active_entries: list[ActiveEntry] = [
            (n, t) for n, _pid, t in self._stacks.get(target_entity_id, [])
        ]
        active_set = compute_active_set(active_entries)
        friendly_name = device_entry.name

        _LOGGER.info(
            "Rendering %s (%s): %d active notifications, adapter=%s",
            target_entity_id, friendly_name, len(active_set),
            type(adapter).__name__,
        )

        try:
            await adapter.render(friendly_name, active_set)
        except Exception:
            _LOGGER.exception("Adapter render failed for %s", target_entity_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_coordinator.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
jj commit -m "Update coordinator to accept targets and pool_entry_id

Coordinator now tracks per-switch stacks with pool identity. This
enables cross-pool priority resolution on shared physical switches."
```

---

### Task 3: Update Switch and Button Entities

**Files:**
- Modify: `custom_components/notify_lights/switch.py`
- Modify: `custom_components/notify_lights/button.py`
- Modify: `tests/test_switch.py`

- [ ] **Step 1: Update switch tests for new constructor and coordinator calls**

```python
# tests/test_switch.py
import pytest
from unittest.mock import AsyncMock
from custom_components.notify_lights.switch import NotificationSwitch
from custom_components.notify_lights.notification import Notification
from custom_components.notify_lights.const import Effect, Speed


TARGETS = ["light.lr"]
ENTRY_ID = "pool_entry_1"


def _make_notif(name="test_alert"):
    return Notification(
        name=name, color=0, brightness=100,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=0, priority=50,
    )


@pytest.mark.asyncio
async def test_turn_on_activates_notification():
    coordinator = AsyncMock()
    notif = _make_notif()
    switch = NotificationSwitch(coordinator, notif, TARGETS, ENTRY_ID)

    await switch.async_turn_on()

    assert switch.is_on is True
    coordinator.async_activate.assert_called_once_with(notif, TARGETS, ENTRY_ID)


@pytest.mark.asyncio
async def test_turn_off_deactivates_notification():
    coordinator = AsyncMock()
    notif = _make_notif()
    switch = NotificationSwitch(coordinator, notif, TARGETS, ENTRY_ID)

    await switch.async_turn_on()
    coordinator.async_activate.reset_mock()
    await switch.async_turn_off()

    assert switch.is_on is False
    coordinator.async_deactivate.assert_called_once_with(notif, TARGETS, ENTRY_ID)


def test_unique_id_includes_entry_id():
    coordinator = AsyncMock()
    notif = _make_notif("heating_alert")
    switch = NotificationSwitch(coordinator, notif, TARGETS, ENTRY_ID)

    assert switch.unique_id == f"notify_lights_{ENTRY_ID}_heating_alert"


def test_display_name():
    coordinator = AsyncMock()
    notif = _make_notif("heating_alert")
    switch = NotificationSwitch(coordinator, notif, TARGETS, ENTRY_ID)

    assert switch.name == "Notify heating alert"


def test_initial_state_is_off():
    coordinator = AsyncMock()
    notif = _make_notif()
    switch = NotificationSwitch(coordinator, notif, TARGETS, ENTRY_ID)

    assert switch.is_on is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_switch.py -v`
Expected: FAIL — `NotificationSwitch.__init__() takes 3 positional arguments but 5 were given`

- [ ] **Step 3: Update switch.py**

```python
# custom_components/notify_lights/switch.py
"""Switch entity for stateful (duration=0) notifications."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .notification import Notification

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    notifications = data["notifications"]
    targets = data["targets"]

    stateful = [n for n in notifications.values() if n.is_stateful]
    _LOGGER.info(
        "Switch platform setup: %d stateful of %d total notifications",
        len(stateful), len(notifications),
    )

    entities = [
        NotificationSwitch(coordinator, notif, targets, entry.entry_id)
        for notif in stateful
    ]
    async_add_entities(entities)


class NotificationSwitch(SwitchEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        notification: Notification,
        targets: list[str],
        entry_id: str,
    ) -> None:
        self._coordinator = coordinator
        self._notification = notification
        self._targets = targets
        self._entry_id = entry_id
        self._is_on = False
        self._attr_unique_id = f"notify_lights_{entry_id}_{notification.name}"
        self._attr_name = f"Notify {notification.name.replace('_', ' ')}"

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        _LOGGER.info("Switch %s turned ON", self._notification.name)
        self._is_on = True
        await self._coordinator.async_activate(
            self._notification, self._targets, self._entry_id
        )

    async def async_turn_off(self, **kwargs) -> None:
        _LOGGER.info("Switch %s turned OFF", self._notification.name)
        self._is_on = False
        await self._coordinator.async_deactivate(
            self._notification, self._targets, self._entry_id
        )
```

- [ ] **Step 4: Update button.py**

```python
# custom_components/notify_lights/button.py
"""Button entity for momentary (duration > 0) notifications."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN
from .notification import Notification

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    notifications = data["notifications"]
    targets = data["targets"]

    momentary = [n for n in notifications.values() if n.is_momentary]
    _LOGGER.info(
        "Button platform setup: %d momentary of %d total notifications",
        len(momentary), len(notifications),
    )

    entities = [
        NotificationButton(coordinator, notif, targets, entry.entry_id, hass)
        for notif in momentary
    ]
    async_add_entities(entities)


class NotificationButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        notification: Notification,
        targets: list[str],
        entry_id: str,
        hass,
    ) -> None:
        self._coordinator = coordinator
        self._notification = notification
        self._targets = targets
        self._entry_id = entry_id
        self._hass = hass
        self._cancel_timer = None
        self._attr_unique_id = f"notify_lights_{entry_id}_{notification.name}"
        self._attr_name = f"Notify {notification.name.replace('_', ' ')}"

    async def async_press(self, **kwargs) -> None:
        _LOGGER.info(
            "Button %s pressed (duration=%ds)",
            self._notification.name, self._notification.duration,
        )
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None

        await self._coordinator.async_activate(
            self._notification, self._targets, self._entry_id
        )

        self._cancel_timer = async_call_later(
            self._hass,
            self._notification.duration,
            self._auto_deactivate,
        )

    async def _auto_deactivate(self, _now=None) -> None:
        _LOGGER.info("Auto-deactivating button %s", self._notification.name)
        self._cancel_timer = None
        await self._coordinator.async_deactivate(
            self._notification, self._targets, self._entry_id
        )
```

- [ ] **Step 5: Run switch tests to verify they pass**

Run: `python -m pytest tests/test_switch.py -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
jj commit -m "Update switch and button entities to pass targets to coordinator

Entities receive targets and entry_id at construction time. unique_id
now includes entry_id for pool-scoped identity."
```

---

### Task 4: Rewrite Config Flow for Pool Creation

**Files:**
- Modify: `custom_components/notify_lights/config_flow.py`
- Modify: `custom_components/notify_lights/strings.json`
- Modify: `tests/test_config_flow.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Update conftest.py stubs for new config flow features**

Add `suggested_area_id` support and ensure `OptionsFlowWithConfigEntry` can handle the new menu options.

```python
# tests/conftest.py
"""Stub out Home Assistant modules so pure-Python unit tests run without HA."""
import sys
import types
from unittest.mock import MagicMock


class _ConfigFlow:
    """Minimal stub for homeassistant.config_entries.ConfigFlow."""

    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if domain:
            cls.domain = domain

    def async_show_form(self, *, step_id, data_schema=None, errors=None):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema}

    def async_create_entry(self, *, title, data, options=None):
        return {"type": "create_entry", "title": title, "data": data, "options": options or {}}

    async def async_set_unique_id(self, unique_id):
        self._unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        pass


class _OptionsFlowWithConfigEntry:
    """Minimal stub for OptionsFlowWithConfigEntry."""

    def __init__(self, config_entry=None):
        self.config_entry = config_entry
        self.options = getattr(config_entry, "options", {}) if config_entry else {}
        self.hass = getattr(config_entry, "hass", None)

    def async_show_form(self, *, step_id, data_schema=None, errors=None, description_placeholders=None):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema}

    def async_create_entry(self, *, data, title=""):
        return {"type": "create_entry", "data": data}

    def async_show_menu(self, *, step_id, menu_options):
        return {"type": "menu", "step_id": step_id, "menu_options": menu_options}


_config_entries_stub = types.ModuleType("homeassistant.config_entries")
_config_entries_stub.ConfigFlow = _ConfigFlow
_config_entries_stub.ConfigEntry = MagicMock
_config_entries_stub.OptionsFlowWithConfigEntry = _OptionsFlowWithConfigEntry

# Stub homeassistant modules before any component imports
for module in [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.selector",
]:
    sys.modules.setdefault(module, MagicMock())

sys.modules["homeassistant.config_entries"] = _config_entries_stub

# Stub voluptuous (used by config_flow for form schemas)
if "voluptuous" not in sys.modules:
    _vol = MagicMock()
    _vol.Schema = MagicMock(side_effect=lambda schema: schema)
    _vol.Required = MagicMock(side_effect=lambda key, **kw: key)
    _vol.Optional = MagicMock(side_effect=lambda key, **kw: key)
    sys.modules["voluptuous"] = _vol

# Switch entity stub
_switch_module = types.ModuleType("homeassistant.components.switch")


class _SwitchEntity:
    _attr_unique_id = None
    _attr_name = None
    _attr_has_entity_name = False

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def name(self):
        return self._attr_name


_switch_module.SwitchEntity = _SwitchEntity
sys.modules.setdefault(
    "homeassistant.components", types.ModuleType("homeassistant.components")
)
sys.modules["homeassistant.components.switch"] = _switch_module

# Button entity stub
_button_module = types.ModuleType("homeassistant.components.button")


class _ButtonEntity:
    _attr_unique_id = None
    _attr_name = None
    _attr_has_entity_name = False

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def name(self):
        return self._attr_name


_button_module.ButtonEntity = _ButtonEntity
sys.modules["homeassistant.components.button"] = _button_module

# Event helpers stub
_event_module = types.ModuleType("homeassistant.helpers.event")


def _async_call_later(hass, delay, callback):
    return MagicMock()


_event_module.async_call_later = _async_call_later
sys.modules["homeassistant.helpers.event"] = _event_module
```

- [ ] **Step 2: Write config flow tests for pool creation**

```python
# tests/test_config_flow.py
"""Tests for the Notify Lights config flow (pool-based)."""
import pytest
from unittest.mock import MagicMock
from custom_components.notify_lights.config_flow import (
    NotifyLightsConfigFlow,
    NotifyLightsOptionsFlow,
)
from custom_components.notify_lights.const import DOMAIN


@pytest.mark.asyncio
async def test_user_step_shows_name_form():
    """First step shows pool name + area form."""
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()

    result = await flow.async_step_user(user_input=None)

    assert result["type"] == "form"
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_user_step_advances_to_targets():
    """Submitting name advances to targets step."""
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()

    result = await flow.async_step_user(
        user_input={"name": "Floor 1 Switches", "area_id": "living_room"}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "targets"


@pytest.mark.asyncio
async def test_targets_step_creates_entry():
    """Submitting targets creates the config entry."""
    flow = NotifyLightsConfigFlow()
    flow.hass = MagicMock()

    # First advance through user step
    await flow.async_step_user(
        user_input={"name": "Floor 1 Switches", "area_id": ""}
    )

    result = await flow.async_step_targets(
        user_input={"targets": ["light.living_room", "light.kitchen"]}
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "Floor 1 Switches"
    assert result["data"]["name"] == "Floor 1 Switches"
    assert result["data"]["targets"] == ["light.living_room", "light.kitchen"]
    assert result["options"] == {"notifications": {}}


@pytest.mark.asyncio
async def test_options_init_shows_menu():
    """Options flow shows menu when notifications exist."""
    entry = MagicMock()
    entry.data = {"name": "Test Pool", "area_id": "", "targets": ["light.x"]}
    entry.options = {"notifications": {"heating": {"slug": "heating", "display_name": "Heating"}}}

    flow = NotifyLightsOptionsFlow(entry)
    flow.hass = MagicMock()
    result = await flow.async_step_init(user_input=None)

    assert result["type"] == "menu"
    assert "add" in result["menu_options"]
    assert "modify" in result["menu_options"]
    assert "delete" in result["menu_options"]
    assert "basics" in result["menu_options"]


@pytest.mark.asyncio
async def test_options_init_redirects_to_add_when_empty():
    """Options flow goes straight to add when no notifications exist."""
    entry = MagicMock()
    entry.data = {"name": "Test Pool", "area_id": "", "targets": ["light.x"]}
    entry.options = {"notifications": {}}

    flow = NotifyLightsOptionsFlow(entry)
    flow.hass = MagicMock()
    result = await flow.async_step_init(user_input=None)

    assert result["type"] == "form"
    assert result["step_id"] == "add"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_config_flow.py -v`
Expected: FAIL — ImportError or step method missing

- [ ] **Step 4: Rewrite config_flow.py for pool-based architecture**

```python
# custom_components/notify_lights/config_flow.py
"""Config flow for the Notify Lights integration."""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlowWithConfigEntry,
)
from homeassistant.helpers import selector

from .const import (
    DEFAULT_BRIGHTNESS,
    DEFAULT_PRIORITY,
    DEFAULT_SPEED,
    DOMAIN,
    Effect,
    NAMED_COLORS,
    Speed,
)

_LOGGER = logging.getLogger(__name__)

COLOR_OPTIONS = [
    selector.SelectOptionDict(value=name, label=name.capitalize())
    for name in NAMED_COLORS
]

EFFECT_OPTIONS = [
    selector.SelectOptionDict(value=e.value, label=e.value.capitalize())
    for e in Effect
]

SPEED_OPTIONS = [
    selector.SelectOptionDict(value=s.value, label=s.value.capitalize())
    for s in Speed
]


def _slugify(name: str) -> str:
    """Generate a stable slug from a notification name."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _notification_schema() -> vol.Schema:
    """Build the notification form schema (no targets — pool owns them)."""
    return vol.Schema(
        {
            vol.Required("name"): selector.TextSelector(),
            vol.Required("color", default="blue"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=COLOR_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required("effect", default=Effect.SOLID): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=EFFECT_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required("effect_speed", default=DEFAULT_SPEED): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=SPEED_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required("brightness", default=DEFAULT_BRIGHTNESS): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=100, step=1,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required("duration", default=0): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=86400, step=1,
                    unit_of_measurement="seconds",
                )
            ),
            vol.Required("priority", default=DEFAULT_PRIORITY): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=100, step=1,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
        }
    )


class NotifyLightsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._pool_name: str = ""
        self._area_id: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("name"): selector.TextSelector(),
                        vol.Optional("area_id", default=""): selector.AreaSelector(),
                    }
                ),
            )

        self._pool_name = user_input["name"]
        self._area_id = user_input.get("area_id", "")
        return await self.async_step_targets()

    async def async_step_targets(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is None:
            return self.async_show_form(
                step_id="targets",
                data_schema=vol.Schema(
                    {
                        vol.Required("targets"): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain=["light", "switch"],
                                multiple=True,
                            )
                        ),
                    }
                ),
            )

        return self.async_create_entry(
            title=self._pool_name,
            data={
                "name": self._pool_name,
                "area_id": self._area_id,
                "targets": user_input["targets"],
            },
            options={"notifications": {}},
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> NotifyLightsOptionsFlow:
        return NotifyLightsOptionsFlow(config_entry)


class NotifyLightsOptionsFlow(OptionsFlowWithConfigEntry):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        notifications = self.options.get("notifications", {})

        if not notifications:
            return await self.async_step_add()

        menu_options = ["basics", "add", "modify", "delete"]
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_basics(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is not None:
            new_data = dict(self.config_entry.data)
            new_data["name"] = user_input["name"]
            new_data["area_id"] = user_input.get("area_id", "")
            new_data["targets"] = user_input["targets"]
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            return self.async_create_entry(data=dict(self.options))

        current = self.config_entry.data
        return self.async_show_form(
            step_id="basics",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=current.get("name", "")): selector.TextSelector(),
                    vol.Optional("area_id", default=current.get("area_id", "")): selector.AreaSelector(),
                    vol.Required("targets", default=current.get("targets", [])): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=["light", "switch"],
                            multiple=True,
                        )
                    ),
                }
            ),
        )

    async def async_step_add(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input["name"]
            slug = _slugify(name)
            notifications = dict(self.options.get("notifications", {}))

            if slug in notifications:
                errors["name"] = "name_exists"
            else:
                notifications[slug] = {
                    "slug": slug,
                    "display_name": name,
                    "color": user_input["color"],
                    "effect": user_input["effect"],
                    "effect_speed": user_input["effect_speed"],
                    "brightness": int(user_input["brightness"]),
                    "duration": int(user_input["duration"]),
                    "priority": int(user_input["priority"]),
                }
                return self.async_create_entry(data={"notifications": notifications})

        return self.async_show_form(
            step_id="add",
            data_schema=_notification_schema(),
            errors=errors,
        )

    async def async_step_modify(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        notifications = dict(self.options.get("notifications", {}))

        if user_input is not None and "slug" in user_input:
            slug = user_input["slug"]
            self._modify_slug = slug
            return await self.async_step_modify_form()

        if user_input is not None and hasattr(self, "_modify_slug"):
            slug = self._modify_slug
            notifications[slug] = {
                "slug": slug,
                "display_name": user_input["name"],
                "color": user_input["color"],
                "effect": user_input["effect"],
                "effect_speed": user_input["effect_speed"],
                "brightness": int(user_input["brightness"]),
                "duration": int(user_input["duration"]),
                "priority": int(user_input["priority"]),
            }
            return self.async_create_entry(data={"notifications": notifications})

        slug_options = [
            selector.SelectOptionDict(value=slug, label=cfg["display_name"])
            for slug, cfg in notifications.items()
        ]

        return self.async_show_form(
            step_id="modify",
            data_schema=vol.Schema(
                {
                    vol.Required("slug"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=slug_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_modify_form(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is not None:
            notifications = dict(self.options.get("notifications", {}))
            slug = self._modify_slug
            notifications[slug] = {
                "slug": slug,
                "display_name": user_input["name"],
                "color": user_input["color"],
                "effect": user_input["effect"],
                "effect_speed": user_input["effect_speed"],
                "brightness": int(user_input["brightness"]),
                "duration": int(user_input["duration"]),
                "priority": int(user_input["priority"]),
            }
            return self.async_create_entry(data={"notifications": notifications})

        current = self.options["notifications"][self._modify_slug]
        return self.async_show_form(
            step_id="modify_form",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=current["display_name"]): selector.TextSelector(),
                    vol.Required("color", default=current["color"]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=COLOR_OPTIONS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required("effect", default=current["effect"]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=EFFECT_OPTIONS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required("effect_speed", default=current["effect_speed"]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=SPEED_OPTIONS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required("brightness", default=current["brightness"]): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=100, step=1,
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required("duration", default=current["duration"]): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=86400, step=1,
                            unit_of_measurement="seconds",
                        )
                    ),
                    vol.Required("priority", default=current["priority"]): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=100, step=1,
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                }
            ),
        )

    async def async_step_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        notifications = dict(self.options.get("notifications", {}))

        if user_input is not None:
            slug = user_input["slug"]
            notifications.pop(slug, None)
            return self.async_create_entry(data={"notifications": notifications})

        slug_options = [
            selector.SelectOptionDict(value=slug, label=cfg["display_name"])
            for slug, cfg in notifications.items()
        ]

        return self.async_show_form(
            step_id="delete",
            data_schema=vol.Schema(
                {
                    vol.Required("slug"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=slug_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )
```

- [ ] **Step 5: Update strings.json**

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Create Notification Pool",
        "description": "Name this notification target group and optionally assign it to an area.",
        "data": {
          "name": "Pool name",
          "area_id": "Area"
        }
      },
      "targets": {
        "title": "Select Targets",
        "description": "Choose which light/switch entities this pool targets.",
        "data": {
          "targets": "Target entities"
        }
      }
    }
  },
  "options": {
    "step": {
      "init": {
        "menu_options": {
          "basics": "Pool settings",
          "add": "Add notification",
          "modify": "Modify notification",
          "delete": "Delete notification"
        }
      },
      "basics": {
        "title": "Pool Settings",
        "data": {
          "name": "Pool name",
          "area_id": "Area",
          "targets": "Target entities"
        }
      },
      "add": {
        "title": "Add Notification",
        "description": "Define a new LED notification. Duration 0 = stateful (switch), duration > 0 = momentary (button).",
        "data": {
          "name": "Name",
          "color": "Color",
          "effect": "Effect",
          "effect_speed": "Speed",
          "brightness": "Brightness",
          "duration": "Duration (seconds, 0 = stays on)",
          "priority": "Priority"
        }
      },
      "modify": {
        "title": "Modify Notification",
        "data": {
          "slug": "Notification to modify"
        }
      },
      "modify_form": {
        "title": "Edit Notification",
        "data": {
          "name": "Display name",
          "color": "Color",
          "effect": "Effect",
          "effect_speed": "Speed",
          "brightness": "Brightness",
          "duration": "Duration (seconds, 0 = stays on)",
          "priority": "Priority"
        }
      },
      "delete": {
        "title": "Delete Notification",
        "data": {
          "slug": "Notification to delete"
        }
      }
    },
    "error": {
      "name_exists": "A notification with this name already exists."
    }
  }
}
```

- [ ] **Step 6: Run config flow tests to verify they pass**

Run: `python -m pytest tests/test_config_flow.py -v`
Expected: All 5 tests PASS

- [ ] **Step 7: Commit**

```bash
jj commit -m "Rewrite config flow for pool-based architecture

Config flow creates pools with name, optional area, and target entities.
Options flow provides basics/add/modify/delete menu. Notifications use
stable slugs for identity with editable display names."
```

---

### Task 5: Rewrite Entry Setup for Global Coordinator + Per-Pool Devices

**Files:**
- Modify: `custom_components/notify_lights/__init__.py`

- [ ] **Step 1: Rewrite __init__.py**

```python
# custom_components/notify_lights/__init__.py
"""Notify Lights — LED notifications as HA entities."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .adapter import AdapterRegistry
from .adapters.inovelli_blue_z2m import InovelliBlueZ2MAdapter
from .const import DOMAIN, Effect, Speed, NAMED_COLORS
from .coordinator import NotifyLightsCoordinator
from .notification import Notification

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "button"]


def _get_or_create_coordinator(hass: HomeAssistant) -> NotifyLightsCoordinator:
    """Return the global coordinator singleton, creating it if needed."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "coordinator" not in domain_data:
        entity_registry = er.async_get(hass)
        device_registry = dr.async_get(hass)

        adapter_registry = AdapterRegistry()
        adapter_registry.register(InovelliBlueZ2MAdapter(hass))

        domain_data["coordinator"] = NotifyLightsCoordinator(
            hass, adapter_registry, entity_registry, device_registry
        )
        _LOGGER.info("Created global NotifyLightsCoordinator")

    return domain_data["coordinator"]


def notifications_from_options(options: dict) -> dict[str, Notification]:
    """Build Notification objects from config entry options."""
    result: dict[str, Notification] = {}
    for slug, config in options.get("notifications", {}).items():
        color = config["color"]
        if isinstance(color, str) and color in NAMED_COLORS:
            color = NAMED_COLORS[color]
        result[slug] = Notification(
            name=slug,
            color=color,
            brightness=int(config["brightness"]),
            effect=Effect(config["effect"]),
            effect_speed=Speed(config["effect_speed"]),
            duration=int(config["duration"]),
            priority=int(config["priority"]),
        )
    _LOGGER.info("Loaded %d notifications from options", len(result))
    return result


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Setting up pool entry %s (%s)", entry.entry_id, entry.data.get("name"))

    coordinator = _get_or_create_coordinator(hass)
    notifications = notifications_from_options(entry.options)
    targets = entry.data.get("targets", [])

    # Register device for this pool
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get("name", "Notify Lights Pool"),
        suggested_area=entry.data.get("area_id") or None,
    )

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "notifications": notifications,
        "targets": targets,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _LOGGER.info("Setup complete for pool %s", entry.entry_id)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _LOGGER.info("Options updated for pool %s, reloading", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Unloading pool %s", entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
```

- [ ] **Step 2: Run full test suite (some integration tests will still fail — that's next task)**

Run: `python -m pytest tests/test_notification.py tests/test_coordinator.py tests/test_switch.py tests/test_config_flow.py -v`
Expected: All tests in these files PASS

- [ ] **Step 3: Commit**

```bash
jj commit -m "Rewrite entry setup for global coordinator and per-pool devices

Each pool entry creates a device and shares the global coordinator
singleton. Entry data stores pool name, area, and targets."
```

---

### Task 6: Update Integration Tests

**Files:**
- Modify: `tests/test_integration.py`

- [ ] **Step 1: Rewrite integration tests for pool-based architecture**

```python
# tests/test_integration.py
"""End-to-end smoke tests for the pool-based Notify Lights architecture."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.notify_lights.coordinator import NotifyLightsCoordinator
from custom_components.notify_lights.adapter import AdapterRegistry, NotificationAdapter
from custom_components.notify_lights.notification import Notification
from custom_components.notify_lights.const import Effect, Speed, DOMAIN
from custom_components.notify_lights.switch import NotificationSwitch
from custom_components.notify_lights.button import NotificationButton


class MockAdapter(NotificationAdapter):
    manufacturer = "Inovelli"
    model_patterns = ["VZM31*"]
    max_concurrent = 1
    supported_effects = set(Effect)
    effect_fallbacks = {}

    def __init__(self):
        self.render_calls = []
        self.clear_calls = []

    async def render(self, target, active):
        self.render_calls.append((target, list(active)))

    async def clear(self, target):
        self.clear_calls.append(target)


TARGETS = ["light.office_dimmer"]
POOL_A = "pool_entry_a"
POOL_B = "pool_entry_b"


def _make_registries(device_name="office_dimmer"):
    """Create mock entity and device registries."""
    entity_entry = MagicMock()
    entity_entry.device_id = "device_123"

    entity_registry = MagicMock()
    entity_registry.async_get.return_value = entity_entry

    device_entry = MagicMock()
    device_entry.manufacturer = "Inovelli"
    device_entry.model = "VZM31-SN"
    device_entry.name = device_name

    device_registry = MagicMock()
    device_registry.async_get.return_value = device_entry

    return entity_registry, device_registry


@pytest.mark.asyncio
async def test_switch_round_trip():
    """Full round-trip: switch on -> adapter renders -> switch off -> adapter clears."""
    hass = MagicMock()
    entity_reg, device_reg = _make_registries("office_dimmer")
    adapter = MockAdapter()

    registry = AdapterRegistry()
    registry.register(adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)

    notif = Notification(
        name="heating",
        color=120,
        brightness=80,
        effect=Effect.PULSE,
        effect_speed=Speed.FAST,
        duration=0,
        priority=50,
    )

    switch = NotificationSwitch(coordinator, notif, TARGETS, POOL_A)

    await switch.async_turn_on()
    assert switch.is_on is True
    assert len(adapter.render_calls) == 1
    target, active = adapter.render_calls[0]
    assert target == "office_dimmer"
    assert len(active) == 1
    assert active[0][0].name == "heating"

    await switch.async_turn_off()
    assert switch.is_on is False
    assert len(adapter.render_calls) == 2
    target, active = adapter.render_calls[1]
    assert target == "office_dimmer"
    assert len(active) == 0


@pytest.mark.asyncio
async def test_button_activates_and_schedules_deactivation():
    """Button press -> adapter renders -> timer fires -> adapter clears."""
    hass = MagicMock()
    entity_reg, device_reg = _make_registries("kitchen_switch")
    adapter = MockAdapter()

    registry = AdapterRegistry()
    registry.register(adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)

    notif = Notification(
        name="doorbell_flash",
        color=0,
        brightness=100,
        effect=Effect.BLINK,
        effect_speed=Speed.FAST,
        duration=5,
        priority=90,
    )

    targets = ["light.kitchen_switch"]
    captured_callback = None

    def fake_call_later(hass, delay, callback):
        nonlocal captured_callback
        captured_callback = callback
        assert delay == 5
        return MagicMock()

    button = NotificationButton(coordinator, notif, targets, POOL_A, hass)

    with patch("custom_components.notify_lights.button.async_call_later", side_effect=fake_call_later):
        await button.async_press()

    assert len(adapter.render_calls) == 1
    target, active = adapter.render_calls[0]
    assert target == "kitchen_switch"
    assert active[0][0].name == "doorbell_flash"

    assert captured_callback is not None
    await captured_callback()

    assert len(adapter.render_calls) == 2
    target, active = adapter.render_calls[1]
    assert len(active) == 0


@pytest.mark.asyncio
async def test_cross_pool_priority_on_shared_switch():
    """Two pools targeting the same switch resolve by priority."""
    hass = MagicMock()
    entity_reg, device_reg = _make_registries("office_dimmer")
    adapter = MockAdapter()

    registry = AdapterRegistry()
    registry.register(adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)

    low = Notification(
        name="background", color=120, brightness=50,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=0, priority=10,
    )
    high = Notification(
        name="urgent_alert", color=0, brightness=100,
        effect=Effect.BLINK, effect_speed=Speed.FAST,
        duration=0, priority=90,
    )

    switch_low = NotificationSwitch(coordinator, low, TARGETS, POOL_A)
    switch_high = NotificationSwitch(coordinator, high, TARGETS, POOL_B)

    await switch_low.async_turn_on()
    await switch_high.async_turn_on()

    target, active = adapter.render_calls[-1]
    assert active[0][0].name == "urgent_alert"
    assert active[1][0].name == "background"

    # Turn off high priority from pool B -> only low from pool A remains
    await switch_high.async_turn_off()
    target, active = adapter.render_calls[-1]
    assert len(active) == 1
    assert active[0][0].name == "background"


@pytest.mark.asyncio
async def test_same_notification_different_pools_independent():
    """Same notification name from two pools are tracked independently."""
    hass = MagicMock()
    entity_reg, device_reg = _make_registries("office_dimmer")
    adapter = MockAdapter()

    registry = AdapterRegistry()
    registry.register(adapter)

    coordinator = NotifyLightsCoordinator(hass, registry, entity_reg, device_reg)

    notif = Notification(
        name="heating", color=120, brightness=80,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=0, priority=50,
    )

    switch_a = NotificationSwitch(coordinator, notif, TARGETS, POOL_A)
    switch_b = NotificationSwitch(coordinator, notif, TARGETS, POOL_B)

    await switch_a.async_turn_on()
    await switch_b.async_turn_on()

    # Two active entries on same switch
    target, active = adapter.render_calls[-1]
    assert len(active) == 2

    # Deactivate from pool A only
    await switch_a.async_turn_off()
    target, active = adapter.render_calls[-1]
    assert len(active) == 1
```

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
jj commit -m "Update integration tests for pool-based architecture

Tests verify cross-pool priority resolution, independent pool tracking,
and the full switch/button round-trip with pool targets."
```

---

### Task 7: Clean Up Removed Code and Final Verification

**Files:**
- Modify: `tests/test_button.py` (if it exists)
- Remove: any orphaned test references

- [ ] **Step 1: Check for remaining test files that reference old API**

Run: `grep -r "targets=" tests/ --include="*.py" | grep -v "test_config_flow"`
Fix any remaining references to old `targets=` in Notification constructors.

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS, 0 failures

- [ ] **Step 3: Run a quick check for any remaining references to old patterns**

Run: `grep -rn "targets=\|_find_supported_entities\|unique_id_configured" custom_components/ tests/`
Expected: No matches from old code patterns (targets= only in config_flow for entity picker, not Notification)

- [ ] **Step 4: Commit any final cleanup**

```bash
jj commit -m "Clean up remaining references to old single-entry architecture"
```

---

## Summary of Changes

| Component | Before | After |
|-----------|--------|-------|
| Config entry | One singleton for all | One per pool |
| Notification.targets | Per-notification | Removed (pool-owned) |
| Coordinator | Per-entry | Global singleton |
| coordinator.activate() | `(notification)` | `(notification, targets, pool_entry_id)` |
| Deactivation | By notification name | By name + pool_entry_id |
| Device | One for integration | One per pool |
| Entity unique_id | `notify_lights_{name}` | `notify_lights_{entry_id}_{slug}` |
| Options flow | Add/Remove | Basics/Add/Modify/Delete |
