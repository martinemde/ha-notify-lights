# tests/test_notification.py
import pytest
from custom_components.notify_lights.notification import Notification
from custom_components.notify_lights.const import Effect, Speed


def test_create_notification_with_all_fields():
    n = Notification(
        name="heating",
        display_name="Heating",
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
        display_name="Test",
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
            name="test", display_name="Test", color=400, brightness=100,
            effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
            duration=0, priority=50,
        )


def test_stateful_when_duration_zero():
    n = Notification(
        name="test", display_name="Test", color=0, brightness=100,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=0, priority=50,
    )
    assert n.is_stateful
    assert not n.is_momentary


def test_momentary_when_duration_positive():
    n = Notification(
        name="test", display_name="Test", color=0, brightness=100,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=10, priority=50,
    )
    assert n.is_momentary
    assert not n.is_stateful


def test_source_bound_stateful_notification():
    n = Notification(
        name="front_door_unlocked", display_name="Front door unlocked",
        color=0, brightness=100, effect=Effect.PULSE,
        effect_speed=Speed.MEDIUM, duration=0, priority=90,
        state_entity="lock.front_door_lock", active_state="unlocked",
    )
    assert n.is_stateful
    assert n.is_source_bound
    assert not n.is_manual_stateful


def test_stateful_without_source_is_manual():
    n = Notification(
        name="manual", display_name="Manual", color=0, brightness=100,
        effect=Effect.SOLID, effect_speed=Speed.MEDIUM,
        duration=0, priority=50,
    )
    assert n.is_manual_stateful
    assert not n.is_source_bound
