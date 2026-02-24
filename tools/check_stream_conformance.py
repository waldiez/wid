#!/usr/bin/env python3
"""Cross-language conformance checks for canonical stream semantics."""

# pylint: skip-file
# flake8: noqa: D103, C901, E501
# pyright: reportArgumentType=false,reportAny=false

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "spec" / "conformance" / "stream.json"


def run(
    cmd: list[str], timeout_sec: int | None = None, env: dict[str, str] | None = None
) -> tuple[int, str, bool]:
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
    blocked: dict[str, str] = {}
    # C binary
    if not (ROOT / "c" / ".build" / "wid").exists():
        subprocess.run(["make", "-C", "c", "setup"], cwd=ROOT, check=True)
    # TypeScript dist
    if shutil.which("node") and shutil.which("npm") and not (ROOT / "typescript" / "dist" / "cli.js").exists():
        if not (ROOT / "node_modules").exists():
            subprocess.run(["npm", "install"], cwd=ROOT, check=True)
        subprocess.run(["npm", "run", "build"], cwd=ROOT, check=True)
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
    return [f"{k}={v}" for k, v in d.items()]


def choose_python_cmd() -> list[str]:
    venv_py = ROOT / ".venv" / "bin" / "python"
    if venv_py.exists():
        return [str(venv_py)]
    return [sys.executable]


def main() -> int:
    strict_toolchains = os.environ.get("WID_STRICT_TOOLCHAINS", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    blocked = ensure_builds()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = fixture["test_cases"]
    py_cmd = choose_python_cmd()
    go_env = {**os.environ, "GOCACHE": str((ROOT / ".local" / "go-cache").resolve())}

    candidate_impls: dict[str, tuple[list[str], dict[str, str] | None]] = {
        "sh": (["bash", "sh/wid"], None),
        "rust": (["target/debug/wid"], None),
        "c": (["c/.build/wid"], None),
        "go": ([str(ROOT / "go" / "cmd" / "wid" / "wid")], go_env),
        "typescript": (["node", "typescript/dist/cli.js"], None),
        "python": (py_cmd + ["-m", "wid"], {**os.environ, "PYTHONPATH": "python", "PYTHONUNBUFFERED": "1"}),
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

    if not impls:
        print(
            "Stream conformance skipped: no runnable implementations found in this environment.",
            file=sys.stderr,
        )
        return 0
    if strict_toolchains and skipped:
        print("Stream conformance strict mode failed: missing implementations:", file=sys.stderr)
        for item in skipped:
            print(f"- {item}", file=sys.stderr)
        return 1

    failures: list[str] = []

    for impl, (base, extra_env) in impls.items():
        for case in cases:
            cid = case["id"]
            canonical = dict(case["canonical"])
            if impl == "sh":
                canonical.setdefault("I", "sh")
            canon = kv_args(canonical)
            expect = case["expect"]

            if expect["mode"] == "infinite":
                rc, out, timed_out = run(
                    base + canon, timeout_sec=int(expect["timeout_sec"]), env=extra_env
                )
                lines = len([ln for ln in out.splitlines() if ln.strip()])
                if not timed_out:
                    failures.append(
                        f"{impl}:{cid}: expected timeout/infinite, got rc={rc}"
                    )
                elif lines < int(expect["min_lines"]):
                    failures.append(
                        f"{impl}:{cid}: expected >= {expect['min_lines']} lines before timeout, got {lines}"
                    )
            elif expect["mode"] == "bounded":
                rc, out, timed_out = run(base + canon, timeout_sec=10, env=extra_env)
                lines = len([ln for ln in out.splitlines() if ln.strip()])
                if timed_out:
                    failures.append(f"{impl}:{cid}: unexpected timeout")
                elif rc != 0:
                    failures.append(f"{impl}:{cid}: non-zero exit rc={rc}")
                elif lines != int(expect["lines"]):
                    failures.append(
                        f"{impl}:{cid}: expected {expect['lines']} lines, got {lines}"
                    )
            else:
                failures.append(f"{impl}:{cid}: unknown mode {expect['mode']}")

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


if __name__ == "__main__":
    raise SystemExit(main())
