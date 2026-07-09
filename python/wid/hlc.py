"""HLC-WID generator."""

# pylint: disable=too-many-instance-attributes,invalid-name

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, final

from .core import clamp_tick
from .parse import MAX_W, MAX_Z


@dataclass(frozen=True, slots=True)
class HLCState:
    """The HLC state."""

    pt: int  # physical tick (seconds or milliseconds per the generator's unit)
    lc: int  # logical counter


@final
class HLCWidGen:
    """HLC-WID generator.

    Format:
      YYYYMMDDTHHMMSS.<lcW>Z-<node>[-<padZ>]

    Notes:
      - (pt, lc) monotonic within a node instance
      - Lexicographic monotonicity holds only when Z == 0 and node fixed
      - node is one or more ASCII alphanumerics or underscores

    """

    node: str
    max_lc: int
    pt: int
    lc: int
    _cached_sec: int
    _cached_ts: str

    def __init__(
        self,
        node: str,
        W: int = 4,
        Z: int = 0,
        time_unit: Literal["sec", "ms"] = "sec",
        *,
        w: int | None = None,  # deprecated lowercase alias for W
        z: int | None = None,  # deprecated lowercase alias for Z
    ) -> None:
        """Initialize the generator."""
        # Deprecated: lowercase w/z aliases kept for transitional compatibility.
        if w is not None:
            import warnings

            warnings.warn(
                "'w' is deprecated, use 'W' instead", DeprecationWarning, stacklevel=2
            )
            W = w  # pyright: ignore[reportConstantRedefinition]
        if z is not None:
            import warnings

            warnings.warn(
                "'z' is deprecated, use 'Z' instead", DeprecationWarning, stacklevel=2
            )
            Z = z  # pyright: ignore[reportConstantRedefinition]

        if not node or not all(c.isascii() and (c.isalnum() or c == "_") for c in node):
            raise ValueError(
                "node must be one or more ASCII alphanumerics or underscores"
            )
        # Bounds match all six implementations: W > 18 would overflow an
        # int64 logical counter; Z > 64 exceeds the C implementation's WID_MAX_Z.
        if W <= 0 or W > MAX_W:
            raise ValueError("W must be between 1 and 18")
        if Z < 0 or Z > MAX_Z:
            raise ValueError("Z must be between 0 and 64")
        if time_unit not in {"sec", "ms"}:
            raise ValueError("time_unit must be 'sec' or 'ms'")

        # Spec vocabulary casing, matching WidGen.W/WidGen.Z (this class used
        # to expose lowercase `w`/`z`; properties below keep those readable).
        self.W: int = W
        self.Z: int = Z
        self.time_unit: Literal["sec", "ms"] = time_unit
        self.node = node
        self.max_lc = 10**W - 1

        self.pt = 0
        self.lc = 0

        self._cached_sec = -1
        self._cached_ts = ""

    def _ts_for_tick(self, sec: int) -> str:
        # Saturate instead of raising from datetime.fromtimestamp: a
        # corrupted resume state degrades to a pinned timestamp.
        """Format a (clamped) seconds tick as the WID timestamp field."""
        sec = clamp_tick(sec, self.time_unit)
        if sec != self._cached_sec:
            self._cached_sec = sec
            if self.time_unit == "ms":
                sec_part = sec // 1000
                ms_part = sec % 1000
                base = datetime.fromtimestamp(sec_part, tz=timezone.utc).strftime(
                    "%Y%m%dT%H%M%S"
                )
                self._cached_ts = f"{base}{ms_part:03d}"
            else:
                self._cached_ts = datetime.fromtimestamp(sec, tz=timezone.utc).strftime(
                    "%Y%m%dT%H%M%S"
                )
        return self._cached_ts

    @staticmethod
    def _pad_hex(z: int) -> str:
        """Return Z random lowercase hex characters (empty for Z=0)."""
        return os.urandom((z + 1) // 2).hex()[:z]

    def _rollover_if_needed(self) -> None:
        """Advance the physical tick when the logical counter saturates."""
        if self.lc > self.max_lc:
            self.pt += 1
            self.lc = 0

    def observe(self, remote_pt: int, remote_lc: int) -> None:
        """Merge remote HLC state (remote_pt seconds, remote_lc counter)."""
        if remote_pt < 0 or remote_lc < 0:
            raise ValueError("remote values must be non-negative")

        now = int(time.time() * 1000) if self.time_unit == "ms" else int(time.time())
        new_pt = max(now, self.pt, remote_pt)

        if new_pt == self.pt == remote_pt:
            self.lc = max(self.lc, remote_lc) + 1
        elif new_pt == self.pt:
            self.lc += 1
        elif new_pt == remote_pt:
            self.lc = remote_lc + 1
        else:
            self.lc = 0

        self.pt = new_pt
        self._rollover_if_needed()

    def next(self) -> str:
        """Get the next id."""
        now = int(time.time() * 1000) if self.time_unit == "ms" else int(time.time())

        if now > self.pt:
            self.pt = now
            self.lc = 0
        else:
            self.lc += 1

        self._rollover_if_needed()

        ts = self._ts_for_tick(self.pt)
        lc_str = str(self.lc).zfill(self.W)

        if self.Z > 0:
            pad = self._pad_hex(self.Z)
            return f"{ts}.{lc_str}Z-{self.node}-{pad}"
        return f"{ts}.{lc_str}Z-{self.node}"

    @property
    def w(self) -> int:
        """Backwards-compatible lowercase alias for :attr:`W`."""
        return self.W

    @property
    def z(self) -> int:
        """Backwards-compatible lowercase alias for :attr:`Z`."""
        return self.Z

    def next_n(self, n: int) -> list[str]:
        """Get next n ids."""
        if n < 0:
            raise ValueError("n must be >= 0")
        return [self.next() for _ in range(n)]

    def state(self) -> HLCState:
        """Get the generator state."""
        return HLCState(pt=self.pt, lc=self.lc)

    def restore_state(self, pt: int, lc: int) -> None:
        """Restore the generator state."""
        if pt < 0 or lc < 0:
            raise ValueError("invalid state")
        self.pt = pt
        self.lc = lc
