"""Pure model of the seven-pixel notification bar on Inovelli Blue devices."""

from __future__ import annotations

import colorsys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from ..const import Effect

if TYPE_CHECKING:
    from ..active_set import ActiveEntry
    from ..notification import Notification


LED_COUNT = 7


@dataclass(frozen=True)
class BarPixel:
    """One physical pixel and the notification currently occupying it."""

    led: int
    notification: Notification
    effect: Effect


@dataclass(frozen=True)
class InovelliBlueBar:
    """Desired bottom-to-top layout of an Inovelli Blue LED bar.

    One notification owns the full bar. When at least two are active, the
    second-highest priority notification remains visible as a solid pixel at
    the bottom while the highest priority notification owns the other six.
    Notifications below the first two remain in the coordinator's stack but
    are not visible until one of those two is removed.
    """

    pixels: tuple[BarPixel | None, ...]

    def __post_init__(self) -> None:
        if len(self.pixels) != LED_COUNT:
            raise ValueError(f"An Inovelli Blue bar has {LED_COUNT} pixels")
        for expected_led, pixel in enumerate(self.pixels, start=1):
            if pixel is not None and pixel.led != expected_led:
                raise ValueError("Pixels must be ordered from LED 1 through LED 7")

    @classmethod
    def from_active(cls, active: list[ActiveEntry]) -> InovelliBlueBar:
        """Build a layout from priority-sorted active entries."""
        if not active:
            return cls((None,) * LED_COUNT)

        primary = active[0][0]
        pixels = [
            BarPixel(led=led, notification=primary, effect=primary.effect)
            for led in range(1, LED_COUNT + 1)
        ]
        if len(active) > 1:
            secondary = active[1][0]
            pixels[0] = BarPixel(
                led=1,
                notification=secondary,
                effect=Effect.SOLID,
            )
        return cls(tuple(pixels))

    @property
    def is_empty(self) -> bool:
        return all(pixel is None for pixel in self.pixels)

    @property
    def is_layered(self) -> bool:
        """Return whether more than one notification is visible."""
        return len({id(pixel.notification) for pixel in self.pixels if pixel}) > 1

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
                    f"{pixel.notification.display_name} "
                    f"({pixel.effect.value}, {hue}°)"
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
