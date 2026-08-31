"""Pure model of the seven-pixel notification bar on Inovelli Blue devices."""

from __future__ import annotations

import colorsys
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..const import DisplayMode, Effect

if TYPE_CHECKING:
    from ..active_set import ActiveEntry
    from ..notification import Notification


LED_COUNT = 7
MINOR_PRIORITY_MAX = 30


def _uses_single_pixel(notification: Notification) -> bool:
    """Return whether a notification has a one-pixel stack footprint."""
    return (
        notification.display_mode is DisplayMode.INDICATOR
        or notification.priority <= MINOR_PRIORITY_MAX
    )


@dataclass(frozen=True)
class BarPixel:
    """One physical pixel and the notification currently occupying it."""

    led: int
    notification: Notification
    effect: Effect
    activated_at: float


@dataclass(frozen=True)
class InovelliBlueBar:
    """Desired bottom-to-top layout of an Inovelli Blue LED bar.

    Full-bar notifications occupy the available bar. Indicator notifications
    intentionally occupy one bottom pixel even when they are the only active
    rule. At most the two highest-priority notifications are visible; lower
    entries remain in the coordinator stack until a visible one clears.
    """

    pixels: tuple[BarPixel | None, ...]
    full_bar: BarPixel | None = None

    def __post_init__(self) -> None:
        if len(self.pixels) != LED_COUNT:
            raise ValueError(f"An Inovelli Blue bar has {LED_COUNT} pixels")
        if self.full_bar is not None and self.full_bar.led != 1:
            raise ValueError("The full-bar layer uses LED 1 as its placeholder")
        for expected_led, pixel in enumerate(self.pixels, start=1):
            if pixel is not None and pixel.led != expected_led:
                raise ValueError("Pixels must be ordered from LED 1 through LED 7")

    @classmethod
    def from_active(cls, active: list[ActiveEntry]) -> InovelliBlueBar:
        """Build a layout from priority-sorted active entries."""
        if not active:
            return cls((None,) * LED_COUNT)

        visible = active[:2]
        pixels: list[BarPixel | None] = [None] * LED_COUNT
        primary_full_index = next(
            (
                index
                for index, (notification, _activated_at) in enumerate(visible)
                if not _uses_single_pixel(notification)
            ),
            None,
        )
        full_bar = None
        if primary_full_index is not None:
            primary_full, primary_activated_at = visible[primary_full_index]
            full_bar = BarPixel(
                led=1,
                notification=primary_full,
                effect=primary_full.effect,
                activated_at=primary_activated_at,
            )
            pixels = [
                BarPixel(
                    led=led,
                    notification=primary_full,
                    effect=primary_full.effect,
                    activated_at=primary_activated_at,
                )
                for led in range(1, LED_COUNT + 1)
            ]

        next_indicator_led = 1
        for index, (notification, activated_at) in enumerate(visible):
            if index == primary_full_index:
                continue
            pixels[next_indicator_led - 1] = BarPixel(
                led=next_indicator_led,
                notification=notification,
                # Explicit indicators retain their effect. Full-bar rules that
                # have been squashed to one pixel use the same stable summary
                # as an ordinary backgrounded notification.
                effect=(
                    notification.effect
                    if notification.display_mode is DisplayMode.INDICATOR
                    else Effect.SOLID
                ),
                activated_at=activated_at,
            )
            next_indicator_led += 1
        return cls(tuple(pixels), full_bar)

    @property
    def is_empty(self) -> bool:
        return all(pixel is None for pixel in self.pixels)

    @property
    def is_layered(self) -> bool:
        """Return whether more than one notification is visible."""
        return (
            len(
                {
                    (id(pixel.notification), pixel.activated_at)
                    for pixel in self.pixels
                    if pixel
                }
            )
            > 1
        )

    @property
    def uses_individual_leds(self) -> bool:
        """Return whether this layout cannot use one native full-bar command."""
        return not self.is_empty and (
            self.is_layered or any(pixel is None for pixel in self.pixels)
        )

    @property
    def individual_pixels(self) -> tuple[BarPixel | None, ...]:
        """Return only the pixels that override the native full-bar layer."""
        full_bar = self.full_bar
        if full_bar is None:
            return self.pixels
        return tuple(
            None
            if pixel is not None
            and pixel.notification is full_bar.notification
            and pixel.activated_at == full_bar.activated_at
            else pixel
            for pixel in self.pixels
        )

    def top_to_bottom(self) -> Iterable[BarPixel | None]:
        """Iterate in the same orientation as a wall-mounted switch."""
        return reversed(self.pixels)

    def preview(self, *, color: bool = True) -> str:
        """Render a compact terminal preview of the bar."""
        lines: list[str] = []
        for pixel in self.top_to_bottom():
            if pixel is None:
                block = "·"
                label = "empty"
            else:
                hue = int(pixel.notification.color)
                block = _color_block(hue) if color else "█"
                label = (
                    f"{pixel.notification.display_name} ({pixel.effect.value}, {hue}°)"
                )
            lines.append(f"│ {block} │ {label}")
        return "\n".join(lines)


def _color_block(hue: int) -> str:
    """Return a true-color ANSI block for a hue in degrees."""
    # Inovelli reserves hue 360 for white.
    if hue == 360:
        red, green, blue = 255, 255, 255
    else:
        red_f, green_f, blue_f = colorsys.hsv_to_rgb(hue / 360, 1, 1)
        red, green, blue = (
            round(red_f * 255),
            round(green_f * 255),
            round(blue_f * 255),
        )
    return f"\033[38;2;{red};{green};{blue}m█\033[0m"
