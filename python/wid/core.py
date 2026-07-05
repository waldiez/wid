"""Shared core helpers: time-unit parsing and tick clamping."""

from __future__ import annotations

from typing import Literal

TimeUnitName = Literal["sec", "ms"]

# Largest second tick that still formats as a 4-digit year
# (9999-12-31T23:59:59Z).
MAX_SEC_TICK = 253_402_300_799


def clamp_tick(tick: int, time_unit: TimeUnitName) -> int:
    """Saturate a tick to the formattable range.

    A corrupted resume state (e.g. a hand-edited SQL row) degrades to a
    pinned timestamp instead of raising from ``datetime.fromtimestamp``,
    matching the Rust implementation.
    """
    max_tick = MAX_SEC_TICK * 1000 + 999 if time_unit == "ms" else MAX_SEC_TICK
    return min(max(tick, 0), max_tick)


def parse_time_unit(value: str) -> TimeUnitName:
    """Normalize a time-unit argument to ``'sec'`` or ``'ms'``.

    Raises ``ValueError`` (a usage error, CLI exit 2) for anything else.
    """
    v = value.strip().lower()
    if v == "sec":
        return "sec"
    if v == "ms":
        return "ms"
    raise ValueError("time_unit must be 'sec' or 'ms'")
