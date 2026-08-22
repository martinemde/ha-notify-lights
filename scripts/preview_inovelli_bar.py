#!/usr/bin/env python3
"""Preview layered Inovelli Blue notifications and their Z2M commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the repository importable when this file is invoked as a script.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from custom_components.notify_lights.active_set import compute_active_set  # noqa: E402
from custom_components.notify_lights.adapters.inovelli_blue_bar import (  # noqa: E402
    InovelliBlueBar,
)
from custom_components.notify_lights.adapters.inovelli_blue_z2m import (  # noqa: E402
    build_z2m_render_payloads,
)
from custom_components.notify_lights.const import Effect, Speed  # noqa: E402
from custom_components.notify_lights.notification import Notification  # noqa: E402


NOTIFICATION_FORMAT = "NAME:COLOR:PRIORITY[:EFFECT[:SPEED[:BRIGHTNESS]]]"


def parse_notification(value: str) -> Notification:
    """Parse one compact notification definition from the command line."""
    fields = value.split(":")
    if not 3 <= len(fields) <= 6:
        raise argparse.ArgumentTypeError(f"expected {NOTIFICATION_FORMAT}")

    name, color_value, priority_value = fields[:3]
    try:
        color: int | str = int(color_value)
    except ValueError:
        color = color_value

    try:
        effect = Effect(fields[3]) if len(fields) >= 4 else Effect.SOLID
        speed = Speed(fields[4]) if len(fields) >= 5 else Speed.MEDIUM
        brightness = int(fields[5]) if len(fields) >= 6 else 100
        priority = int(priority_value)
        return Notification(
            name=name,
            display_name=name.replace("_", " ").title(),
            color=color,
            brightness=brightness,
            effect=effect,
            effect_speed=speed,
            duration=0,
            priority=priority,
        )
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview the seven-pixel bar produced by an active stack.",
        epilog=(
            "Example: %(prog)s urgent:red:90:pulse:fast "
            "hvac:blue:30:solid"
        ),
    )
    parser.add_argument(
        "notifications",
        metavar=NOTIFICATION_FORMAT,
        nargs="+",
        type=parse_notification,
        help="active notification; named colors or hue degrees are accepted",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="render plain blocks without ANSI true color",
    )
    parser.add_argument(
        "--commands",
        action="store_true",
        help="also print the MQTT payload sequence as JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Later arguments are treated as more recently activated for equal-priority
    # ties, matching coordinator ordering.
    active = compute_active_set([
        (notification, float(index))
        for index, notification in enumerate(args.notifications)
    ])
    bar = InovelliBlueBar.from_active(active)
    print(bar.preview(color=not args.no_color))

    if args.commands:
        print("\nZigbee2MQTT payloads:")
        for payload in build_z2m_render_payloads(active):
            print(json.dumps(payload, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
