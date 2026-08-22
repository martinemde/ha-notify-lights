"""Tests for the hardware-independent Inovelli Blue bar model."""

from custom_components.notify_lights.adapters.inovelli_blue_bar import (
    InovelliBlueBar,
)
from custom_components.notify_lights.const import Effect, Speed
from custom_components.notify_lights.notification import Notification


def _notification(name: str, color: int, effect: Effect, priority: int = 50):
    return Notification(
        name=name,
        display_name=name.title(),
        color=color,
        brightness=80,
        effect=effect,
        effect_speed=Speed.MEDIUM,
        duration=0,
        priority=priority,
    )


def test_empty_bar_has_seven_empty_pixels():
    bar = InovelliBlueBar.from_active([])

    assert bar.is_empty
    assert not bar.is_layered
    assert bar.pixels == (None,) * 7


def test_one_notification_fills_the_bar():
    notification = _notification("primary", 240, Effect.PULSE)

    bar = InovelliBlueBar.from_active([(notification, 1.0)])

    assert not bar.is_empty
    assert not bar.is_layered
    assert [pixel.led for pixel in bar.pixels] == list(range(1, 8))
    assert all(pixel.notification is notification for pixel in bar.pixels)
    assert all(pixel.effect is Effect.PULSE for pixel in bar.pixels)


def test_two_notifications_create_bottom_secondary_layer():
    primary = _notification("primary", 0, Effect.BLINK, priority=90)
    secondary = _notification("secondary", 120, Effect.PULSE, priority=10)

    bar = InovelliBlueBar.from_active([
        (primary, 2.0),
        (secondary, 1.0),
    ])

    assert bar.is_layered
    assert bar.pixels[0].notification is secondary
    assert bar.pixels[0].effect is Effect.SOLID
    assert all(pixel.notification is primary for pixel in bar.pixels[1:])
    assert all(pixel.effect is Effect.BLINK for pixel in bar.pixels[1:])


def test_preview_is_top_to_bottom_and_can_disable_ansi_color():
    primary = _notification("primary", 0, Effect.BLINK)
    secondary = _notification("secondary", 120, Effect.PULSE)
    bar = InovelliBlueBar.from_active([(primary, 2.0), (secondary, 1.0)])

    lines = bar.preview(color=False).splitlines()

    assert len(lines) == 7
    assert "Primary (blink, 0°)" in lines[0]
    assert "Secondary (solid, 120°)" in lines[-1]
    assert "\033[" not in bar.preview(color=False)
    assert "\033[" in bar.preview(color=True)
