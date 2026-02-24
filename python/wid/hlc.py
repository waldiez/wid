"""HLC-WID generator."""

# pylint: disable=too-many-instance-attributes,invalid-name
# flake8: noqa: C901, E501, N803, N806

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, final


@dataclass(frozen=True, slots=True)
class HLCState:
    """The HLC state."""

    pt: int  # physical time (sec)
    lc: int  # logical counter


@final
class HLCWidGen:
    """HLC-WID generator.

    Format:
      YYYYMMDDTHHMMSS.<lcW>Z-<node>[-<padZ>]

    Notes:
      - (pt, lc) monotonic within a node instance
      - Lexicographic monotonicity holds only when Z == 0 and node fixed
      - node is a non-empty token with no whitespace and no hyphen

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
        **kwargs: Any,
    ) -> None:
        """Initialize the generator."""
        # Backwards-compatible keyword names: accept `w`/`w` from callers
        if "w" in kwargs:
            W = int(kwargs.pop("w"))  # pyright: ignore[reportConstantRedefinition]
        if "Z" in kwargs:
            Z = int(kwargs.pop("z"))  # pyright: ignore[reportConstantRedefinition]

        if not node or any(c.isspace() for c in node) or "-" in node:
            raise ValueError("node must be a non-empty token (no whitespace or '-')")
        if W <= 0:
            raise ValueError("W must be > 0")
        if Z < 0:
            raise ValueError("Z must be >= 0")
        if time_unit not in {"sec", "ms"}:
            raise ValueError("time_unit must be 'sec' or 'ms'")

        self.w: int = W
        self.z: int = Z
        self.time_unit: Literal["sec", "ms"] = time_unit
        self.node = node
        self.max_lc = 10**W - 1

        self.pt = 0
        self.lc = 0

        self._cached_sec = -1
        self._cached_ts = ""

    def _ts_for_sec(self, sec: int) -> str:
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
        return os.urandom((z + 1) // 2).hex()[:z]

    def _rollover_if_needed(self) -> None:
        if self.lc > self.max_lc:
            self.pt += 1
            self.lc = 0

    def observe(self, remote_pt: int, remote_lc: int) -> None:
        """Merge remote HLC state (remote_pt is seconds, remote_lc is logical counter)."""
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

        ts = self._ts_for_sec(self.pt)
        lc_str = str(self.lc).zfill(self.w)

        if self.z > 0:
            pad = self._pad_hex(self.z)
            return f"{ts}.{lc_str}Z-{self.node}-{pad}"
        return f"{ts}.{lc_str}Z-{self.node}"

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
