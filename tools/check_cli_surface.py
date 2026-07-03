#!/usr/bin/env python3
"""Cross-language CLI-surface conformance check.

The six CLIs re-implement the same flag matrix, KEY=VALUE parsing, and
defaults table by hand — the most duplicated, most drift-prone code in the
repository. This harness drives every real CLI through the shared fixture
``spec/conformance/cli_surface.json``:

* ``emit`` cases MUST exit 0, print exactly ``lines`` stdout lines, and every
  line must match the identifier shape implied by the case's params
  (W/Z/time_unit/kind/node) — this pins the *defaults table* as much as the
  flags, since most cases rely on defaults; a case may also carry
  ``min_seconds`` to assert cadence (an explicit ``L=n`` stream must sleep);
* ``reject`` cases MUST exit nonzero, say something on stderr, and MUST NOT
  crash (no Python traceback, no Rust/Go panic) — a clean diagnostic is part
  of the shared surface.

Exit codes are asserted nonzero, not exact: implementations currently use a
mix of 1 and 2 and that mix is not (yet) a conformance target.

The sh implementation is pinned to ``I=sh`` in canonical mode so its native
parser is exercised rather than its Python delegation.

Set ``CLI_SURFACE_STRICT=1`` to fail when an implementation is skipped
(missing binary/runtime) rather than only when a case disagrees.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "spec" / "conformance" / "cli_surface.json"

CRASH_MARKERS = ("Traceback (most recent call last)", "panicked at", "goroutine 1 [")


def choose_python_cmd() -> list[str]:
    for candidate in (["python3"], ["python"]):
        if shutil.which(candidate[0]):
            return candidate
    return ["python3"]


def available_impls() -> tuple[dict[str, tuple[list[str], dict[str, str] | None]], list[str]]:
    go_env = {**os.environ, "GOCACHE": str((ROOT / ".local" / "go-cache").resolve())}
    candidates: dict[str, tuple[list[str], dict[str, str] | None]] = {
        "sh": (["bash", "sh/wid"], None),
        "python": (choose_python_cmd() + ["-m", "wid"], {**os.environ, "PYTHONPATH": "python"}),
        "typescript": (["node", "dist/cli.js"], None),
        "go": ([str(ROOT / "go" / "cmd" / "wid" / "wid")], go_env),
        "rust": (["target/debug/wid"], None),
        "c": (["c/.build/wid"], None),
    }
    impls: dict[str, tuple[list[str], dict[str, str] | None]] = {}
    skipped: list[str] = []
    for name, (base, env) in candidates.items():
        exe = base[0]
        if "/" in exe:
            if not (ROOT / exe).exists() and not Path(exe).exists():
                skipped.append(f"{name} (missing binary: {exe})")
                continue
        elif shutil.which(exe) is None:
            skipped.append(f"{name} (missing runtime: {exe})")
            continue
        impls[name] = (base, env)
    return impls, skipped


def shape_pattern(params: dict) -> re.Pattern[str]:
    w = int(params.get("W", 4))
    z = int(params.get("Z", 6))
    ts = r"\d{8}T\d{9}" if params.get("time_unit", "sec") == "ms" else r"\d{8}T\d{6}"
    body = rf"{ts}\.\d{{{w}}}Z"
    if params.get("kind", "wid") == "hlc":
        node = re.escape(str(params.get("node", "")))
        body += rf"-{node}" if node else r"-[A-Za-z0-9_]+"
    if z > 0:
        body += rf"-[0-9a-f]{{{z}}}"
    return re.compile(rf"^{body}$")


def case_args(impl: str, args: list[str]) -> list[str]:
    # Pin sh to its native canonical parser instead of Python delegation.
    if impl == "sh" and any("=" in a for a in args) and not any(a.startswith("I=") for a in args):
        return [*args, "I=sh"]
    return args


def run_case(base: list[str], env: dict[str, str] | None, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*base, *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def main() -> int:
    fixture = json.loads(FIXTURE.read_text())
    impls, skipped = available_impls()
    strict = os.environ.get("CLI_SURFACE_STRICT", "0") == "1"

    failures: list[str] = []
    total = 0

    for impl, (base, env) in impls.items():
        for case in fixture["emit"]:
            total += 1
            args = case_args(impl, list(case["args"]))
            started = time.monotonic()
            proc = run_case(base, env, args)
            elapsed = time.monotonic() - started
            lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
            pattern = shape_pattern(case.get("params") or {})
            min_seconds = float(case.get("min_seconds", 0))
            if proc.returncode != 0:
                failures.append(f"{impl}: emit {case['name']}: rc={proc.returncode} stderr={proc.stderr.strip()[:200]}")
            elif len(lines) != int(case["lines"]):
                failures.append(f"{impl}: emit {case['name']}: expected {case['lines']} lines, got {len(lines)}")
            elif elapsed < min_seconds:
                failures.append(
                    f"{impl}: emit {case['name']}: finished in {elapsed:.2f}s "
                    f"but the case requires >= {min_seconds}s (L= cadence ignored?)"
                )
            else:
                for ln in lines:
                    if not pattern.match(ln):
                        failures.append(f"{impl}: emit {case['name']}: line {ln!r} !~ {pattern.pattern}")
                        break

        for case in fixture["reject"]:
            total += 1
            args = case_args(impl, list(case["args"]))
            proc = run_case(base, env, args)
            combined = proc.stdout + proc.stderr
            if proc.returncode == 0:
                failures.append(f"{impl}: reject {case['name']}: accepted (rc=0, stdout={proc.stdout.strip()[:120]!r})")
            elif not proc.stderr.strip():
                failures.append(f"{impl}: reject {case['name']}: rc={proc.returncode} but stderr is empty")
            else:
                for marker in CRASH_MARKERS:
                    if marker in combined:
                        failures.append(f"{impl}: reject {case['name']}: crashed instead of clean error ({marker!r})")
                        break

    for line in skipped:
        print(f"skip: {line}", file=sys.stderr)
    for line in failures:
        print(f"FAIL: {line}", file=sys.stderr)

    ok = not failures and (not strict or not skipped)
    print(
        f"cli-surface: impls={len(impls)} cases={total} "
        f"fail={len(failures)} skipped={len(skipped)} -> {'OK' if ok else 'FAIL'}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
