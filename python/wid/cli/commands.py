"""Flag-mode command handlers.

next, stream, healthcheck, bench, selftest,validate, and parse.
"""

# pyright: reportUnusedCallResult=false,reportAny=false

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from ..core import parse_time_unit
from ..hlc import HLCWidGen
from ..parse import (
    MAX_W,
    MAX_Z,
    parse_hlc_wid,
    parse_wid,
    validate_hlc_wid,
    validate_wid,
)
from ..wid import WidGen

if TYPE_CHECKING:
    from collections.abc import Callable


def _resolve_z(kind: str, z: int | None) -> int:
    """HLC-WID defaults to Z=0, WID to Z=6. Explicit Z always wins."""
    if z is not None:
        return z
    return 0 if kind == "hlc" else 6


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def run_emit_mode(mode: str, argv: list[str]) -> None:
    """Handle flag-mode ``next``/``stream``: emit one or N identifiers."""
    ap = argparse.ArgumentParser(description=f"Emit WID values ({mode})")
    ap.add_argument("--kind", choices=["wid", "hlc"], default="wid")
    ap.add_argument("--W", type=int, default=_env_int("W", 4))
    ap.add_argument("--Z", type=int, default=None)
    ap.add_argument("--node", type=str, default=os.environ.get("NODE", "py"))
    ap.add_argument(
        "--time-unit",
        choices=["sec", "ms"],
        default=os.environ.get("WID_TIME_UNIT", "sec"),
    )
    ap.add_argument(
        "--count", type=int, default=0, help="0 means infinite (stream mode)"
    )
    # The sh implementation delegates its canonical A=stream (L= cadence)
    # here; this is the flag-mode spelling of that interval.
    ap.add_argument(
        "--interval-ms",
        type=int,
        default=0,
        dest="interval_ms",
        help="sleep between stream emissions in milliseconds (stream mode)",
    )
    args = ap.parse_args(argv)
    # HLC-WID defaults to Z=0 when --Z not explicitly passed.
    args.Z = _resolve_z(args.kind, args.Z)
    if args.interval_ms < 0:
        raise ValueError("--interval-ms must be >= 0")

    gen: Callable[[], str]
    g: WidGen | HLCWidGen
    effective_time_unit = parse_time_unit(args.time_unit)
    if args.kind == "wid":
        g = WidGen(w=args.W, z=args.Z, time_unit=effective_time_unit)
        gen = g.next
    else:
        g = HLCWidGen(args.node, w=args.W, z=args.Z, time_unit=effective_time_unit)
        gen = g.next

    if mode == "next":
        print(gen(), flush=True)
        return

    emitted = 0
    try:
        while args.count == 0 or emitted < args.count:
            print(gen(), flush=True)
            emitted += 1
            more = args.count == 0 or emitted < args.count
            if more and args.interval_ms > 0:
                time.sleep(args.interval_ms / 1000)
    except KeyboardInterrupt:
        sys.exit(130)


def run_healthcheck_mode(argv: list[str]) -> None:
    """Generate one sample identifier and validate its shape."""
    ap = argparse.ArgumentParser(description="Healthcheck WID/HLC generator (strict)")
    ap.add_argument("--kind", choices=["wid", "hlc"], default="wid")
    ap.add_argument("--W", type=int, default=_env_int("W", 4))
    ap.add_argument("--Z", type=int, default=None)
    ap.add_argument("--node", type=str, default=os.environ.get("NODE", "py"))
    ap.add_argument(
        "--time-unit",
        choices=["sec", "ms"],
        default=os.environ.get("WID_TIME_UNIT", "sec"),
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    # HLC-WID defaults to Z=0 when --Z not explicitly passed.
    args.Z = _resolve_z(args.kind, args.Z)

    effective_time_unit = parse_time_unit(args.time_unit)
    ok: bool = False
    if args.kind == "wid":
        sample = WidGen(w=args.W, z=args.Z, time_unit=effective_time_unit).next()
        ok = validate_wid(sample, W=args.W, Z=args.Z, time_unit=effective_time_unit)
    else:
        sample = HLCWidGen(
            args.node,
            w=args.W,
            z=args.Z,
            time_unit=effective_time_unit,
        ).next()
        ok = validate_hlc_wid(sample, W=args.W, Z=args.Z, time_unit=effective_time_unit)

    payload = {
        "ok": bool(ok),
        "kind": args.kind,
        "W": args.W,
        "Z": args.Z,
        "sample_id": sample,
        "time_unit": args.time_unit,
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    if args.json:
        print(json.dumps(payload, separators=(",", ":")))
    else:
        print(f"ok={str(payload['ok']).lower()} kind={args.kind} sample={sample}")

    if not ok:
        sys.exit(1)


def run_bench_mode(argv: list[str]) -> None:
    """Benchmark generation throughput and print ids/sec."""
    ap = argparse.ArgumentParser(description="Benchmark WID/HLC generation throughput")
    ap.add_argument("--kind", choices=["wid", "hlc"], default="wid")
    ap.add_argument("--W", type=int, default=_env_int("W", 4))
    ap.add_argument("--Z", type=int, default=None)
    ap.add_argument("--node", type=str, default=os.environ.get("NODE", "py"))
    ap.add_argument(
        "--time-unit",
        choices=["sec", "ms"],
        default=os.environ.get("WID_TIME_UNIT", "sec"),
    )
    ap.add_argument("--count", type=int, default=0, help="0 means the default 100000")
    args = ap.parse_args(argv)
    # HLC-WID defaults to Z=0 when --Z not explicitly passed.
    args.Z = _resolve_z(args.kind, args.Z)

    n = args.count if args.count > 0 else 100000
    effective_time_unit = parse_time_unit(args.time_unit)
    g: WidGen | HLCWidGen
    if args.kind == "wid":
        g = WidGen(w=args.W, z=args.Z, time_unit=effective_time_unit)
    else:
        g = HLCWidGen(args.node, w=args.W, z=args.Z, time_unit=effective_time_unit)

    start = time.perf_counter()
    for _ in range(n):
        g.next()
    seconds = max(time.perf_counter() - start, 1e-9)

    print(
        json.dumps(
            {
                "impl": "python",
                "kind": args.kind,
                "W": args.W,
                "Z": args.Z,
                "time_unit": args.time_unit,
                "n": n,
                "seconds": seconds,
                "ids_per_sec": n / seconds,
            },
            separators=(",", ":"),
        )
    )


def run_selftest_mode() -> None:
    """Run the same checks as the other implementations' selftest (silent, exit 0/1)."""
    wg = WidGen(w=4, z=0, time_unit="sec")
    a = wg.next()
    b = wg.next()
    ok = (
        a < b
        and validate_wid(a, W=4, Z=0, time_unit="sec")
        and validate_hlc_wid(
            HLCWidGen("node01", w=4, z=0, time_unit="sec").next(),
            W=4,
            Z=0,
            time_unit="sec",
        )
        and not validate_wid("20260212T091530.0000Z-node01", W=4, Z=0, time_unit="sec")
        and not validate_hlc_wid("20260212T091530.0000Z", W=4, Z=0, time_unit="sec")
        and validate_wid("20260212T091530123.0000Z", W=4, Z=0, time_unit="ms")
        and validate_hlc_wid(
            "20260212T091530123.0000Z-node01", W=4, Z=0, time_unit="ms"
        )
    )
    if not ok:
        sys.exit(1)


def _check_shape_bounds(w: int, z: int) -> None:
    """Reject out-of-range W/Z as a usage error (exit 2).

    Checked before validate/parse run so a bad parameter is not misreported
    as the id itself being invalid (exit 1) — the shared contract in
    spec/quick-usage.md "Exit codes".
    """
    if w <= 0 or w > MAX_W:
        raise ValueError("W must be between 1 and 18")
    if z < 0 or z > MAX_Z:
        raise ValueError("Z must be between 0 and 64")


def _parse_validate_flags(args: list[str]) -> tuple[str, int, int, str]:
    """Parse --kind --W --Z --time-unit flags; return (kind, W, Z, time_unit)."""
    kind = "wid"
    w = 4
    z = 6
    time_unit = "sec"
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--kind" and i + 1 < len(args):
            kind = args[i + 1]
            if kind not in ("wid", "hlc"):
                raise ValueError("--kind must be one of: wid, hlc")
            i += 2
        elif arg == "--W" and i + 1 < len(args):
            w = int(args[i + 1])
            i += 2
        elif arg == "--Z" and i + 1 < len(args):
            z = int(args[i + 1])
            i += 2
        elif arg in ("--time-unit", "--T") and i + 1 < len(args):
            time_unit = args[i + 1]
            if time_unit not in ("sec", "ms"):
                raise ValueError("time-unit must be sec or ms")
            i += 2
        elif arg in ("--kind", "--W", "--Z", "--time-unit", "--T"):
            raise ValueError(f"{arg} requires a value")
        else:
            raise ValueError(f"unknown flag: {arg}")
    _check_shape_bounds(w, z)
    return kind, w, z, time_unit


def run_validate_mode(args: list[str]) -> None:
    """Handle ``wid validate <id>`` plus --kind/--W/--Z/--time-unit flags."""
    if not args or args[0].startswith("--"):
        print("error: validate requires an id", file=sys.stderr)
        sys.exit(2)
    wid_str = args[0]
    kind, w, z, time_unit = _parse_validate_flags(args[1:])
    tu: Literal["ms", "sec"] = "ms" if time_unit == "ms" else "sec"
    if kind == "hlc":
        ok = validate_hlc_wid(wid_str, W=w, Z=z, time_unit=tu)
    else:
        ok = validate_wid(wid_str, W=w, Z=z, time_unit=tu)
    print("true" if ok else "false")
    if not ok:
        sys.exit(1)


def run_parse_mode(args: list[str]) -> None:
    """Handle ``wid parse <id>`` plus --kind/--W/--Z/--time-unit/--json flags."""
    if not args or args[0].startswith("--"):
        print("error: parse requires an id", file=sys.stderr)
        sys.exit(2)
    wid_str = args[0]
    json_out = "--json" in args
    rest = [a for a in args[1:] if a != "--json"]
    kind, w, z, time_unit = _parse_validate_flags(rest)
    tu: Literal["ms", "sec"] = "ms" if time_unit == "ms" else "sec"
    if kind == "hlc":
        result_h = parse_hlc_wid(wid_str, W=w, Z=z, time_unit=tu)
        if result_h is None:
            print(f"error: invalid hlc-wid: {wid_str}", file=sys.stderr)
            sys.exit(1)
        if json_out:
            print(
                json.dumps(
                    {
                        "raw": result_h.raw,
                        "timestamp": result_h.timestamp.isoformat(),
                        "logical_counter": result_h.logical_counter,
                        "node": result_h.node,
                        "padding": result_h.padding,
                    },
                    separators=(",", ":"),
                )
            )
        else:
            print(f"raw={result_h.raw}")
            print(f"timestamp={result_h.timestamp.isoformat()}")
            print(f"logical_counter={result_h.logical_counter}")
            print(f"node={result_h.node}")
            print(f"padding={result_h.padding or ''}")
    else:
        result = parse_wid(wid_str, W=w, Z=z, time_unit=tu)
        if result is None:
            print(f"error: invalid wid: {wid_str}", file=sys.stderr)
            sys.exit(1)
        if json_out:
            print(
                json.dumps(
                    {
                        "raw": result.raw,
                        "timestamp": result.timestamp.isoformat(),
                        "sequence": result.sequence,
                        "padding": result.padding,
                    },
                    separators=(",", ":"),
                )
            )
        else:
            print(f"raw={result.raw}")
            print(f"timestamp={result.timestamp.isoformat()}")
            print(f"sequence={result.sequence}")
            print(f"padding={result.padding or ''}")
