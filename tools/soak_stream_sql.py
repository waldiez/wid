#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from wid import parse_wid
from wid.async_api import async_next_wid


async def worker(
    *,
    worker_id: int,
    stop_at: float,
    db_path: str,
    seen: set[str],
    lock: asyncio.Lock,
    failures: list[str],
) -> int:
    count = 0
    last_key = None
    while time.time() < stop_at:
        wid = await async_next_wid(W=4, Z=0, time_unit="sec", database_path=db_path)
        parsed = parse_wid(wid, W=4, Z=0)
        if parsed is None:
            failures.append(f"worker={worker_id}: parse failed for {wid}")
            continue
        key = (int(parsed.timestamp.timestamp()), parsed.sequence)
        if last_key is not None and key <= last_key:
            failures.append(f"worker={worker_id}: non-monotonic local order: {wid}")
        last_key = key
        async with lock:
            if wid in seen:
                failures.append(f"worker={worker_id}: duplicate id: {wid}")
            seen.add(wid)
        count += 1
    return count


async def run(duration_sec: int, workers: int, db_path: str) -> tuple[int, float]:
    stop_at = time.time() + duration_sec
    seen: set[str] = set()
    lock = asyncio.Lock()
    failures: list[str] = []
    tasks = [
        asyncio.create_task(
            worker(worker_id=i, stop_at=stop_at, db_path=db_path, seen=seen, lock=lock, failures=failures)
        )
        for i in range(workers)
    ]
    counts = await asyncio.gather(*tasks)
    if failures:
        raise RuntimeError("\n".join(failures[:10]))
    total = sum(counts)
    rate = total / max(duration_sec, 1)
    return total, rate


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--duration-sec", type=int, default=30)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--db-path", default=".local/soak/wid_soak.sqlite")
    args = p.parse_args()

    Path(args.db_path).parent.mkdir(parents=True, exist_ok=True)
    total, rate = asyncio.run(run(args.duration_sec, args.workers, args.db_path))
    print(
        f'{{"ok":true,"duration_sec":{args.duration_sec},"workers":{args.workers},"total":{total},"ids_per_sec":{rate:.2f}}}'
    )


if __name__ == "__main__":
    main()
