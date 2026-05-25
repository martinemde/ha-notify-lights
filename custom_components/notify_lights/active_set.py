from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .notification import Notification

# (Notification, activated_at)
ActiveEntry = tuple["Notification", float]


def compute_active_set(entries: list[ActiveEntry]) -> list[ActiveEntry]:
    """Return entries sorted by priority ordering rules.

    Order: highest priority first, momentary before stateful at equal
    priority, most recently activated first when all else is equal.
    """
    return sorted(entries, key=_sort_key)


def _sort_key(entry: ActiveEntry) -> tuple[int, int, float]:
    notification, activated_at = entry
    return (
        -notification.priority,
        0 if notification.is_momentary else 1,
        -activated_at,
    )
