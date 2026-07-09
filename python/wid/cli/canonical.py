"""Canonical ``KEY=VALUE`` dispatcher and sh-implementation delegation.

The dispatcher is one long function on purpose: it mirrors the switch/case
dispatch tables of the other five implementations.
"""

# pyright: reportUnusedCallResult=false,reportAny=false

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ..core import TimeUnitName, parse_time_unit
from ..parse import validate_wid
from ..wid import WidGen
from .crypto import run_sign_mode, run_verify_mode, run_wotp_mode
from .help import print_actions
from .sql import sql_allocate_next_wid, sql_state_path

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


def _delegate_to_shell(canon: dict[str, str]) -> None:
    """Delegate I=sh/I=bash to the sibling sh/wid script (raises if unavailable)."""
    if os.name == "nt":
        # sh/wid is a bash script; Windows cannot exec it directly (and a
        # checkout usually has no bash). Refuse up front with a clear message
        # instead of a cryptic subprocess exec error.
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


def _emit_one_wid(
    gen: WidGen,
    state_mode: str,
    w_val: int,
    z_val: int,
    time_unit: TimeUnitName,
    data_dir: Path,
) -> None:
    """Print one WID via the shared SQL CAS row (E=sql) or the in-process gen."""
    if state_mode == "sql":
        print(
            sql_allocate_next_wid(w_val, z_val, time_unit, sql_state_path(data_dir)),
            flush=True,
        )
    else:
        print(gen.next(), flush=True)


def _canonical_next(
    w_val: int, z_val: int, time_unit: TimeUnitName, state_mode: str, data_dir: Path
) -> None:
    """Emit one WID (A=next)."""
    gen = WidGen(w=w_val, z=z_val, time_unit=time_unit)
    _emit_one_wid(gen, state_mode, w_val, z_val, time_unit, data_dir)


def _canonical_healthcheck(w_val: int, z_val: int, time_unit: TimeUnitName) -> None:
    """Emit a sample WID plus a JSON validity report (A=healthcheck)."""
    gen = WidGen(w=w_val, z=z_val, time_unit=time_unit)
    sample = gen.next()
    ok = validate_wid(sample, W=w_val, Z=z_val, time_unit=time_unit)
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


def _canonical_stream(
    w_val: int,
    z_val: int,
    l_val: int,
    n_val: int,
    time_unit: TimeUnitName,
    state_mode: str,
    data_dir: Path,
) -> None:
    """Emit N WIDs (0 = unbounded) with an L-second cadence (A=stream)."""
    gen = WidGen(w=w_val, z=z_val, time_unit=time_unit)
    emitted = 0
    while n_val == 0 or emitted < n_val:
        _emit_one_wid(gen, state_mode, w_val, z_val, time_unit, data_dir)
        emitted += 1
        if n_val == 0 or emitted < n_val:
            time.sleep(max(0, l_val))


# The canonical KEY=VALUE dispatcher is one deliberate action table,
# mirroring the switch/case dispatchers of the other five implementations.
def run_canonical(argv: list[str]) -> bool:  # noqa: C901
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
        print_actions()
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
            _delegate_to_shell(canon)
        elif action == "next":
            _canonical_next(w_val, z_val, effective_time_unit, state_mode, data_dir)
        elif action == "healthcheck":
            _canonical_healthcheck(w_val, z_val, effective_time_unit)
        else:
            _canonical_stream(
                w_val, z_val, l_val, n_val, effective_time_unit, state_mode, data_dir
            )
        return True

    if action == "sign":
        run_sign_mode(canon)
        return True

    if action == "verify":
        run_verify_mode(canon)
        return True

    if action == "w-otp":
        run_wotp_mode(canon, w_val=w_val, z_val=z_val, time_unit=time_unit)
        return True

    raise ValueError(f"unknown A={action}")
