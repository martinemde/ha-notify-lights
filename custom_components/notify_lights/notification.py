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
