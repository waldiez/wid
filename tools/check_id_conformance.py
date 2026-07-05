#!/usr/bin/env python3
"""Cross-language WID identifier conformance check.

Runs the shared fixtures ``spec/conformance/valid.json`` and
``spec/conformance/invalid.json`` through every available implementation's
``validate`` subcommand and asserts that all of them agree with the fixtures
(and therefore with each other):

* every WID in ``valid.json`` MUST be accepted (exit 0);
* every WID in ``invalid.json`` MUST be rejected (exit != 0).

Every case is run through both ``validate`` and ``parse``: the two subcommands
MUST agree (a parse that accepts what validate rejects -- impossible calendar
values, bad node charsets -- is a cross-implementation divergence).

It also runs ``spec/conformance/generation_bounds.json`` through canonical-mode
generation (``A=next W=... Z=...``): out-of-range or non-integer W/Z MUST be
rejected (SPEC.md makes this mandatory for generation, not just validation),
and every accepted boundary case must round-trip through the same
implementation's ``validate``. The sh implementation is pinned to ``I=sh`` so
its native generator is exercised rather than its Python delegation.

This is the executable harness backing the repository's cross-language
identifier-conformance claim. It complements ``check_wotp_parity.sh`` and
``smoke_crypto.sh`` (crypto) and ``check_stream_conformance.py`` (streaming).

Set ``ID_CONFORMANCE_STRICT=1`` to fail when any implementation is skipped
(e.g. its binary was not built), rather than only when a case disagrees.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VALID = ROOT / "spec" / "conformance" / "valid.json"
INVALID = ROOT / "spec" / "conformance" / "invalid.json"
GENERATION_BOUNDS = ROOT / "spec" / "conformance" / "generation_bounds.json"


def choose_python_cmd() -> list[str]:
    """Pick the first available Python interpreter command."""
    for candidate in (["python3"], ["python"]):
        if shutil.which(candidate[0]):
            return candidate
    return ["python3"]


def available_impls() -> tuple[
    dict[str, tuple[list[str], dict[str, str] | None]], list[str]
]:
    """Map implementation name to (argv prefix, env), plus skipped names."""
    go_env = {**os.environ, "GOCACHE": str((ROOT / ".local" / "go-cache").resolve())}
    candidates: dict[str, tuple[list[str], dict[str, str] | None]] = {
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


def case_args(case: dict[str, Any], subcommand: str) -> list[str]:
    """Build the validate/parse argv for one fixture case."""
    params: dict[str, Any] = case.get("params") or {}
    w = int(params.get("W", 4))
    z = int(params.get("Z", 6))
    time_unit = params.get("time_unit", "sec")
    kind = case.get("type", "wid")
    args = [subcommand, case["wid"], "--kind", kind, "--W", str(w), "--Z", str(z)]
    if time_unit != "sec":
        args += ["--time-unit", time_unit]
    return args


def accepts(
    base: list[str], env: dict[str, str] | None, case: dict[str, Any], subcommand: str
) -> bool:
    """Return True if the implementation exits 0 for this fixture case."""
    proc = subprocess.run(
        base + case_args(case, subcommand),
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.returncode == 0


def check_generation(
    name: str, base: list[str], env: dict[str, str] | None, case: dict[str, Any]
) -> str | None:
    """Return a failure description, or None if the case behaves as expected."""
    params = case["params"]
    args = ["A=next", f"W={params['W']}", f"Z={params['Z']}", "T=sec", "E=stateless"]
    if name == "sh":
        args.append("I=sh")
    proc = subprocess.run(
        base + args,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    accepted = proc.returncode == 0
    if case["expect"] == "reject":
        if accepted:
            emitted = proc.stdout.strip()
            return (
                f"generation/{case['id']} (W={params['W']} Z={params['Z']}) "
                f"wrongly ACCEPTED, emitted: {emitted!r}"
            )
        return None
    if not accepted:
        return (
            f"generation/{case['id']} (W={params['W']} Z={params['Z']}) "
            f"wrongly REJECTED: {proc.stderr.strip()!r}"
        )
    emitted = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    validate_args = [
        "validate",
        emitted,
        "--kind",
        "wid",
        "--W",
        str(params["W"]),
        "--Z",
        str(params["Z"]),
    ]
    round_trip = subprocess.run(
        base + validate_args,
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if round_trip.returncode != 0:
        return (
            f"generation/{case['id']} output failed its own validate "
            f"round-trip: {emitted!r}"
        )
    return None


Fixtures = tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
]  # (valid, invalid, generation_bounds)


def run_impl(
    name: str,
    base: list[str],
    env: dict[str, str] | None,
    fixtures: Fixtures,
) -> list[str]:
    """Run every fixture case through one implementation; return failures."""
    valid_cases, invalid_cases, generation_cases = fixtures
    failures: list[str] = []
    for subcommand in ("validate", "parse"):
        for case in valid_cases:
            if not accepts(base, env, case, subcommand):
                failures.append(
                    f"valid/{case['id']} ({case['wid']})"
                    + f" wrongly REJECTED by {subcommand}"
                )
        for case in invalid_cases:
            if accepts(base, env, case, subcommand):
                failures.append(
                    f"invalid/{case['id']} ({case['wid']})"
                    + f" wrongly ACCEPTED by {subcommand}"
                )
    for case in generation_cases:
        failure = check_generation(name, base, env, case)
        if failure is not None:
            failures.append(failure)
    return failures


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Load the test_cases array from one fixture file."""
    cases: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))[
        "test_cases"
    ]
    return cases


def main() -> int:
    """Run all fixtures through every implementation; 0 iff all agree."""
    strict = os.environ.get("ID_CONFORMANCE_STRICT") == "1"
    fixtures = (load_cases(VALID), load_cases(INVALID), load_cases(GENERATION_BOUNDS))
    impls, skipped = available_impls()

    if not impls:
        print(
            "id-conformance skipped: no runnable implementations found.",
            file=sys.stderr,
        )
        return 0

    total_mismatches = 0
    for name, (base, env) in impls.items():
        failures = run_impl(name, base, env, fixtures)
        if failures:
            total_mismatches += len(failures)
            print(f"FAIL: {name} ({len(failures)} mismatch(es))")
            for failure in failures:
                print(f"    - {failure}")
        else:
            valid_cases, invalid_cases, generation_cases = fixtures
            case_count = 2 * (len(valid_cases) + len(invalid_cases)) + len(
                generation_cases
            )
            print(f"PASS: {name} ({case_count} cases)")

    if skipped:
        print("Skipped: " + ", ".join(skipped))

    if total_mismatches:
        print(f"ID conformance FAILED: {total_mismatches} mismatch(es)")
        return 1
    if strict and skipped:
        print("ID_CONFORMANCE_STRICT=1 and skipped implementations detected.")
        return 1
    print("ID conformance passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
