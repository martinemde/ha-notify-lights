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
    OPEN_CLOSE = "open_close"
    SMALL_TO_BIG = "small_to_big"
    # slow_siren and fast_siren in Zigbee2MQTT: one effect with a speed, the
    # way blink is. There is no medium_siren; medium renders as fast.
    SIREN = "siren"


class Speed(StrEnum):
    SLOW = "slow"
    MEDIUM = "medium"
    FAST = "fast"


# Effects with no speed to choose. Solid has no animation to run at a rate;
# pulse and aurora are single values in the Zigbee2MQTT led_effect enum, so
# picking a speed for them would change nothing on the only hardware there
# is an adapter for. Their light-entity effect name is bare. Move one out of
# here if an adapter ever renders its speeds differently.
SPEEDLESS_EFFECTS = frozenset(
    {
        Effect.SOLID,
        Effect.PULSE,
        Effect.AURORA,
        Effect.OPEN_CLOSE,
        Effect.SMALL_TO_BIG,
    }
)


class Activation(StrEnum):
    """How a notification rule becomes active."""

    STATE_WHILE = "state_while"
    STATE_ENTERED = "state_entered"
    MANUAL_WHILE = "manual_while"
    MANUAL_TIMED = "manual_timed"


class DisplayMode(StrEnum):
    """How much of a device's notification surface a rule should use."""

    FULL = "full"
    INDICATOR = "indicator"


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
DEFAULT_COLOR = "blue"
DEFAULT_EFFECT = Effect.SOLID
DEFAULT_SPEED = Speed.MEDIUM
DEFAULT_PRIORITY = 50

# What a notification looks like now lives on its light entity, not in the
# options flow. These are the fields that entity owns and writes back.
APPEARANCE_FIELDS = frozenset({"color", "brightness", "effect", "effect_speed"})
