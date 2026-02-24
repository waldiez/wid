"""Compatibility core surface for CLI and shared helpers."""

# pylint: disable=too-few-public-methods
# pyright: reportReturnType=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, final

TimeUnitName = Literal["sec", "ms"]


@dataclass(frozen=True, slots=True)
class _TimeUnit:
    value: TimeUnitName

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return self.__str__()


@final
class WidCore:
    """Minimal compatibility namespace used by CLI canonical flows."""

    class TimeUnit:
        """Time Unit."""

        SEC = _TimeUnit("sec")
        MS = _TimeUnit("ms")

        @staticmethod
        def from_string(value: str) -> TimeUnitName:
            """Parse a string."""
            v = value.strip().lower()
            if v in {"sec", "ms"}:
                return v  # type: ignore[return-value]
            raise ValueError("time_unit must be 'sec' or 'ms'")

        @staticmethod
        def as_string(value: TimeUnitName | _TimeUnit) -> str:
            """Get the string representation of a time unit."""
            if isinstance(value, _TimeUnit):
                return value.value
            return value

        def __str__(self) -> str:
            """Get the string representation of a time unit."""
            return f"<TimeUnit sec:{self.SEC}, ms:{self.MS}/>"

        def __repr__(self) -> str:
            """Get the string representation of a time unit."""
            return self.__str__()
