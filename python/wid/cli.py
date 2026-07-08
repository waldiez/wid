#!/usr/bin/env python3
"""CLI entrypoints for emit, stream, and healthcheck modes."""

# pyright: reportUnusedCallResult=false,reportAny=false
# Deliberate patterns, not oversights: cryptography imports stay inside the
# sign/verify handlers so the core CLI works without the optional extra, and
# the canonical dispatcher is one long function on purpose (it mirrors the
# other five implementations' dispatch tables).

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TextIO

from .core import parse_time_unit
from .hlc import HLCWidGen
from .parse import (
    MAX_W,
    MAX_Z,
    parse_hlc_wid,
    parse_wid,
    validate_hlc_wid,
    validate_wid,
)
from .wid import WidGen

if TYPE_CHECKING:
    from collections.abc import Callable

CANONICAL_KEYS = {
    "W",
    "A",
    "L",
    "D",
    "I",
    "E",
    "Z",
    "T",
    "R",
    "M",
    "N",
    "WID",
    "KEY",
    "SIG",
    "DATA",
    "OUT",
    "MODE",
    "CODE",
    "DIGITS",
    "MAX_AGE_SEC",
    "MAX_FUTURE_SEC",
}
# Core transports only. The service layer (daemons, MQTT/WS/Redis adapters)
# lives exclusively in the Rust implementation -- see spec/SERVICES.md.
TRANSPORTS = {"null", "stdout", "auto"}


def _resolve_z(kind: str, z: int | None) -> int:
    """HLC-WID defaults to Z=0, WID to Z=6. Explicit Z always wins."""
    if z is not None:
        return z
    return 0 if kind == "hlc" else 6


def _print_actions() -> None:
    """Print the canonical action matrix (A=...)."""
    print("""wid action matrix

Core ID:
  A=next | A=stream | A=healthcheck
  A=sign | A=verify | A=w-otp

Services (Rust implementation only -- see spec/SERVICES.md):
  A=start | A=stop | A=status | A=logs | A=run | A=discover | A=scaffold
  A=saf | A=saf-wid | A=wir | A=wism | A=wihp | A=wipr | A=duplex

Help:
  A=help-actions

State mode:
  E=state | E=stateless | E=sql
""")


def _print_usage(stream: TextIO = sys.stdout) -> None:
    """Print CLI usage to ``stream`` (stdout for help, stderr on error)."""
    print(
        """wid python CLI

Usage:
  python -m wid [next|stream|healthcheck|help-actions] [options]
  python -m wid A=<action> W=<n> Z=<n> ...

Commands:
  next         Emit one ID.
  stream       Emit IDs continuously (or until --count).
  validate     Validate an ID string.
  parse        Parse an ID string.
  healthcheck  Generate one sample and validate format.
  bench        Benchmark generation throughput.
  selftest     Run built-in sanity checks (silent, exit 0/1).
  help-actions Show canonical action matrix (A=...).
  sign         Canonical mode only:
               A=sign WID=<wid> KEY=<priv.pem> [DATA=<path>] [OUT=<path>].
  verify       Canonical mode only:
               A=verify WID=<wid> KEY=<pub.pem> SIG=<sig> [DATA=<path>].
  w-otp        Canonical mode only:
               A=w-otp MODE=gen|verify KEY=<secret|path> [WID=<wid>]
               [CODE=<otp>] [DIGITS=<n>] [MAX_AGE_SEC=<n>] [MAX_FUTURE_SEC=<n>].

Examples:
  python -m wid next
  python -m wid stream --kind wid --W 4 --Z 0
  python -m wid healthcheck --kind hlc --W 4 --Z 0 --node edge01
  python -m wid A=next W=4 Z=0 T=sec
""",
        file=stream,
    )


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _run_emit_mode(mode: str, argv: list[str]) -> None:
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
    if args.kind == "hlc" and not any(a in ("--Z", "-Z") for a in argv):
        args.Z = 0
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


def _run_healthcheck_mode(argv: list[str]) -> None:
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
    if args.kind == "hlc" and not any(a in ("--Z", "-Z") for a in argv):
        args.Z = 0
    # HLC-WID defaults to Z=0 when --Z not explicitly passed.
    if args.kind == "hlc" and not any(a in ("--Z", "-Z") for a in argv):
        args.Z = 0

    if args.kind == "hlc" and not any(a in ("--Z", "-Z") for a in argv):
        args.Z = 0
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


def _run_bench_mode(argv: list[str]) -> None:
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
    if args.kind == "hlc" and not any(a in ("--Z", "-Z") for a in argv):
        args.Z = 0
    # HLC-WID defaults to Z=0 when --Z not explicitly passed.
    if args.kind == "hlc" and not any(a in ("--Z", "-Z") for a in argv):
        args.Z = 0

    if args.kind == "hlc" and not any(a in ("--Z", "-Z") for a in argv):
        args.Z = 0
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


def _run_selftest_mode() -> None:
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


def _is_true(raw: str) -> bool:
    """Interpret a canonical boolean value (true/1/yes/on)."""
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _repo_root() -> Path | None:
    """Return the repository root (three levels above this file)."""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "sh" / "wid").exists() and (parent / "README.md").exists():
            return parent
    return None


def _run_cmd(
    cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    """Run a subprocess, streaming its output; raise on non-zero exit."""
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def _run_shell_wid(root_dir: Path, canon: dict[str, str]) -> None:
    """Delegate a canonical invocation to the sh implementation."""
    sh_impl = root_dir / "sh" / "wid"
    if not sh_impl.exists():
        raise RuntimeError(f"shell implementation not found: {sh_impl}")
    args = [
        f"{k}={canon[k]}"
        for k in ("W", "A", "L", "D", "I", "E", "Z", "T", "R", "M", "N")
    ]
    _run_cmd([str(sh_impl), *args])


def _sql_state_path(data_dir: Path) -> Path:
    """Return the SQLite state DB path inside ``data_dir``."""
    return data_dir / "wid_state.sqlite"


def _sql_state_key(w_val: int, z_val: int, time_unit: str) -> str:
    # Deliberately language-agnostic (wid:W:Z:T, no implementation tag): all
    # six implementations share one row per generator shape, so mixing
    # languages on the same database cannot mint duplicate WIDs.
    """Build the language-agnostic state key ``wid:W:Z:T``."""
    return f"wid:{w_val}:{z_val}:{time_unit}"


def _sql_allocate_next_wid(
    w_val: int, z_val: int, time_unit: str, db_path: Path
) -> str:
    """Mint one WID via the shared SQLite compare-and-swap state row."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        q = (
            "CREATE TABLE IF NOT EXISTS wid_state ("
            "k TEXT PRIMARY KEY, "
            "last_tick INTEGER NOT NULL, "
            "last_seq INTEGER NOT NULL)"
        )
        conn.execute(q)
        key = _sql_state_key(w_val, z_val, time_unit)
        conn.execute(
            "INSERT OR IGNORE INTO wid_state(k,last_tick,last_seq) VALUES(?,0,-1)",
            (key,),
        )
        conn.commit()

        for _ in range(64):
            row = conn.execute(
                "SELECT last_tick,last_seq FROM wid_state WHERE k=?",
                (key,),
            ).fetchone()
            if row is None:
                raise RuntimeError("invalid SQL state row")

            last_sec = int(row[0])
            last_seq = int(row[1])
            gen = WidGen(
                w=w_val,
                z=z_val,
                time_unit=parse_time_unit(time_unit),
            )
            gen.restore_state(last_sec, last_seq)
            wid_id = gen.next()
            st = gen.state()
            q_s = (
                "UPDATE wid_state SET last_tick=?,last_seq=? "
                "WHERE k=? AND last_tick=? AND last_seq=?"
            )
            q_p = (st.last_sec, st.last_seq, key, last_sec, last_seq)
            cur = conn.execute(q_s, q_p)
            conn.commit()
            if cur.rowcount == 1:
                return wid_id
        raise RuntimeError("sql allocation contention: retry budget exhausted")
    finally:
        conn.close()


def _require_canon(canon: dict[str, str], key: str, message: str) -> str:
    """Return a required canonical parameter or raise the usage error.

    Missing required parameters are usage errors (ValueError -> exit 2);
    indexing ``canon[...]`` directly raised an uncaught KeyError traceback.
    """
    value = canon.get(key, "")
    if not value:
        raise ValueError(message)
    return value


def _run_sign_mode(canon: dict[str, str]) -> None:
    """Handle ``A=sign``: Ed25519-sign a WID (plus optional payload)."""
    # Validate required params (usage errors, exit 2) BEFORE importing
    # cryptography: a missing optional dependency is an operational failure
    # (ImportError -> exit 1), and must not mask a missing KEY= usage error.
    wid_str = _require_canon(canon, "WID", "WID=<wid_string> required for A=sign")
    raw_key = _require_canon(canon, "KEY", "KEY=<private_key_path> required for A=sign")

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key_path = Path(raw_key).expanduser().resolve()
    data_path_str = canon.get("DATA")
    out_path_str = canon.get("OUT")

    if not key_path.exists():
        raise FileNotFoundError(f"private key file not found: {key_path}")

    try:
        with open(key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
    except ValueError as exc:
        # Bad key material is an operational failure (exit 1), not a usage
        # error: cryptography raises ValueError, which would exit 2.
        raise RuntimeError("sign failed (ensure Ed25519 private key PEM)") from exc

    if not isinstance(private_key, ed25519.Ed25519PrivateKey):
        raise TypeError("Loaded key is not an Ed25519 private key.")

    # Canonical message: "wid-sig-v1:" + len(WID) + ":" + WID + DATA. The domain
    # prefix and explicit WID byte-length frame the WID/DATA boundary.
    wid_bytes = wid_str.encode("utf-8")
    message = f"wid-sig-v1:{len(wid_bytes)}:".encode("ascii") + wid_bytes
    if data_path_str:
        data_path = Path(data_path_str).expanduser().resolve()
        if not data_path.exists():
            raise FileNotFoundError(f"data file not found: {data_path}")
        with open(data_path, "rb") as f:
            message += f.read()

    signature = private_key.sign(message)
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")

    if out_path_str:
        out_path = Path(out_path_str).expanduser().resolve()
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(encoded_signature)
    else:
        print(encoded_signature, flush=True)


def _run_verify_mode(canon: dict[str, str]) -> None:
    """Handle ``A=verify``: check an Ed25519 signature for a WID."""
    # Validate required params (usage errors, exit 2) BEFORE importing
    # cryptography, so a missing optional dependency (ImportError -> exit 1)
    # never masks a missing KEY=/SIG=/WID= usage error.
    wid_str = _require_canon(canon, "WID", "WID=<wid_string> required for A=verify")
    raw_key = _require_canon(
        canon, "KEY", "KEY=<public_key_path> required for A=verify"
    )
    sig_str = _require_canon(
        canon, "SIG", "SIG=<signature_string> required for A=verify"
    )

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key_path = Path(raw_key).expanduser().resolve()
    data_path_str = canon.get("DATA")

    if not key_path.exists():
        raise FileNotFoundError(f"public key file not found: {key_path}")

    try:
        with open(key_path, "rb") as f:
            public_key = serialization.load_pem_public_key(f.read())
    except ValueError as exc:
        # Bad key material is an operational failure (exit 1), not a usage
        # error: cryptography raises ValueError, which would exit 2.
        raise RuntimeError(
            "invalid public key (ensure Ed25519 public key PEM)"
        ) from exc

    if not isinstance(public_key, ed25519.Ed25519PublicKey):
        raise TypeError("Loaded key is not an Ed25519 public key.")

    # Canonical message: "wid-sig-v1:" + len(WID) + ":" + WID + DATA. The domain
    # prefix and explicit WID byte-length frame the WID/DATA boundary.
    wid_bytes = wid_str.encode("utf-8")
    message = f"wid-sig-v1:{len(wid_bytes)}:".encode("ascii") + wid_bytes
    if data_path_str:
        data_path = Path(data_path_str).expanduser().resolve()
        if not data_path.exists():
            raise FileNotFoundError(f"data file not found: {data_path}")
        with open(data_path, "rb") as f:
            message += f.read()

    try:
        # Add padding back; base64 raises binascii.Error (a ValueError
        # subclass) on garbage, which would exit 2 as a usage error — but a
        # malformed signature is a verification failure (exit 1) everywhere.
        decoded_signature = base64.urlsafe_b64decode(sig_str + "===")
    except ValueError as exc:
        raise RuntimeError("invalid signature encoding") from exc

    try:
        public_key.verify(decoded_signature, message)
        print("Signature valid.", flush=True)
        sys.exit(0)
    except InvalidSignature:
        print("Signature invalid.", file=sys.stderr, flush=True)
        sys.exit(1)
    except Exception as e:
        print(f"Verification error: {e}", file=sys.stderr, flush=True)
        sys.exit(1)


def _resolve_wotp_secret(raw_key: str) -> str:
    """Treat KEY= as a file path if one exists, else as the literal secret."""
    key_path = Path(raw_key).expanduser().resolve()
    if key_path.exists() and key_path.is_file():
        return key_path.read_text(encoding="utf-8").strip()
    return raw_key.strip()


def _wotp_code(secret: str, wid: str, digits: int) -> str:
    """Derive the truncated HMAC-SHA256 OTP for ``wid`` (CRYPTO_SPEC)."""
    key = secret.encode("utf-8")
    digest = hmac.new(key, wid.encode("utf-8"), hashlib.sha256).digest()
    binary = int.from_bytes(digest[:4], "big", signed=False)
    return str(binary % (10**digits)).zfill(digits)


def _wotp_wid_tick_ms(wid_str: str) -> int:
    """Extract the WID's timestamp in epoch milliseconds for age checks.

    Raises ``RuntimeError`` (not ``ValueError``) on a malformed timestamp:
    verification *outcomes* exit 1 in every implementation, while this CLI
    reserves exit 2 for usage errors (``ValueError``).
    """
    invalid = "WID timestamp is invalid for time-window verification"
    ts = wid_str.split(".", 1)[0]
    if "T" not in ts:
        raise RuntimeError(invalid)
    date_part, time_part = ts.split("T", 1)
    if len(date_part) != 8 or len(time_part) not in {6, 9}:
        raise RuntimeError(invalid)
    fmt = "%Y%m%dT%H%M%S%f" if len(time_part) == 9 else "%Y%m%dT%H%M%S"
    try:
        dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise RuntimeError(invalid) from exc
    return int(dt.timestamp() * 1000)


# One branch per MODE/parameter rule; mirrors the other implementations.
def _run_wotp_mode(  # noqa: C901
    canon: dict[str, str], w_val: int, z_val: int, time_unit: str
) -> None:
    """Handle ``A=w-otp MODE=gen|verify``: WID-bound one-time codes."""
    mode = canon.get("MODE", "gen").strip().lower()
    if mode not in {"gen", "verify"}:
        raise ValueError("MODE must be gen or verify for A=w-otp")
    if "KEY" not in canon:
        raise ValueError("KEY=<secret_or_path> required for A=w-otp")
    secret = _resolve_wotp_secret(canon["KEY"])
    if not secret:
        raise ValueError("w-otp secret cannot be empty")

    digits_raw = canon.get("DIGITS", "6")
    if not digits_raw.isdigit():
        raise ValueError("DIGITS must be an integer")
    digits = int(digits_raw)
    if digits < 4 or digits > 10:
        raise ValueError("DIGITS must be between 4 and 10")
    max_age_raw = canon.get("MAX_AGE_SEC", "0")
    max_future_raw = canon.get("MAX_FUTURE_SEC", "5")
    if not max_age_raw.isdigit():
        raise ValueError("MAX_AGE_SEC must be a non-negative integer")
    if not max_future_raw.isdigit():
        raise ValueError("MAX_FUTURE_SEC must be a non-negative integer")
    max_age_sec = int(max_age_raw)
    max_future_sec = int(max_future_raw)

    wid_str = canon.get("WID", "").strip()
    if not wid_str and mode == "gen":
        unit = parse_time_unit(time_unit)
        gen = WidGen(w=w_val, z=z_val, time_unit=unit)
        wid_str = gen.next()
    if not wid_str:
        raise ValueError("WID=<wid_string> required for A=w-otp MODE=verify")

    otp = _wotp_code(secret, wid_str, digits)
    if mode == "gen":
        record = {"wid": wid_str, "otp": otp, "digits": digits}
        print(json.dumps(record, separators=(",", ":")))
        return

    code = canon.get("CODE", "").strip()
    if not code:
        raise ValueError("CODE=<otp_code> required for A=w-otp MODE=verify")
    # Freshness failures are verification *outcomes*, not usage errors:
    # RuntimeError exits 1, matching the other five implementations
    # (ValueError would exit 2 here).
    if max_age_sec > 0 or max_future_sec > 0:
        wid_ms = _wotp_wid_tick_ms(wid_str)
        now_ms = int(time.time() * 1000)
        delta_ms = now_ms - wid_ms
        if delta_ms < 0 and -delta_ms > max_future_sec * 1000:
            raise RuntimeError("OTP invalid: WID timestamp is too far in the future")
        if delta_ms >= 0 and max_age_sec > 0 and delta_ms > max_age_sec * 1000:
            raise RuntimeError("OTP invalid: WID timestamp is too old")
    if hmac.compare_digest(otp, code):
        print("OTP valid.", flush=True)
        return
    print("OTP invalid.", file=sys.stderr, flush=True)
    sys.exit(1)


# The canonical KEY=VALUE dispatcher is one deliberate action table,
# mirroring the switch/case dispatchers of the other five implementations.
def _run_canonical(argv: list[str]) -> bool:  # noqa: C901
    """Parse and dispatch canonical KEY=VALUE mode; False if not canonical."""
    if not argv or not any("=" in item for item in argv):
        return False

    canon: dict[str, str] = {
        "A": "next",
        "W": "4",
        "L": "3600",
        "D": "",
        "I": "auto",
        "E": "state",
        "Z": "6",
        "T": "sec",
        "R": "auto",
        "M": "false",
        "N": "0",
    }
    l_explicit = False

    for item in argv:
        if "=" not in item:
            raise ValueError(f"expected KEY=VALUE, got '{item}'")
        key, value = item.split("=", 1)
        if key not in CANONICAL_KEYS:
            raise ValueError(f"unknown key: {key}")
        canon[key] = value
        if key == "L" and value != "#":
            l_explicit = True

    placeholder_defaults = {
        "A": "next",
        "W": "4",
        "L": "3600",
        "D": "",
        "I": "auto",
        "E": "state",
        "Z": "6",
        "T": "sec",
        "R": "auto",
        "M": "false",
        "N": "0",
    }
    for key, default in placeholder_defaults.items():
        if canon[key] == "#":
            canon[key] = default

    if _is_true(canon["M"]):
        canon["T"] = "ms"

    # Unified stream cadence (all six implementations): an unset or
    # placeholder L means emit back-to-back; only an explicit L=n sleeps.
    # The 3600 default applies to the Rust-only service loops, not here.
    if canon["A"] == "stream" and not l_explicit:
        canon["L"] = "0"

    if canon["T"] not in {"sec", "ms"}:
        raise ValueError("T must be sec or ms")
    if not canon["W"].isdigit() or int(canon["W"]) <= 0:
        raise ValueError("W must be a positive integer")
    if not canon["Z"].isdigit():
        raise ValueError("Z must be a non-negative integer")
    if not canon["N"].isdigit():
        raise ValueError("N must be a non-negative integer")
    if not canon["L"].isdigit():
        raise ValueError("L must be a non-negative integer (seconds)")
    if canon["R"] not in TRANSPORTS:
        raise ValueError(
            f"transport R={canon['R']} is only available in the Rust"
            + " implementation (services/transports are Rust-only)"
        )

    action: str = canon["A"].strip().lower()
    w_val: int = int(canon["W"])
    z_val: int = int(canon["Z"])
    l_val: int = int(canon["L"])
    n_val: int = int(canon["N"])
    time_unit: str = canon["T"]
    input_src: str = canon["I"]
    d_val = canon["D"]
    e_val: str = canon["E"]
    if action == "help-actions":
        _print_actions()
        return True

    # Default matches every other implementation: <cwd>/.local/services.
    # A ~-anchored default here would silently split the shared SQL state.
    data_dir = (
        Path(d_val).expanduser().resolve()
        if d_val
        else (Path.cwd() / ".local" / "services").resolve()
    )
    data_dir.mkdir(parents=True, exist_ok=True)

    effective_time_unit = parse_time_unit(time_unit)

    # E may carry a "+transport" / ",transport" suffix from the full canonical
    # grammar; only the state-mode half is meaningful here (transports are
    # Rust-only).
    state_mode = e_val
    if "+" in e_val:
        state_mode = e_val.split("+", 1)[0]
    elif "," in e_val:
        state_mode = e_val.split(",", 1)[0]

    if action in {"next", "stream", "healthcheck"}:
        if input_src in {"sh", "bash"}:
            if os.name == "nt":
                # sh/wid is a bash script; Windows cannot exec it directly
                # (and a checkout usually has no bash). Refuse up front with a
                # clear message instead of a cryptic subprocess exec error.
                msg = (
                    "I=sh/I=bash is not available on Windows: it delegates to "
                    "the bash script sh/wid, which Windows cannot execute. Use "
                    "the default/native Python path (omit I=, or I=auto)."
                )
                raise RuntimeError(msg)
            root_dir = _repo_root()
            if root_dir is None:
                msg = (
                    "I=sh/I=bash delegates to the sibling sh/wid script, which is "
                    "only present in a source checkout of the repository. The "
                    "installed 'waldiez-wid' package bundles the Python "
                    "implementation only (and there is no bundled sh/wid on "
                    "Windows even from a checkout, since it is a bash script). "
                    "Use the default/native Python path (omit I=, or I=auto) here."
                )
                raise RuntimeError(msg)
            _run_shell_wid(root_dir, canon)
            return True

        if action == "next":
            if state_mode == "sql":
                print(
                    _sql_allocate_next_wid(
                        w_val,
                        z_val,
                        time_unit,
                        _sql_state_path(data_dir),
                    ),
                    flush=True,
                )
            else:
                gen = WidGen(w=w_val, z=z_val, time_unit=effective_time_unit)
                print(gen.next(), flush=True)
            return True
        if action == "healthcheck":
            gen = WidGen(w=w_val, z=z_val, time_unit=effective_time_unit)
            sample = gen.next()
            ok = validate_wid(sample, W=w_val, Z=z_val, time_unit=effective_time_unit)
            payload = {
                "ok": bool(ok),
                "kind": "wid",
                "W": w_val,
                "Z": z_val,
                "sample_id": sample,
                "time_unit": time_unit,
            }
            print(json.dumps(payload, separators=(",", ":")))
            if not ok:
                sys.exit(1)
            return True

        gen = WidGen(w=w_val, z=z_val, time_unit=effective_time_unit)
        emitted = 0
        while n_val == 0 or emitted < n_val:
            if state_mode == "sql":
                print(
                    _sql_allocate_next_wid(
                        w_val,
                        z_val,
                        time_unit,
                        _sql_state_path(data_dir),
                    ),
                    flush=True,
                )
            else:
                print(gen.next(), flush=True)
            emitted += 1
            if n_val == 0 or emitted < n_val:
                time.sleep(max(0, l_val))
        return True

    if action == "sign":
        _run_sign_mode(canon)
        return True

    if action == "verify":
        _run_verify_mode(canon)
        return True

    if action == "w-otp":
        _run_wotp_mode(canon, w_val=w_val, z_val=z_val, time_unit=time_unit)
        return True

    raise ValueError(f"unknown A={action}")


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


def _run_validate_mode(args: list[str]) -> None:
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


def _run_parse_mode(args: list[str]) -> None:
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


def _fish_completion() -> str:
    """Build the fish completion script line by line."""
    guard = (
        "not __fish_seen_subcommand_from next stream healthcheck validate"
        + " parse help-actions bench selftest completion"
    )
    subcommands = (
        ("next", "Emit one WID"),
        ("stream", "Stream WIDs continuously"),
        ("healthcheck", "Generate and validate a sample WID"),
        ("validate", "Validate a WID string"),
        ("parse", "Parse a WID string"),
        ("help-actions", "Show canonical action matrix"),
        ("completion", "Print shell completion script"),
    )
    lines = ["complete -c wid -e"]
    lines += [
        f"complete -c wid -f -n '{guard}' -a {cmd} -d '{desc}'"
        for cmd, desc in subcommands
    ]
    lines += [
        "complete -c wid -f -a 'A=next A=stream A=healthcheck A=sign"
        + " A=verify A=w-otp A=help-actions' -d 'Action'",
        "complete -c wid -f -a 'T=sec T=ms' -d 'Time unit'",
        "complete -c wid -f -a 'I=auto I=sh I=bash' -d 'Input source'",
        "complete -c wid -f -a 'E=state E=stateless E=sql' -d 'State mode'",
        "complete -c wid -f -a 'R=auto R=null R=stdout' -d 'Transport'",
        "complete -c wid -f -a 'M=true M=false' -d 'Milliseconds mode'",
        "complete -c wid -f -a 'W=' -d 'Sequence width'",
        "complete -c wid -f -a 'Z=' -d 'Padding length'",
        "complete -c wid -f -a 'N=' -d 'Count'",
        "complete -c wid -f -a 'L=' -d 'Interval seconds'",
    ]
    return "\n".join(lines)


def _print_completion(shell: str) -> None:
    """Print a bash/zsh/fish completion script for the wid CLI.

    Only values the CLI actually accepts are advertised: service actions
    and broker transports are Rust-only and rejected here.
    """
    if shell == "bash":
        print(r"""_wid_complete() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local cmds="next stream healthcheck validate parse help-actions bench \
selftest completion"
  if [[ "$cur" == *=* ]]; then
    local key="${cur%%=*}" val="${cur#*=}" vals=""
    case "$key" in
      A) vals="next stream healthcheck sign verify w-otp help-actions" ;;
      T) vals="sec ms" ;;
      I) vals="auto sh bash" ;;
      E) vals="state stateless sql" ;;
      R) vals="auto null stdout" ;;
      M) vals="true false" ;;
    esac
    local IFS=$'\n'
    COMPREPLY=($(for v in $vals; do
      [[ "$v" == "$val"* ]] && printf '%s\n' "${key}=${v}"
    done))
  else
    local kv="A= W= Z= T= N= L= D= I= E= R= M="
    COMPREPLY=($(compgen -W "$cmds $kv" -- "$cur"))
  fi
}
complete -o nospace -F _wid_complete wid""")
    elif shell == "zsh":
        # fmt: off
        print(
            r"""#compdef wid
_wid_complete() {
  local cur="${words[-1]}"
  local -a cmds=(
    next stream healthcheck validate parse
    help-actions bench selftest completion
  )
  if [[ "$cur" == *=* ]]; then
    local key="${cur%%=*}"
    local -a vals=()
    case "$key" in
      A) vals=(next stream healthcheck sign verify w-otp help-actions) ;;
      T) vals=(sec ms) ;;
      I) vals=(auto sh bash) ;;
      E) vals=(state stateless sql) ;;
      R) vals=(auto null stdout) ;;
      M) vals=(true false) ;;
    esac
    compadd -P "${key}=" -- "${vals[@]}"
  else
    compadd -- "${cmds[@]}" A= W= Z= T= N= L= D= I= E= R= M=
  fi
}
_wid_complete """
            + '"$@"'
        )
        # fmt: on
    elif shell == "fish":
        print(_fish_completion())
    else:
        print(
            f"error: unknown shell '{shell}'. Use: wid completion bash|zsh|fish",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    """Wid main entrypoint."""
    if len(sys.argv) >= 2 and sys.argv[1] in {"-h", "--help", "help"}:
        _print_usage()
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "completion":
        if len(sys.argv) < 3:
            print("usage: wid completion bash|zsh|fish", file=sys.stderr)
            sys.exit(1)
        _print_completion(sys.argv[2])
        return

    try:
        if _run_canonical(sys.argv[1:]):
            return
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    except (RuntimeError, OSError, TypeError, ImportError) as exc:
        # OSError: missing key/data files; ImportError: cryptography not
        # installed; TypeError: wrong key type. Same contract as the other
        # implementations: `error: ...` on stderr, never a traceback.
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)

    # Flag-mode subcommands share the canonical mode's error contract:
    # invalid values exit with a clean `error: ...`, never a traceback.
    try:
        _dispatch_flag_mode()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    except (RuntimeError, OSError, TypeError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


def _dispatch_flag_mode() -> None:
    # No arguments prints usage and exits 2, matching every other
    # implementation (a bare `wid` used to silently emit one ID).
    """Dispatch flag-mode subcommands (next, stream, validate, ...)."""
    if len(sys.argv) == 1:
        _print_usage(sys.stderr)
        sys.exit(2)

    cmd = sys.argv[1]
    if cmd in {"next", "stream"}:
        _run_emit_mode(cmd, sys.argv[2:])
        return

    if cmd == "help-actions":
        _print_actions()
        return

    if cmd == "healthcheck":
        _run_healthcheck_mode(sys.argv[2:])
        return

    if cmd == "validate":
        _run_validate_mode(sys.argv[2:])
        return

    if cmd == "parse":
        _run_parse_mode(sys.argv[2:])
        return

    if cmd == "bench":
        _run_bench_mode(sys.argv[2:])
        return

    if cmd == "selftest":
        _run_selftest_mode()
        return

    print(f"Unknown command: {cmd}", file=sys.stderr)
    sys.exit(2)


def _run_cli_entry(args: list[str]) -> None:
    """Run the CLI with an explicit argv (used by the hlc-wid entry point)."""
    original = list(sys.argv)
    try:
        sys.argv = [sys.argv[0], *args, *original[1:]]
        main()
    finally:
        sys.argv = original


def hlc_wid_main() -> None:
    """Default hlc-wid command."""
    _run_cli_entry(["next", "--kind", "hlc"])


if __name__ == "__main__":
    main()
