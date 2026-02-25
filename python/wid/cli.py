#!/usr/bin/env python3
"""CLI entrypoints for emit, stream, and healthcheck modes."""

# pyright: reportUnusedCallResult=false,reportAny=false
# pylint: skip-file
# flake8: noqa: C901, E501

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from .core import WidCore
from .hlc import HLCWidGen
from .parse import parse_hlc_wid, parse_wid, validate_hlc_wid, validate_wid
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
TRANSPORTS = {"mqtt", "ws", "redis", "null", "stdout", "auto"}
ACTION_ALIASES = {
    "raf": "saf",
    "waf": "saf-wid",
    "wraf": "saf-wid",
    "witr": "wir",
    "wim": "wism",
    "wih": "wihp",
    "wip": "wipr",
}
LOCAL_SERVICE_TRANSPORTS = {"mqtt", "ws", "redis", "null", "stdout", "auto"}


def _print_actions() -> None:
    print("""wid action matrix

Core ID:
  A=next | A=stream | A=healthcheck
  A=sign | A=verify | A=w-otp

Service lifecycle:
  A=discover | A=scaffold | A=run | A=start | A=stop | A=status | A=logs | A=self.check-update

Local services:
  A=saf      (alias: raf)
  A=saf-wid  (aliases: waf, wraf)
  A=wir      (alias: witr)
  A=wism     (alias: wim)
  A=wihp     (alias: wih)
  A=wipr     (alias: wip)
  A=duplex

Help:
  A=help-actions

State mode:
  E=state | E=stateless | E=sql
""")


def _print_usage() -> None:
    print(
        """wid python CLI

Usage:
  python -m wid [next|stream|healthcheck|help-actions] [options]
  python -m wid A=<action> W=<n> Z=<n> ...

Commands:
  next         Emit one ID (default with no args).
  stream       Emit IDs continuously (or until --count).
  healthcheck  Generate one sample and validate format.
  help-actions Show canonical action matrix (A=...).
  sign         Canonical mode only: A=sign WID=<wid> KEY=<priv.pem> [DATA=<path>] [OUT=<path>].
  verify       Canonical mode only: A=verify WID=<wid> KEY=<pub.pem> SIG=<sig> [DATA=<path>].
  w-otp        Canonical mode only: A=w-otp MODE=gen|verify KEY=<secret|path> [WID=<wid>] [CODE=<otp>] [DIGITS=<n>] [MAX_AGE_SEC=<n>] [MAX_FUTURE_SEC=<n>].

Examples:
  python -m wid
  python -m wid stream --kind wid --W 4 --Z 0
  python -m wid healthcheck --kind hlc --W 4 --Z 0 --node edge01
  python -m wid A=next W=4 Z=0 T=sec

Environment:
  WID_DEFAULT_MODE=next|stream
"""
    )


def _emit_record(id_value: str, kind: str, out_format: str) -> str:
    if out_format == "jsonl":
        return json.dumps(
            {
                "id": id_value,
                "kind": kind,
                "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            },
            separators=(",", ":"),
        )
    return id_value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_default_mode() -> str:
    mode = os.environ.get("WID_DEFAULT_MODE", "next").strip().lower()
    return mode if mode in {"next", "stream"} else "next"


def _run_emit_mode(mode: str, argv: list[str]) -> None:
    ap = argparse.ArgumentParser(description=f"Emit WID values ({mode})")
    ap.add_argument("--kind", choices=["wid", "hlc"], default="wid")
    ap.add_argument("--W", type=int, default=_env_int("W", 4))
    ap.add_argument("--Z", type=int, default=_env_int("Z", 6))
    ap.add_argument("--node", type=str, default=os.environ.get("NODE", "py"))
    ap.add_argument(
        "--time-unit",
        choices=["sec", "ms"],
        default=os.environ.get("WID_TIME_UNIT", "sec"),
    )
    ap.add_argument("--format", choices=["text", "jsonl"], default="text")
    ap.add_argument(
        "--count", type=int, default=0, help="0 means infinite (stream mode)"
    )
    ap.add_argument("--interval-ms", type=int, default=0)
    ap.add_argument(
        "--cadence",
        "--L",
        dest="cadence",
        type=int,
        default=max(1, _env_int("L", 1000)),
    )
    ap.add_argument("--healthcheck-cmd", type=str, default="")
    args = ap.parse_args(argv)

    gen: Callable[[], str]
    g: WidGen | HLCWidGen
    effective_time_unit = WidCore.TimeUnit.from_string(args.time_unit)
    if args.kind == "wid":
        g = WidGen(w=args.W, z=args.Z, time_unit=effective_time_unit)
        gen = g.next
    else:
        g = HLCWidGen(args.node, w=args.W, z=args.Z, time_unit=effective_time_unit)
        gen = g.next

    if mode == "next":
        print(_emit_record(gen(), args.kind, args.format), flush=True)
        return

    emitted = 0
    try:
        while args.count == 0 or emitted < args.count:
            print(_emit_record(gen(), args.kind, args.format), flush=True)
            emitted += 1
            if (
                args.healthcheck_cmd
                and args.cadence > 0
                and emitted % args.cadence == 0
            ):
                rc = subprocess.run(args.healthcheck_cmd, shell=True).returncode
                if rc != 0:
                    print(
                        f"Healthcheck command failed with exit code {rc}",
                        file=sys.stderr,
                    )
                    sys.exit(rc)
            if args.interval_ms > 0:
                time.sleep(args.interval_ms / 1000.0)
    except KeyboardInterrupt:
        sys.exit(130)


def _run_healthcheck_mode(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(description="Healthcheck WID/HLC generator (strict)")
    ap.add_argument("--kind", choices=["wid", "hlc"], default="wid")
    ap.add_argument("--W", type=int, default=_env_int("W", 4))
    ap.add_argument("--Z", type=int, default=_env_int("Z", 6))
    ap.add_argument("--node", type=str, default=os.environ.get("NODE", "py"))
    ap.add_argument(
        "--time-unit",
        choices=["sec", "ms"],
        default=os.environ.get("WID_TIME_UNIT", "sec"),
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    effective_time_unit = WidCore.TimeUnit.from_string(args.time_unit)
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


def _is_true(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "sh" / "wid").exists() and (parent / "README.md").exists():
            return parent
    return None


def _run_cmd(
    cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)



def _run_shell_wid(root_dir: Path, canon: dict[str, str]) -> None:
    sh_impl = root_dir / "sh" / "wid"
    if not sh_impl.exists():
        raise RuntimeError(f"shell implementation not found: {sh_impl}")
    args = [
        f"{k}={canon[k]}"
        for k in ("W", "A", "L", "D", "I", "E", "Z", "T", "R", "M", "N")
    ]
    _run_cmd([str(sh_impl), *args])


def _runtime_dir(root_dir: Path) -> Path:
    return (root_dir / ".local" / "wid" / "python").resolve()


def _pid_file(root_dir: Path) -> Path:
    return _runtime_dir(root_dir) / "service.pid"


def _log_file(root_dir: Path) -> Path:
    return _runtime_dir(root_dir) / "service.log"


def _tail_text(path: Path, n: int = 40) -> str:
    if not path.exists():
        return "no-log\n"
    with path.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return "".join(lines[-n:])


def _service_loop_native(
    *,
    action: str,
    n_val: int,
    l_val: int,
    w_val: int,
    z_val: int,
    time_unit: str,
    state_mode: str,
    data_dir: Path,
) -> None:
    loops = n_val if n_val > 0 else 10
    unit = WidCore.TimeUnit.from_string(time_unit)
    gen = WidGen(w=w_val, z=z_val, time_unit=unit)
    emitted = 0
    while emitted < loops:
        if action == "run":
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
        if emitted < loops:
            time.sleep(max(0, l_val))


def _start_native_daemon(
    *,
    root_dir: Path,
    canon: dict[str, str],
) -> None:
    run_canon = dict(canon)
    run_canon["A"] = "run"
    ks = ("W", "A", "L", "D", "I", "E", "Z", "T", "R", "M", "N")
    args = [f"{k}={run_canon[k]}" for k in ks]
    runtime = _runtime_dir(root_dir)
    runtime.mkdir(parents=True, exist_ok=True)
    log_path = _log_file(root_dir)
    py = sys.executable or shutil.which("python3") or "python3"
    cmd = [py, "-m", "wid", "__daemon", *args]
    with log_path.open("a", encoding="utf-8") as logf:
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            cwd=str(root_dir),
            env=dict(os.environ),
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _pid_file(root_dir).write_text(f"{proc.pid}\n", encoding="utf-8")
    print(f"started python service pid={proc.pid}")


def _stop_native_daemon(root_dir: Path) -> None:
    pid_path = _pid_file(root_dir)
    if not pid_path.exists():
        print("not-running")
        return
    raw = pid_path.read_text(encoding="utf-8").strip()
    if not raw.isdigit():
        pid_path.unlink(missing_ok=True)
        print("stopped")
        return
    pid = int(raw)
    try:
        os.kill(pid, signal.SIGTERM)
        print("stopped")
    except ProcessLookupError:
        print("stale")
    pid_path.unlink(missing_ok=True)


def _status_native_daemon(root_dir: Path) -> None:
    pid_path = _pid_file(root_dir)
    if not pid_path.exists():
        print("stopped")
        return
    raw = pid_path.read_text(encoding="utf-8").strip()
    if not raw.isdigit():
        print("stale")
        return
    pid = int(raw)
    try:
        os.kill(pid, 0)
        print("running")
    except ProcessLookupError:
        print("stale")


def _logs_native_daemon(root_dir: Path) -> None:
    print(_tail_text(_log_file(root_dir), 40), end="")


def _check_update_native() -> None:
    import urllib.request
    current = "1.0.0"
    latest = ""
    update_exists = False
    try:
        url = "https://api.github.com/repos/waldiez/wid/releases/latest"
        with urllib.request.urlopen(url, timeout=3) as response:
            data = json.loads(response.read().decode())
            latest = data.get("tag_name", "").lstrip("v")
            if latest and latest != current:
                update_exists = True
    except Exception:
        latest = current

    print(json.dumps({
        "current": current,
        "latest": latest,
        "update_exists": update_exists
    }, separators=(",", ":")))


def _sql_state_path(data_dir: Path) -> Path:
    return data_dir / "wid_state.sqlite"


def _sql_state_key(w_val: int, z_val: int, time_unit: str) -> str:
    return f"wid:py:{w_val}:{z_val}:{time_unit}"


def _sql_allocate_next_wid(
    w_val: int, z_val: int, time_unit: str, db_path: Path
) -> str:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        q = (
            "CREATE TABLE IF NOT EXISTS wid_state ("
            "k TEXT PRIMARY KEY, "
            "last_sec INTEGER NOT NULL, "
            "last_seq INTEGER NOT NULL)"
        )
        conn.execute(q)
        key = _sql_state_key(w_val, z_val, time_unit)
        conn.execute(
            "INSERT OR IGNORE INTO wid_state(k,last_sec,last_seq) VALUES(?,0,-1)",
            (key,),
        )
        conn.commit()

        for _ in range(64):
            row = conn.execute(
                "SELECT last_sec,last_seq FROM wid_state WHERE k=?",
                (key,),
            ).fetchone()
            if row is None:
                raise RuntimeError("invalid SQL state row")

            last_sec = int(row[0])
            last_seq = int(row[1])
            gen = WidGen(
                w=w_val,
                z=z_val,
                time_unit=WidCore.TimeUnit.from_string(time_unit),
            )
            gen.restore_state(last_sec, last_seq)
            wid_id = gen.next()
            st = gen.state()
            q_s = (
                "UPDATE wid_state SET last_sec=?,last_seq=? "
                "WHERE k=? AND last_sec=? AND last_seq=?"
            )
            q_p = (st.last_sec, st.last_seq, key, last_sec, last_seq)
            cur = conn.execute(q_s, q_p)
            conn.commit()
            if cur.rowcount == 1:
                return wid_id
        raise RuntimeError("sql allocation contention: retry budget exhausted")
    finally:
        conn.close()


def _run_sign_mode(canon: dict[str, str]) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    wid_str = canon["WID"]
    key_path = Path(canon["KEY"]).expanduser().resolve()
    data_path_str = canon.get("DATA")
    out_path_str = canon.get("OUT")

    if not key_path.exists():
        raise FileNotFoundError(f"Private key file not found: {key_path}")

    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    if not isinstance(private_key, ed25519.Ed25519PrivateKey):
        raise TypeError("Loaded key is not an Ed25519 private key.")

    message = wid_str.encode("utf-8")
    if data_path_str:
        data_path = Path(data_path_str).expanduser().resolve()
        if not data_path.exists():
            raise FileNotFoundError(f"Data file not found: {data_path}")
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
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    wid_str = canon["WID"]
    key_path = Path(canon["KEY"]).expanduser().resolve()
    sig_str = canon["SIG"]
    data_path_str = canon.get("DATA")

    if not key_path.exists():
        raise FileNotFoundError(f"Public key file not found: {key_path}")

    with open(key_path, "rb") as f:
        public_key = serialization.load_pem_public_key(f.read())

    if not isinstance(public_key, ed25519.Ed25519PublicKey):
        raise TypeError("Loaded key is not an Ed25519 public key.")

    message = wid_str.encode("utf-8")
    if data_path_str:
        data_path = Path(data_path_str).expanduser().resolve()
        if not data_path.exists():
            raise FileNotFoundError(f"Data file not found: {data_path}")
        with open(data_path, "rb") as f:
            message += f.read()

    decoded_signature = base64.urlsafe_b64decode(sig_str + "===")  # Add padding back

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
    key_path = Path(raw_key).expanduser().resolve()
    if key_path.exists() and key_path.is_file():
        return key_path.read_text(encoding="utf-8").strip()
    return raw_key.strip()


def _wotp_code(secret: str, wid: str, digits: int) -> str:
    digest = hmac.new(secret.encode("utf-8"), wid.encode("utf-8"), hashlib.sha256).digest()
    binary = int.from_bytes(digest[:4], "big", signed=False)
    return str(binary % (10**digits)).zfill(digits)


def _wotp_wid_tick_ms(wid_str: str) -> int:
    ts = wid_str.split(".", 1)[0]
    if "T" not in ts:
        raise ValueError("WID timestamp is invalid for time-window verification")
    date_part, time_part = ts.split("T", 1)
    if len(date_part) != 8 or len(time_part) not in {6, 9}:
        raise ValueError("WID timestamp is invalid for time-window verification")
    fmt = "%Y%m%dT%H%M%S%f" if len(time_part) == 9 else "%Y%m%dT%H%M%S"
    dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _run_wotp_mode(canon: dict[str, str], w_val: int, z_val: int, time_unit: str) -> None:
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
        gen = WidGen(w=w_val, z=z_val, time_unit=WidCore.TimeUnit.from_string(time_unit))
        wid_str = gen.next()
    if not wid_str:
        raise ValueError("WID=<wid_string> required for A=w-otp MODE=verify")

    otp = _wotp_code(secret, wid_str, digits)
    if mode == "gen":
        print(json.dumps({"wid": wid_str, "otp": otp, "digits": digits}, separators=(",", ":")))
        return

    code = canon.get("CODE", "").strip()
    if not code:
        raise ValueError("CODE=<otp_code> required for A=w-otp MODE=verify")
    if max_age_sec > 0 or max_future_sec > 0:
        wid_ms = _wotp_wid_tick_ms(wid_str)
        now_ms = int(time.time() * 1000)
        delta_ms = now_ms - wid_ms
        if delta_ms < 0 and -delta_ms > max_future_sec * 1000:
            raise ValueError("OTP invalid: WID timestamp is too far in the future")
        if delta_ms >= 0 and max_age_sec > 0 and delta_ms > max_age_sec * 1000:
            raise ValueError("OTP invalid: WID timestamp is too old")
    if hmac.compare_digest(otp, code):
        print("OTP valid.", flush=True)
        return
    print("OTP invalid.", file=sys.stderr, flush=True)
    sys.exit(1)


def _run_canonical(argv: list[str]) -> bool:
    if not argv or not any("=" in item for item in argv):
        return False

    canon: dict[str, str] = {
        "A": "run",
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
    l_from_placeholder = False

    for item in argv:
        if "=" not in item:
            raise ValueError(f"expected KEY=VALUE, got '{item}'")
        key, value = item.split("=", 1)
        if key not in CANONICAL_KEYS:
            raise ValueError(f"unknown key: {key}")
        canon[key] = value
        if key == "L" and value == "#":
            l_from_placeholder = True

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

    if canon["A"] == "stream" and l_from_placeholder:
        canon["L"] = "1"

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
        raise ValueError(f"invalid transport: {canon['R']}")

    action: str = canon["A"].strip().lower()
    action = ACTION_ALIASES.get(action, action)
    w_val: int = int(canon["W"])
    z_val: int = int(canon["Z"])
    l_val: int = int(canon["L"])
    n_val: int = int(canon["N"])
    time_unit: str = canon["T"]
    input_src: str = canon["I"]
    d_val = canon["D"]
    e_val: str = canon["E"]
    r_val: str = canon["R"]
    if action == "help-actions":
        _print_actions()
        return True

    data_dir = (
        Path(d_val).expanduser().resolve()
        if d_val
        else (Path.home() / ".local" / "wid" / "services").resolve()
    )
    data_dir.mkdir(parents=True, exist_ok=True)

    effective_time_unit = WidCore.TimeUnit.from_string(time_unit)

    state_mode = e_val
    effective_transport = r_val
    if "+" in e_val:
        left, right = e_val.split("+", 1)
        state_mode = left
        if effective_transport == "auto":
            effective_transport = right
    elif "," in e_val:
        left, right = e_val.split(",", 1)
        state_mode = left
        if effective_transport == "auto":
            effective_transport = right

    if action in {"next", "stream", "healthcheck"}:
        if input_src in {"sh", "bash"}:
            root_dir = _repo_root()
            if root_dir is None:
                raise RuntimeError("Unable to locate repository root (missing sh/wid)")
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

    if action == "discover":
        payload = {
            "impl": "python",
            "orchestration": "native",
            "actions": [
                "discover",
                "scaffold",
                "run",
                "start",
                "stop",
                "status",
                "logs",
                "saf",
                "saf-wid",
                "wir",
                "wism",
                "wihp",
                "wipr",
                "duplex",
                "self.check-update",
            ],
            "transports": ["auto", "mqtt", "ws", "redis", "null", "stdout"],
        }
        print(json.dumps(payload, separators=(",", ":")))
        return True
    if action == "scaffold":
        if not d_val:
            raise ValueError("D=<name> required for A=scaffold")
        base = Path(d_val).expanduser().resolve()
        (base / "state").mkdir(parents=True, exist_ok=True)
        (base / "logs").mkdir(parents=True, exist_ok=True)
        print(f"scaffolded {base}")
        return True
    if action == "run":
        _service_loop_native(
            action="run",
            n_val=n_val,
            l_val=l_val,
            w_val=w_val,
            z_val=z_val,
            time_unit=time_unit,
            state_mode=state_mode,
            data_dir=data_dir,
        )
        return True
    if action in {"start", "stop", "status", "logs"}:
        root_dir = _repo_root()
        if root_dir is None:
            raise RuntimeError("Unable to locate repository root (missing sh/wid)")
        if action == "start":
            _start_native_daemon(root_dir=root_dir, canon=canon)
        elif action == "stop":
            _stop_native_daemon(root_dir)
        elif action == "status":
            _status_native_daemon(root_dir)
        elif action == "logs":
            _logs_native_daemon(root_dir)
        return True
    if action == "self.check-update":
        _check_update_native()
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

    log_level = os.environ.get("LOG_LEVEL", "INFO")
    tu: Literal["ms", "sec"] = "ms" if time_unit == "ms" else "sec"

    def _service_emit(payload: dict[str, Any]) -> None:
        t = payload.get("transport") or payload.get("a_transport", "")
        if t != "null":
            print(json.dumps(payload, separators=(",", ":")), flush=True)

    if action == "saf":
        tick = 0
        while n_val == 0 or tick < n_val:
            tick += 1
            _service_emit({"impl": "python", "action": "saf", "tick": tick,
                           "transport": effective_transport,
                           "interval": l_val, "log_level": log_level, "data_dir": str(data_dir)})
            if n_val == 0 or tick < n_val:
                time.sleep(max(0, l_val))
        return True

    if action == "saf-wid":
        transport = effective_transport if effective_transport != "auto" else "mqtt"
        if transport not in LOCAL_SERVICE_TRANSPORTS:
            raise ValueError(f"invalid transport for A=saf-wid: {transport}")
        gen = WidGen(w=w_val, z=z_val, time_unit=tu)
        tick = 0
        while n_val == 0 or tick < n_val:
            tick += 1
            _service_emit({"impl": "python", "action": "saf-wid", "tick": tick,
                           "transport": transport, "wid": gen.next(),
                           "W": w_val, "Z": z_val, "time_unit": time_unit,
                           "interval": l_val, "log_level": log_level, "data_dir": str(data_dir)})
            if n_val == 0 or tick < n_val:
                time.sleep(max(0, l_val))
        return True

    if action == "wir":
        transport = effective_transport if effective_transport != "auto" else "mqtt"
        if transport not in LOCAL_SERVICE_TRANSPORTS:
            raise ValueError(f"invalid transport for A=wir: {transport}")
        tick = 0
        while n_val == 0 or tick < n_val:
            tick += 1
            _service_emit({"impl": "python", "action": "wir", "tick": tick,
                           "transport": transport, "interval": l_val,
                           "log_level": log_level, "data_dir": str(data_dir)})
            if n_val == 0 or tick < n_val:
                time.sleep(max(0, l_val))
        return True

    if action == "wism":
        transport = effective_transport if effective_transport != "auto" else "mqtt"
        if transport not in LOCAL_SERVICE_TRANSPORTS:
            raise ValueError(f"invalid transport for A=wism: {transport}")
        gen = WidGen(w=w_val, z=z_val, time_unit=tu)
        tick = 0
        while n_val == 0 or tick < n_val:
            tick += 1
            _service_emit({"impl": "python", "action": "wism", "tick": tick,
                           "transport": transport, "wid": gen.next(),
                           "W": w_val, "Z": z_val,
                           "interval": l_val, "data_dir": str(data_dir)})
            if n_val == 0 or tick < n_val:
                time.sleep(max(0, l_val))
        return True

    if action == "wihp":
        transport = effective_transport if effective_transport != "auto" else "mqtt"
        if transport not in LOCAL_SERVICE_TRANSPORTS:
            raise ValueError(f"invalid transport for A=wihp: {transport}")
        gen = WidGen(w=w_val, z=z_val, time_unit=tu)
        tick = 0
        while n_val == 0 or tick < n_val:
            tick += 1
            _service_emit({"impl": "python", "action": "wihp", "tick": tick,
                           "transport": transport, "wid": gen.next(),
                           "W": w_val, "Z": z_val,
                           "interval": l_val, "data_dir": str(data_dir)})
            if n_val == 0 or tick < n_val:
                time.sleep(max(0, l_val))
        return True

    if action == "wipr":
        transport = effective_transport if effective_transport != "auto" else "mqtt"
        if transport not in LOCAL_SERVICE_TRANSPORTS:
            raise ValueError(f"invalid transport for A=wipr: {transport}")
        gen = WidGen(w=w_val, z=z_val, time_unit=tu)
        tick = 0
        while n_val == 0 or tick < n_val:
            tick += 1
            _service_emit({"impl": "python", "action": "wipr", "tick": tick,
                           "transport": transport, "wid": gen.next(),
                           "W": w_val, "Z": z_val,
                           "interval": l_val, "data_dir": str(data_dir)})
            if n_val == 0 or tick < n_val:
                time.sleep(max(0, l_val))
        return True

    if action == "duplex":
        a_transport = effective_transport if effective_transport != "auto" else "mqtt"
        b_transport = "ws"
        if input_src in TRANSPORTS and input_src != "auto":
            b_transport = input_src
        if a_transport not in LOCAL_SERVICE_TRANSPORTS:
            raise ValueError(f"invalid side-A transport: {a_transport}")
        if b_transport not in LOCAL_SERVICE_TRANSPORTS:
            raise ValueError(f"invalid side-B transport: {b_transport}")
        tick = 0
        while n_val == 0 or tick < n_val:
            tick += 1
            _service_emit({"impl": "python", "action": "duplex", "tick": tick,
                           "a_transport": a_transport, "b_transport": b_transport,
                           "interval": l_val, "data_dir": str(data_dir)})
            if n_val == 0 or tick < n_val:
                time.sleep(max(0, l_val))
        return True

    raise ValueError(f"unknown A={action}")


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
            i += 2
        else:
            i += 1
    return kind, w, z, time_unit


def _run_validate_mode(args: list[str]) -> None:
    """Handle: wid validate <id> [--kind wid|hlc] [--W n] [--Z n] [--time-unit sec|ms]."""
    if not args or args[0].startswith("--"):
        print("error: validate requires an id", file=sys.stderr)
        sys.exit(2)
    wid_str = args[0]
    kind, w, z, time_unit = _parse_validate_flags(args[1:])
    tu: Literal["ms", "sec"] = "ms" if "m" in time_unit else "sec"
    if kind == "hlc":
        ok = validate_hlc_wid(wid_str, W=w, Z=z, time_unit=tu)
    else:
        ok = validate_wid(wid_str, W=w, Z=z, time_unit=tu)
    print("true" if ok else "false")
    if not ok:
        sys.exit(1)


def _run_parse_mode(args: list[str]) -> None:
    """Handle: wid parse <id> [--kind wid|hlc] [--W n] [--Z n] [--time-unit sec|ms] [--json]."""
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
            print(json.dumps({
                "raw": result_h.raw,
                "timestamp": result_h.timestamp.isoformat(),
                "logical_counter": result_h.logical_counter,
                "node": result_h.node,
                "padding": result_h.padding,
            }, separators=(",", ":")))
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
            print(json.dumps({
                "raw": result.raw,
                "timestamp": result.timestamp.isoformat(),
                "sequence": result.sequence,
                "padding": result.padding,
            }, separators=(",", ":")))
        else:
            print(f"raw={result.raw}")
            print(f"timestamp={result.timestamp.isoformat()}")
            print(f"sequence={result.sequence}")
            print(f"padding={result.padding or ''}")


def main() -> None:
    """Wid main entrypoint."""
    if len(sys.argv) >= 2 and sys.argv[1] == "__daemon":
        try:
            _run_canonical(sys.argv[2:])
            return
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(2)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        except subprocess.CalledProcessError as exc:
            sys.exit(exc.returncode)

    if len(sys.argv) >= 2 and sys.argv[1] in {"-h", "--help", "help"}:
        _print_usage()
        return

    try:
        if _run_canonical(sys.argv[1:]):
            return
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)

    # Default: no args => emit ONE id and exit (unless env forces bench/stream).
    if len(sys.argv) == 1:
        default_mode = _env_default_mode()
        if default_mode == "stream":
            _run_emit_mode("stream", [])
            return
        else:
            _run_emit_mode("next", [])
            return

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

    print(f"Unknown command: {cmd}", file=sys.stderr)
    sys.exit(2)


def _run_canonical_entry(action: str) -> None:
    original = list(sys.argv)
    try:
        sys.argv = [sys.argv[0], f"A={action}", *original[1:]]
        main()
    finally:
        sys.argv = original


def _run_cli_entry(args: list[str]) -> None:
    original = list(sys.argv)
    try:
        sys.argv = [sys.argv[0], *args, *original[1:]]
        main()
    finally:
        sys.argv = original


def id_main() -> None:
    """Default id command."""
    _run_canonical_entry("next")


def default_main() -> None:
    """Default main command."""
    _run_canonical_entry("run")


def widas_main() -> None:
    """Default widas command."""
    _run_canonical_entry("run")


def widas_start_main() -> None:
    """Default widas start command."""
    _run_canonical_entry("start")


def widas_stop_main() -> None:
    """Default widas stop command."""
    _run_canonical_entry("stop")


def widas_status_main() -> None:
    """Default widas stop command."""
    _run_canonical_entry("status")


def widas_logs_main() -> None:
    """Default widas logs command."""
    _run_canonical_entry("logs")


def saf_main() -> None:
    """Default saf command."""
    _run_canonical_entry("saf")


def raf_main() -> None:
    """Default raf command."""
    _run_canonical_entry("raf")


def saf_wid_main() -> None:
    """Default saf wid command."""
    _run_canonical_entry("saf-wid")


def waf_main() -> None:
    """Default waf command."""
    _run_canonical_entry("waf")


def wraf_main() -> None:
    """Default wraf command."""
    _run_canonical_entry("wraf")


def wir_main() -> None:
    """Default wir command."""
    _run_canonical_entry("wir")


def wer_main() -> None:
    """Default wer command."""
    _run_canonical_entry("wir")


def witr_main() -> None:
    """Default witr command."""
    _run_canonical_entry("witr")


def wism_main() -> None:
    """Default wism command."""
    _run_canonical_entry("wism")


def wim_main() -> None:
    """Default wim command."""
    _run_canonical_entry("wim")


def wihp_main() -> None:
    """Default wihp command."""
    _run_canonical_entry("wihp")


def wih_main() -> None:
    """Default wih command."""
    _run_canonical_entry("wih")


def wipr_main() -> None:
    """Default wipr command."""
    _run_canonical_entry("wipr")


def wip_main() -> None:
    """Default wip command."""
    _run_canonical_entry("wip")


def duplex_main() -> None:
    """Default duplex command."""
    _run_canonical_entry("duplex")


def hlc_wid_main() -> None:
    """Default hlc-wid command."""
    _run_cli_entry(["next", "--kind", "hlc"])


if __name__ == "__main__":
    main()
