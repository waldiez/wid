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
  of the shared surface;
* ``parity`` cases MUST exit 0 and produce identical output in every
  implementation (lines that parse as JSON are compared as parsed objects,
  so key order does not matter) — this catches silent cross-language
  divergence, e.g. one parser truncating a ``KEY=abc=def`` value and
  deriving a different OTP from the same secret;
* ``infinite`` cases MUST still be running after ``run_seconds`` (0 means an
  unbounded stream everywhere, never "some default count") and must have
  produced at least ``min_lines`` shape-conformant lines by then.

Exit codes follow the shared contract in ``spec/quick-usage.md`` ("Exit
codes"): usage errors (unknown command/flag/key/action, missing required
value, out-of-range parameter) exit **2**; operational failures (invalid id,
verification failure, missing/unreadable files, runtime errors) exit **1**.
Reject cases pin the exact code with ``exit_code``; a case may also set
``allow_empty_stderr`` when the stdout verdict (e.g. validate's ``false``)
is the diagnostic.

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
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "spec" / "conformance" / "cli_surface.json"

CRASH_MARKERS = ("Traceback (most recent call last)", "panicked at", "goroutine 1 [")

# argv prefix + optional environment override for one implementation
Impl = tuple[list[str], dict[str, str] | None]


def choose_python_cmd() -> list[str]:
    """Pick the first available Python interpreter command."""
    for candidate in (["python3"], ["python"]):
        if shutil.which(candidate[0]):
            return candidate
    return ["python3"]


def available_impls() -> tuple[dict[str, Impl], list[str]]:
    """Map implementation name to (argv prefix, env), plus skipped names."""
    go_env = {**os.environ, "GOCACHE": str((ROOT / ".local" / "go-cache").resolve())}
    candidates: dict[str, Impl] = {
        "sh": (["bash", "sh/wid"], None),
        "python": (
            choose_python_cmd() + ["-m", "wid"],
            {**os.environ, "PYTHONPATH": "python"},
        ),
        "typescript": (["node", "dist/cli.js"], None),
        "go": ([str(ROOT / "go" / "cmd" / "wid" / "wid")], go_env),
        "rust": (["target/debug/wid"], None),
        "c": (["c/.build/wid"], None),
    }
    impls: dict[str, Impl] = {}
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


def shape_pattern(params: dict[str, Any]) -> re.Pattern[str]:
    """Build the exact-match regex for the WID shape a case's params imply."""
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
    """Pin sh to its native canonical parser instead of Python delegation."""
    has_kv = any("=" in a for a in args)
    if impl == "sh" and has_kv and not any(a.startswith("I=") for a in args):
        return [*args, "I=sh"]
    return args


def run_case(
    base: list[str], env: dict[str, str] | None, args: list[str]
) -> subprocess.CompletedProcess[str]:
    """Run one bounded case to completion, capturing text output."""
    return subprocess.run(
        [*base, *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def normalized_output(stdout: str) -> list[Any]:
    """Normalize stdout for cross-implementation comparison.

    Lines that parse as JSON are compared as parsed objects so that key
    order (which legitimately differs between implementations) is ignored.
    """
    out: list[Any] = []
    for ln in stdout.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            out.append(ln)
    return out


def run_infinite_case(
    base: list[str], env: dict[str, str] | None, args: list[str], run_seconds: float
) -> tuple[bool, str]:
    """Run a case that must not terminate; return (still_running, stdout)."""
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        [*base, *args],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(run_seconds)
    still_running = proc.poll() is None
    proc.terminate()
    try:
        stdout, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, _ = proc.communicate()
    return still_running, stdout


def check_emit(
    impl: str, base: list[str], env: dict[str, str] | None, case: dict[str, Any]
) -> str | None:
    """Check one emit case; return a failure description or None."""
    tag = f"{impl}: emit {case['name']}"
    args = case_args(impl, list(case["args"]))
    started = time.monotonic()
    proc = run_case(base, env, args)
    elapsed = time.monotonic() - started
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    pattern = shape_pattern(case.get("params") or {})
    min_seconds = float(case.get("min_seconds", 0))
    if proc.returncode != 0:
        return f"{tag}: rc={proc.returncode} stderr={proc.stderr.strip()[:200]}"
    if len(lines) != int(case["lines"]):
        return f"{tag}: expected {case['lines']} lines, got {len(lines)}"
    if elapsed < min_seconds:
        return (
            f"{tag}: finished in {elapsed:.2f}s but the case requires"
            + f" >= {min_seconds}s (L= cadence ignored?)"
        )
    for ln in lines:
        if not pattern.match(ln):
            return f"{tag}: line {ln!r} !~ {pattern.pattern}"
    return None


def check_reject(
    impl: str, base: list[str], env: dict[str, str] | None, case: dict[str, Any]
) -> str | None:
    """Check one reject case; return a failure description or None."""
    tag = f"{impl}: reject {case['name']}"
    args = case_args(impl, list(case["args"]))
    proc = run_case(base, env, args)
    combined = proc.stdout + proc.stderr
    if proc.returncode == 0:
        return f"{tag}: accepted (rc=0, stdout={proc.stdout.strip()[:120]!r})"
    # allow_empty_stderr: for validate-style verdicts the stdout "false" is
    # the diagnostic; every other reject must say something on stderr.
    if not proc.stderr.strip() and not case.get("allow_empty_stderr"):
        return f"{tag}: rc={proc.returncode} but stderr is empty"
    for marker in CRASH_MARKERS:
        if marker in combined:
            return f"{tag}: crashed instead of clean error ({marker!r})"
    want_rc = case.get("exit_code")
    if want_rc is not None and proc.returncode != int(want_rc):
        return (
            f"{tag}: rc={proc.returncode}, case pins exact rc={want_rc}"
            + " (verification outcomes must use the same exit code everywhere)"
        )
    return None


def check_infinite(
    impl: str, base: list[str], env: dict[str, str] | None, case: dict[str, Any]
) -> str | None:
    """Check one unbounded-stream case; return a failure description or None."""
    tag = f"{impl}: infinite {case['name']}"
    args = case_args(impl, list(case["args"]))
    run_seconds = float(case["run_seconds"])
    still_running, stdout = run_infinite_case(base, env, args, run_seconds)
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    pattern = shape_pattern(case.get("params") or {})
    if not still_running:
        return (
            f"{tag}: terminated on its own after {len(lines)} lines"
            + " (0 must mean unbounded, not a default count)"
        )
    if len(lines) < int(case["min_lines"]):
        return (
            f"{tag}: only {len(lines)} lines in {case['run_seconds']}s"
            + f" (expected >= {case['min_lines']})"
        )
    for ln in lines:
        if not pattern.match(ln):
            return f"{tag}: line {ln!r} !~ {pattern.pattern}"
    return None


SECTION_CHECKS = (
    ("emit", check_emit),
    ("reject", check_reject),
    ("infinite", check_infinite),
)


def check_parity(impls: dict[str, Impl], case: dict[str, Any]) -> list[str]:
    """Run one parity case across all implementations; return failures.

    Parity cases compare implementations against each other, so they run
    after the per-implementation loops.
    """
    failures: list[str] = []
    outputs: dict[str, list[Any]] = {}
    for impl, (base, env) in impls.items():
        args = case_args(impl, list(case["args"]))
        proc = run_case(base, env, args)
        if proc.returncode != 0:
            err = proc.stderr.strip()[:200]
            failures.append(
                f"{impl}: parity {case['name']}: rc={proc.returncode} stderr={err}"
            )
            continue
        outputs[impl] = normalized_output(proc.stdout)
    if len(outputs) > 1:
        reference_impl = sorted(outputs)[0]
        reference = outputs[reference_impl]
        for impl, got in sorted(outputs.items()):
            if got != reference:
                failures.append(
                    f"{impl}: parity {case['name']}: output diverges from"
                    + f" {reference_impl}: {got!r} != {reference!r}"
                )
    return failures


def main() -> int:
    """Run every fixture section against every implementation; 0 iff green."""
    fixture: dict[str, Any] = json.loads(FIXTURE.read_text())
    impls, skipped = available_impls()
    strict = os.environ.get("CLI_SURFACE_STRICT", "0") == "1"

    failures: list[str] = []
    total = 0

    for impl, (base, env) in impls.items():
        for section, check in SECTION_CHECKS:
            for case in fixture.get(section, []):
                total += 1
                failure = check(impl, base, env, case)
                if failure is not None:
                    failures.append(failure)

    for case in fixture.get("parity", []):
        total += len(impls)
        failures.extend(check_parity(impls, case))

    for line in skipped:
        print(f"skip: {line}", file=sys.stderr)
    for line in failures:
        print(f"FAIL: {line}", file=sys.stderr)

    ok = not failures and (not strict or not skipped)
    print(
        f"cli-surface: impls={len(impls)} cases={total}"
        + f" fail={len(failures)} skipped={len(skipped)} -> {'OK' if ok else 'FAIL'}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
