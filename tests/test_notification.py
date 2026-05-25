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
