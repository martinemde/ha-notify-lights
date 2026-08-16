from __future__ import annotations

from dataclasses import dataclass

from .const import Effect, Speed, NAMED_COLORS


@dataclass(frozen=True)
class Notification:
    """The presentation of a notification: what it looks like and what it means.

    Targets are resolved per config entry at setup time because resolving
    areas and light groups needs `hass`. A stateful notification may optionally
    bind directly to a source entity; otherwise it is controlled manually.
    """

    name: str
    display_name: str
    color: int | str
    brightness: int
    effect: Effect
    effect_speed: Speed
    duration: int
    priority: int
    # Free text explaining what this notification means. Surfaced as an entity
    # attribute so the catalog is self-documenting -- display_name doubles as
    # the UI label and cannot carry a sentence.
    description: str = ""
    state_entity: str | None = None
    active_state: str = "on"

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
        """True when the notification persists while a condition is active."""
        return self.duration == 0

    @property
    def is_source_bound(self) -> bool:
        """True when a source entity controls this notification's state."""
        return self.is_stateful and bool(self.state_entity)

    @property
    def is_manual_stateful(self) -> bool:
        """True when callers explicitly turn this notification on and off."""
        return self.is_stateful and not self.state_entity

    @property
    def is_momentary(self) -> bool:
        """True when the notification auto-clears after a fixed duration."""
        return self.duration > 0
