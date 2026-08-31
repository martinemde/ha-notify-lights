"""Tests for the hardware-independent Inovelli Blue bar model."""

from custom_components.notify_lights.adapters.inovelli_blue_bar import (
    InovelliBlueBar,
)
from custom_components.notify_lights.const import DisplayMode, Effect, Speed
from custom_components.notify_lights.notification import Notification


def _notification(
    name: str,
    color: int,
    effect: Effect,
    priority: int = 50,
    display_mode: DisplayMode = DisplayMode.FULL,
):
    return Notification(
        name=name,
        display_name=name.title(),
        color=color,
        brightness=80,
        effect=effect,
        effect_speed=Speed.MEDIUM,
        duration=0,
        priority=priority,
        display_mode=display_mode,
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
    secondary = _notification("secondary", 120, Effect.PULSE, priority=40)

    bar = InovelliBlueBar.from_active(
        [
            (primary, 2.0),
            (secondary, 1.0),
        ]
    )

    assert bar.is_layered
    assert bar.pixels[0].notification is secondary
    assert bar.pixels[0].effect is Effect.SOLID
    assert all(pixel.notification is primary for pixel in bar.pixels[1:])
    assert all(pixel.effect is Effect.BLINK for pixel in bar.pixels[1:])
    assert bar.full_bar.notification is primary
    assert bar.individual_pixels[0].notification is secondary
    assert all(pixel is None for pixel in bar.individual_pixels[1:])


def test_priority_30_is_always_one_pixel_even_when_configured_full():
    minor = _notification("cooling", 240, Effect.PULSE, priority=30)

    bar = InovelliBlueBar.from_active([(minor, 1.0)])

    assert bar.uses_individual_leds
    assert bar.pixels[0].notification is minor
    assert bar.pixels[0].effect is Effect.SOLID
    assert all(pixel is None for pixel in bar.pixels[1:])


def test_priority_31_can_still_fill_the_bar():
    notification = _notification("normal", 240, Effect.PULSE, priority=31)

    bar = InovelliBlueBar.from_active([(notification, 1.0)])

    assert all(pixel.notification is notification for pixel in bar.pixels)


def test_two_minor_notifications_stack_as_two_pixels():
    higher = _notification("cooling", 240, Effect.PULSE, priority=30)
    lower = _notification("occupied", 120, Effect.SOLID, priority=20)

    bar = InovelliBlueBar.from_active([(higher, 2.0), (lower, 1.0)])

    assert bar.pixels[0].notification is higher
    assert bar.pixels[1].notification is lower
    assert all(pixel is None for pixel in bar.pixels[2:])
    assert bar.full_bar is None
    assert bar.individual_pixels == bar.pixels


def test_duplicate_minor_notification_instances_remain_individual_layers():
    minor = _notification("heating", 0, Effect.SOLID, priority=20)

    bar = InovelliBlueBar.from_active([(minor, 2.0), (minor, 1.0)])

    assert bar.full_bar is None
    assert bar.individual_pixels[:2] == bar.pixels[:2]


def test_single_indicator_uses_only_bottom_pixel():
    indicator = _notification(
        "bedrooms heating",
        0,
        Effect.PULSE,
        display_mode=DisplayMode.INDICATOR,
    )

    bar = InovelliBlueBar.from_active([(indicator, 1.0)])

    assert bar.uses_individual_leds
    assert bar.pixels[0].notification is indicator
    assert bar.pixels[0].effect is Effect.PULSE
    assert all(pixel is None for pixel in bar.pixels[1:])


def test_indicator_stays_at_bottom_with_lower_priority_full_bar():
    indicator = _notification(
        "urgent indicator",
        0,
        Effect.PULSE,
        priority=90,
        display_mode=DisplayMode.INDICATOR,
    )
    full = _notification("charging", 120, Effect.SOLID, priority=50)

    bar = InovelliBlueBar.from_active([(indicator, 2.0), (full, 1.0)])

    assert bar.pixels[0].notification is indicator
    assert all(pixel.notification is full for pixel in bar.pixels[1:])


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
