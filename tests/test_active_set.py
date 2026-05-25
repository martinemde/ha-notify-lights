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
