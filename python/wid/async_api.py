"""Async convenience API built on top of sync generators."""

# flake8: noqa: C901, E501, N803, N806
# pylint: disable=invalid-name

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from .hlc import HLCWidGen
from .wid import WidGen, WidGenState

if TYPE_CHECKING:

    from collections.abc import AsyncIterator
    from typing import Any


def _parse_time_unit(value: str) -> Literal["sec", "ms"]:
    if value not in {"sec", "ms"}:
        raise ValueError("time_unit must be 'sec' or 'ms'")
    return cast(Literal["sec", "ms"], value)


class AsyncSqliteWidStateStore:
    """`aiosqlite` backed state store for async code paths."""

    def __init__(self, database_path: str, prefix: str = "wid") -> None:
        """Create an async SQLite state store."""
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._prefix = prefix

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def _connect(self) -> Any:
        try:
            import aiosqlite  # pylint: disable=import-outside-toplevel
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError(
                "aiosqlite is required for async SQLite state. Install with: pip install aiosqlite"
            ) from exc
        conn = await aiosqlite.connect(str(self._database_path))
        q = (
            "CREATE TABLE IF NOT EXISTS wid_state ("
            "k TEXT PRIMARY KEY, "
            "last_sec INTEGER NOT NULL, "
            "last_seq INTEGER NOT NULL)"
        )
        await conn.execute(q)
        await conn.commit()
        return conn

    async def load(self, key: str) -> WidGenState | None:
        """Load state for key."""
        conn = await self._connect()
        try:
            async with conn.execute(
                "SELECT last_sec, last_seq FROM wid_state WHERE k=?",
                (self._full_key(key),),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            return WidGenState(last_sec=int(row[0]), last_seq=int(row[1]))
        finally:
            await conn.close()

    async def save(self, key: str, state: WidGenState) -> None:
        """Save state for key."""
        conn = await self._connect()
        try:
            q_s =(
                "INSERT INTO wid_state(k, last_sec, last_seq) VALUES(?, ?, ?) "
                "ON CONFLICT(k) DO UPDATE SET "
                "last_sec=excluded.last_sec, last_seq=excluded.last_seq"
            )
            q_p = (self._full_key(key), state.last_sec, state.last_seq)
            await conn.execute(q_s, q_p)
            await conn.commit()
        finally:
            await conn.close()

    async def next_wid(
        self, *, key: str = "wid", w: int = 4, z: int = 6, time_unit: str = "sec"
    ) -> str:
        """Allocate one next WID with SQL compare-and-swap semantics."""
        full_key = self._full_key(key)
        conn = await self._connect()
        try:
            await conn.execute(
                "INSERT OR IGNORE INTO wid_state(k,last_sec,last_seq) VALUES(?,0,-1)",
                (full_key,),
            )
            await conn.commit()
            while True:
                async with conn.execute(
                    "SELECT last_sec,last_seq FROM wid_state WHERE k=?",
                    (full_key,),
                ) as cur:
                    row = await cur.fetchone()
                if row is None:
                    raise RuntimeError("sql state row missing")
                last_sec = int(row[0])
                last_seq = int(row[1])
                gen = WidGen(w=w, z=z, time_unit=_parse_time_unit(time_unit))
                gen.restore_state(last_sec, last_seq)
                out = gen.next()
                st = gen.state()
                q_s = (
                    "UPDATE wid_state SET last_sec=?,last_seq=? "
                    "WHERE k=? AND last_sec=? AND last_seq=?"
                )
                q_p = (st.last_sec, st.last_seq, full_key, last_sec, last_seq)
                cur2 = await conn.execute(q_s, q_p)
                await conn.commit()
                if cur2.rowcount == 1:
                    return out
                await asyncio.sleep(0)
        finally:
            await conn.close()


async def async_next_wid(W: int = 4, Z: int = 6, **kwargs: Any) -> str:
    """Get one WID in async contexts."""
    if "w" in kwargs:
        W = int(kwargs.pop("w"))  # pyright: ignore[reportConstantRedefinition]
    if "z" in kwargs:
        Z = int(kwargs.pop("z"))  # pyright: ignore[reportConstantRedefinition]
    database_path = kwargs.pop("database_path", None)
    if database_path is None:
        return WidGen(W, Z).next()
    prefix = str(kwargs.pop("prefix", "wid"))
    state_key = str(kwargs.pop("state_key", "wid"))
    time_unit = str(kwargs.pop("time_unit", "sec"))
    store = AsyncSqliteWidStateStore(str(database_path), prefix=prefix)
    return await store.next_wid(
        key=state_key, w=W, z=Z, time_unit=_parse_time_unit(time_unit)
    )


async def async_next_hlc_wid(node: str = "py", w: int = 4, z: int = 0, **kwargs: Any) -> str:
    """Get one HLC-WID in async contexts."""
    if "W" in kwargs:
        w = int(kwargs.pop("W"))
    if "Z" in kwargs:
        z = int(kwargs.pop("Z"))
    return HLCWidGen(node, w=w, z=z).next()


async def async_wid_stream(
    *,
    count: int = 0,
    w: int = 4,
    z: int = 6,
    interval_ms: int = 0,
    **kwargs: Any,
) -> AsyncIterator[str]:
    """Stream WIDs asynchronously.

    count=0 means infinite stream.
    """
    if count < 0:
        raise ValueError("count must be >= 0")
    if interval_ms < 0:
        raise ValueError("interval_ms must be >= 0")

    if "W" in kwargs:
        w = int(kwargs.pop("W"))
    if "Z" in kwargs:
        z = int(kwargs.pop("Z"))
    database_path = kwargs.pop("database_path", None)
    prefix = str(kwargs.pop("prefix", "wid"))
    state_key = str(kwargs.pop("state_key", "wid"))
    time_unit = str(kwargs.pop("time_unit", "sec"))
    parsed_time_unit = _parse_time_unit(time_unit)
    store = (
        AsyncSqliteWidStateStore(str(database_path), prefix=prefix)
        if database_path is not None
        else None
    )
    gen = WidGen(w=w, z=z, time_unit=parsed_time_unit) if store is None else None
    emitted = 0
    while count == 0 or emitted < count:
        if store is not None:
            yield await store.next_wid(
                key=state_key, w=w, z=z, time_unit=parsed_time_unit
            )
        else:
            assert gen is not None
            yield gen.next()
        emitted += 1
        if interval_ms > 0:
            await asyncio.sleep(interval_ms / 1000.0)


async def async_hlc_wid_stream(
    *,
    node: str = "py",
    count: int = 0,
    W: int = 4,
    Z: int = 0,
    interval_ms: int = 0,
    **kwargs: Any,
) -> AsyncIterator[str]:
    """Stream HLC-WIDs asynchronously.

    count=0 means infinite stream.
    """
    if count < 0:
        raise ValueError("count must be >= 0")
    if interval_ms < 0:
        raise ValueError("interval_ms must be >= 0")

    if "w" in kwargs:
        W = int(kwargs.pop("w")) # pyright: ignore[reportConstantRedefinition]
    if "z" in kwargs:
        Z = int(kwargs.pop("z")) # pyright: ignore[reportConstantRedefinition]
    gen = HLCWidGen(node, W=W, Z=Z)
    emitted = 0
    while count == 0 or emitted < count:
        yield gen.next()
        emitted += 1
        if interval_ms > 0:
            await asyncio.sleep(interval_ms / 1000.0)
