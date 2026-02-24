"""WID generation."""

# pylint: disable=invalid-name,too-many-instance-attributes,unused-argument
# pyright: reportExplicitAny=false,reportAny=false,reportUnusedParameter=false
# pyright: reportConstantRedefinition=false
# flake8: noqa: C901,N803,N806

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, final


@dataclass(frozen=True, slots=True)
class WidGenState:
    """Wid generation state."""

    last_sec: int
    last_seq: int


class WidStateStore:
    """State storage interface for WidGen persistence."""

    def load(self, key: str) -> WidGenState | None:
        """Load state for key."""
        raise NotImplementedError

    def save(self, key: str, state: WidGenState) -> None:
        """Save state for key."""
        raise NotImplementedError


@final
class MemoryWidStateStore(WidStateStore):
    """In-memory Wid state store."""

    def __init__(self) -> None:
        """Initialize in-memory store."""
        self._state: dict[str, WidGenState] = {}

    def load(self, key: str) -> WidGenState | None:
        """Load state for key."""
        state = self._state.get(key)
        if state is None:
            return None
        return WidGenState(last_sec=state.last_sec, last_seq=state.last_seq)

    def save(self, key: str, state: WidGenState) -> None:
        """Save state for key."""
        self._state[key] = WidGenState(last_sec=state.last_sec, last_seq=state.last_seq)


@final
class SqliteWidStateStore(WidStateStore):
    """SQLite-backed Wid state store."""

    def __init__(self, database_path: str, prefix: str = "wid") -> None:
        """Initialize SQLite store."""
        db_file = Path(database_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_file))
        self._prefix = prefix
        q = (
            "CREATE TABLE IF NOT EXISTS wid_state ("
            "k TEXT PRIMARY KEY, "
            "last_sec INTEGER NOT NULL, "
            "last_seq INTEGER NOT NULL)"
        )
        self._conn.execute(q)
        self._conn.commit()

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    def load(self, key: str) -> WidGenState | None:
        """Load state for key."""
        row = self._conn.execute(
            "SELECT last_sec, last_seq FROM wid_state WHERE k = ?",
            (self._full_key(key),),
        ).fetchone()
        if row is None:
            return None
        last_sec = int(row[0])
        last_seq = int(row[1])
        return WidGenState(last_sec=last_sec, last_seq=last_seq)

    def save(self, key: str, state: WidGenState) -> None:
        """Save state for key."""
        q_s = (
            "INSERT INTO wid_state(k, last_sec, last_seq) VALUES(?, ?, ?) "
            "ON CONFLICT(k) DO UPDATE SET "
            "last_sec=excluded.last_sec, last_seq=excluded.last_seq"
        )
        q_p = (self._full_key(key), state.last_sec, state.last_seq)
        self._conn.execute(q_s, q_p)
        self._conn.commit()

    def close(self) -> None:
        """Close SQLite connection."""
        self._conn.close()


@final
class WidGen:
    """WID generator.

    Format:
      YYYYMMDDTHHMMSS.<seqW>Z[-<padZ>]

    Invariants:
      - (sec, seq) is monotonic for a single generator instance
      - Lexicographic monotonicity holds only when Z == 0
      - pad is lowercase hex length Z when Z > 0
    """

    max_seq: int
    last_sec: int
    last_seq: int
    _cached_sec: int
    _cached_ts: str
    _state_store: WidStateStore | None
    _state_key: str
    _auto_persist: bool

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        W: int = 4,
        Z: int = 6,
        time_unit: Literal["sec", "ms"] = "sec",
        state_store: WidStateStore | None = None,
        state_key: str = "wid",
        auto_persist: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize the generator."""
        # Backwards-compatible keyword names: accept both `W`/`Z` and `w`/`z`.
        if "w" in kwargs:
            W = int(kwargs.pop("w"))
        elif "W" in kwargs:
            W = int(kwargs.pop("W"))
        if "z" in kwargs:
            Z = int(kwargs.pop("z"))
        elif "Z" in kwargs:
            Z = int(kwargs.pop("Z"))

        if W <= 0:
            raise ValueError("W must be > 0")
        if Z < 0:
            raise ValueError("Z must be >= 0")
        if time_unit not in {"sec", "ms"}:
            raise ValueError("time_unit must be 'sec' or 'ms'")

        self.W: int = W
        self.Z: int = Z
        self.time_unit: Literal["sec", "ms"] = time_unit
        self.max_seq = 10**W - 1

        self.last_sec = 0
        self.last_seq = -1
        self._state_store = state_store
        self._state_key = state_key
        self._auto_persist = auto_persist

        self._cached_sec = -1
        self._cached_ts = ""

        if self._auto_persist and self._state_store is not None:
            loaded = self._state_store.load(self._state_key)
            if loaded is not None and loaded.last_sec >= 0 and loaded.last_seq >= -1:
                self.last_sec = loaded.last_sec
                self.last_seq = loaded.last_seq

    def _persist_state(self) -> None:
        if not self._auto_persist or self._state_store is None:
            return
        try:
            self._state_store.save(self._state_key, self.state())
        except Exception:  # pragma: no cover  # pylint: disable=broad-exception-caught
            # Keep generator functional even if persistence fails.
            return

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
        # Z hex chars => ceil(Z/2) bytes
        return os.urandom((z + 1) // 2).hex()[:z]

    def next(self) -> str:
        """Get the next id."""
        now_sec = (
            int(time.time() * 1000) if self.time_unit == "ms" else int(time.time())
        )
        sec = now_sec if now_sec > self.last_sec else self.last_sec

        seq = (self.last_seq + 1) if (sec == self.last_sec) else 0
        if seq > self.max_seq:
            sec += 1
            seq = 0

        self.last_sec, self.last_seq = sec, seq
        self._persist_state()

        ts = self._ts_for_sec(sec)
        seq_str = str(seq).zfill(self.W)

        if self.Z > 0:
            return f"{ts}.{seq_str}Z-{self._pad_hex(self.Z)}"
        return f"{ts}.{seq_str}Z"

    def next_n(self, n: int) -> list[str]:
        """Get the next number."""
        if n < 0:
            raise ValueError("n must be >= 0")
        return [self.next() for _ in range(n)]

    def state(self) -> WidGenState:
        """Get the current state."""
        return WidGenState(last_sec=self.last_sec, last_seq=self.last_seq)

    def restore_state(self, last_sec: int, last_seq: int) -> None:
        """Restore state."""
        if last_sec < 0 or last_seq < -1:
            raise ValueError("invalid state")
        self.last_sec = last_sec
        self.last_seq = last_seq
        self._persist_state()

    def __call__(self, *args: Any, **kwargs: Any) -> str:
        """Get the next ID."""
        return self.next()
