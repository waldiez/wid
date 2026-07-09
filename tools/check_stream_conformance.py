#!/usr/bin/env python3
"""Cross-language conformance checks for canonical stream semantics.

Drives every buildable implementation through the ``A=stream`` cases in
``spec/conformance/stream.json``: bounded cases must emit exactly N lines
and exit 0; infinite cases must still be producing output when the timeout
fires. Set ``WID_STRICT_TOOLCHAINS=1`` to fail on skipped implementations.
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
FIXTURE = ROOT / "spec" / "conformance" / "stream.json"


def run(
    cmd: list[str], timeout_sec: int | None = None, env: dict[str, str] | None = None
) -> tuple[int, str, bool]:
    """Run a command; return (returncode, stdout, timed_out)."""
    try:
        p = subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        return p.returncode, p.stdout, False
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        return 124, out, True


def ensure_builds() -> dict[str, str]:
    """Build any missing implementation binaries; map name -> block reason."""
    blocked: dict[str, str] = {}
    # C binary
    if not (ROOT / "c" / ".build" / "wid").exists():
        subprocess.run(["make", "-C", "c", "setup"], cwd=ROOT, check=True)
    # TypeScript dist
    has_bun = shutil.which("bun")
    if has_bun and not (ROOT / "dist" / "cli.js").exists():
        if not (ROOT / "node_modules").exists():
            subprocess.run(["bun", "install"], cwd=ROOT, check=True)
        subprocess.run(["bun", "run", "build"], cwd=ROOT, check=True)
    # Rust binary
    if shutil.which("cargo") and not (ROOT / "target" / "debug" / "wid").exists():
        try:
            subprocess.run(["cargo", "build", "-q"], cwd=ROOT, check=True)
        except subprocess.CalledProcessError as e:
            blocked["rust"] = f"cargo build failed (rc={e.returncode})"
    # Go binary
    go_bin = ROOT / "go" / "cmd" / "wid" / "wid"
    if shutil.which("go") and not go_bin.exists():
        env = {**os.environ, "GOCACHE": str((ROOT / ".local" / "go-cache").resolve())}
        try:
            subprocess.run(
                ["go", "build", "-o", str(go_bin), "./go/cmd/wid"],
                cwd=ROOT,
                env=env,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            blocked["go"] = f"go build failed (rc={e.returncode})"
    return blocked


def kv_args(d: dict[str, str]) -> list[str]:
    """Render a dict as canonical KEY=VALUE CLI arguments."""
    return [f"{k}={v}" for k, v in d.items()]


def choose_python_cmd() -> list[str]:
    """Prefer the repo venv's interpreter, else the current one."""
    venv_py = ROOT / ".venv" / "bin" / "python"
    if venv_py.exists():
        return [str(venv_py)]
    return [sys.executable]


def pick_impls(
    blocked: dict[str, str],
) -> tuple[dict[str, tuple[list[str], dict[str, str] | None]], list[str]]:
    """Select runnable implementations; return (impls, skipped descriptions)."""
    py_cmd = choose_python_cmd()
    go_env = {**os.environ, "GOCACHE": str((ROOT / ".local" / "go-cache").resolve())}
    candidate_impls: dict[str, tuple[list[str], dict[str, str] | None]] = {
        "sh": (["bash", "sh/wid"], None),
        "rust": (["target/debug/wid"], None),
        "c": (["c/.build/wid"], None),
        "go": ([str(ROOT / "go" / "cmd" / "wid" / "wid")], go_env),
        "typescript": (["node", "dist/cli.js"], None),
        "python": (
            py_cmd + ["-m", "wid"],
            {**os.environ, "PYTHONPATH": "python", "PYTHONUNBUFFERED": "1"},
        ),
    }
    impls: dict[str, tuple[list[str], dict[str, str] | None]] = {}
    skipped: list[str] = []
    for impl, (base, extra_env) in candidate_impls.items():
        if impl in blocked:
            skipped.append(f"{impl} ({blocked[impl]})")
            continue
        exe = base[0]
        if "/" in exe:
            if not (ROOT / exe).exists():
                skipped.append(f"{impl} (missing built binary: {exe})")
                continue
        else:
            if shutil.which(exe) is None:
                skipped.append(f"{impl} (missing runtime: {exe})")
                continue
        impls[impl] = (base, extra_env)
    return impls, skipped


# One early return per failure mode keeps the checks table-shaped.
def run_stream_case(  # pylint: disable=too-many-return-statements
    impl: str,
    base: list[str],
    extra_env: dict[str, str] | None,
    case: dict[str, Any],
) -> str | None:
    """Run one stream case; return a failure description or None."""
    cid = case["id"]
    canonical: dict[str, str] = dict(case["canonical"])
    if impl == "sh":
        canonical.setdefault("I", "sh")
    canon = kv_args(canonical)
    expect: dict[str, Any] = case["expect"]

    if expect["mode"] == "infinite":
        rc, out, timed_out = run(
            base + canon, timeout_sec=int(expect["timeout_sec"]), env=extra_env
        )
        lines = len([ln for ln in out.splitlines() if ln.strip()])
        if not timed_out:
            return f"{impl}:{cid}: expected timeout/infinite, got rc={rc}"
        if lines < int(expect["min_lines"]):
            return (
                f"{impl}:{cid}: expected >= {expect['min_lines']} lines"
                + f" before timeout, got {lines}"
            )
        return None
    if expect["mode"] == "bounded":
        rc, out, timed_out = run(base + canon, timeout_sec=30, env=extra_env)
        emitted = [ln for ln in out.splitlines() if ln.strip()]
        if timed_out:
            return f"{impl}:{cid}: unexpected timeout"
        if rc != 0:
            return f"{impl}:{cid}: non-zero exit rc={rc}"
        if len(emitted) != int(expect["lines"]):
            return f"{impl}:{cid}: expected {expect['lines']} lines, got {len(emitted)}"
        if expect.get("unique") and len(set(emitted)) != len(emitted):
            dupes = sorted({ln for ln in emitted if emitted.count(ln) > 1})
            return f"{impl}:{cid}: duplicate IDs emitted (e.g. {dupes[0]!r})"
        return None
    return f"{impl}:{cid}: unknown mode {expect['mode']}"


def report(failures: list[str], skipped: list[str]) -> int:
    """Print the outcome; return the process exit code."""
    if failures:
        print("Stream conformance failed:", file=sys.stderr)
        for f in failures:
            print(f"- {f}", file=sys.stderr)
        return 1

    if skipped:
        print("Stream conformance skipped implementations:")
        for item in skipped:
            print(f"- {item}")
    print("Stream conformance passed")
    return 0


def main() -> int:
    """Run every stream fixture against every implementation; 0 iff green."""
    strict_toolchains = os.environ.get("WID_STRICT_TOOLCHAINS", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    blocked = ensure_builds()
    fixture: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = fixture["test_cases"]
    impls, skipped = pick_impls(blocked)

    if not impls:
        print(
            "Stream conformance skipped: no runnable implementations found"
            + " in this environment.",
            file=sys.stderr,
        )
        return 0
    if strict_toolchains and skipped:
        print(
            "Stream conformance strict mode failed: missing implementations:",
            file=sys.stderr,
        )
        for item in skipped:
            print(f"- {item}", file=sys.stderr)
        return 1

    failures: list[str] = []
    for impl, (base, extra_env) in impls.items():
        for case in cases:
            failure = run_stream_case(impl, base, extra_env, case)
            if failure is not None:
                failures.append(failure)

    return report(failures, skipped)


if __name__ == "__main__":
    raise SystemExit(main())
