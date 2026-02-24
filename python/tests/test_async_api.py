"""Tests for async API wrappers."""

# pylint: skip-file
# pyright: reportUnusedCallResult=false, reportOptionalMemberAccess=false
# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false
# flake8: noqa: D102,D103

import asyncio
from collections.abc import AsyncIterable
from pathlib import Path

import pytest
from wid import (
    AsyncSqliteWidStateStore,
    async_hlc_wid_stream,
    async_next_hlc_wid,
    async_next_wid,
    async_wid_stream,
    parse_wid,
    validate_hlc_wid,
    validate_wid,
)
from wid.wid import WidGenState


async def _collect_async(gen: AsyncIterable[str], n: int) -> list[str]:
    out: list[str] = []
    async for item in gen:
        out.append(item)
        if len(out) >= n:
            break
    return out


def test_async_next_wid() -> None:
    wid = asyncio.run(async_next_wid(W=4, Z=6))
    assert validate_wid(wid, W=4, Z=6)


def test_async_next_hlc_wid() -> None:
    wid = asyncio.run(async_next_hlc_wid(node="node01", W=4, Z=0))
    assert validate_hlc_wid(wid, W=4, Z=0)


def test_async_wid_stream_count_and_order() -> None:
    values = asyncio.run(_collect_async(async_wid_stream(count=3, W=4, Z=0), 3))
    assert len(values) == 3
    assert values[0] < values[1] < values[2]


def test_async_hlc_stream_count_and_order() -> None:
    values = asyncio.run(
        _collect_async(async_hlc_wid_stream(node="node01", count=3, W=4, Z=0), 3)
    )
    assert len(values) == 3
    assert values[0] < values[1] < values[2]


def test_async_stream_rejects_invalid_args() -> None:
    async def _run() -> None:
        with pytest.raises(ValueError):
            async for _ in async_wid_stream(count=-1):
                pass
        with pytest.raises(ValueError):
            async for _ in async_wid_stream(count=1, interval_ms=-1):
                pass
        with pytest.raises(ValueError):
            async for _ in async_hlc_wid_stream(count=-1):
                pass
        with pytest.raises(ValueError):
            async for _ in async_hlc_wid_stream(count=1, interval_ms=-1):
                pass

    asyncio.run(_run())


def test_async_next_wid_supports_sqlite_store(tmp_path: Path) -> None:
    aiosqlite = pytest.importorskip("aiosqlite")
    _ = aiosqlite
    db_path = str(tmp_path / "wid_async_state.sqlite")

    first = asyncio.run(async_next_wid(W=4, Z=0, database_path=db_path))
    second = asyncio.run(async_next_wid(W=4, Z=0, database_path=db_path))

    first_parsed = parse_wid(first, W=4, Z=0)
    second_parsed = parse_wid(second, W=4, Z=0)
    assert first_parsed is not None
    assert second_parsed is not None
    assert (second_parsed.timestamp, second_parsed.sequence) > (
        first_parsed.timestamp,
        first_parsed.sequence,
    )


def test_async_sqlite_store_roundtrip(tmp_path: Path) -> None:
    aiosqlite = pytest.importorskip("aiosqlite")
    _ = aiosqlite
    db_path = str(tmp_path / "wid_async_store.sqlite")
    store = AsyncSqliteWidStateStore(db_path, "wid-test")

    async def _run() -> None:
        await store.save("state-1", state=WidGenState(last_sec=10, last_seq=4))
        loaded = await store.load("state-1")
        assert loaded is not None
        assert loaded.last_sec == 10
        assert loaded.last_seq == 4

    asyncio.run(_run())
