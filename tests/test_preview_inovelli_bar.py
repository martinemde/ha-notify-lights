"""Tests for the Inovelli Blue terminal preview helper."""

import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PREVIEW_SCRIPT = REPOSITORY_ROOT / "scripts" / "preview_inovelli_bar.py"


def test_preview_script_shows_priority_layers_and_z2m_commands():
    result = subprocess.run(
        [
            sys.executable,
            str(PREVIEW_SCRIPT),
            "urgent:red:90:pulse:fast",
            "ready:green:20:blink:slow:75",
            "--no-color",
            "--commands",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    lines = result.stdout.splitlines()
    assert len([line for line in lines if line.startswith("│")]) == 7
    assert "Urgent (pulse, 0°)" in lines[0]
    assert "Ready (solid, 120°)" in lines[6]
    assert '"effect":"clear_effect"' in result.stdout
    assert '"led":"1","effect":"solid","color":85,"level":75' in result.stdout
    assert '"led_effect":{"effect":"pulse","color":0,"level":100' in result.stdout
    assert '"led":"7","effect":"clear_effect"' in result.stdout


def test_preview_script_reports_invalid_notification():
    result = subprocess.run(
        [sys.executable, str(PREVIEW_SCRIPT), "missing-fields"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "expected NAME:COLOR:PRIORITY" in result.stderr
