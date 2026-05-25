from enum import StrEnum

DOMAIN = "notify_lights"


class Effect(StrEnum):
    SOLID = "solid"
    BLINK = "blink"
    PULSE = "pulse"
    CHASE = "chase"
    FALLING = "falling"
    RISING = "rising"
    AURORA = "aurora"


class Speed(StrEnum):
    SLOW = "slow"
    MEDIUM = "medium"
    FAST = "fast"


NAMED_COLORS: dict[str, int] = {
    "red": 0,
    "orange": 21,
    "yellow": 60,
    "green": 120,
    "cyan": 180,
    "blue": 240,
    "purple": 270,
    "magenta": 300,
    "white": 360,
}

DEFAULT_BRIGHTNESS = 100
DEFAULT_SPEED = Speed.MEDIUM
DEFAULT_PRIORITY = 50
