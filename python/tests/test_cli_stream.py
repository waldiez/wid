"""Tests for the flag-mode stream surface.

``--interval-ms`` is the flag-mode spelling of the canonical ``L=`` cadence;
the sh implementation delegates its canonical ``A=stream`` here, so removing
or renaming the flag breaks ``sh/wid A=stream`` (and ``make stream``) on any
machine with a Python runtime.
"""

# pylint: disable=missing-function-docstring

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.resolve()


def run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    local_py = str(REPO_ROOT / "python")
    env["PYTHONPATH"] = (
        f"{local_py}{os.pathsep}{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else local_py
    )
    return subprocess.run(
        [sys.executable, "-m", "wid.cli", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_stream_accepts_interval_ms() -> None:
    result = run_cli(["stream", "--count", "3", "--interval-ms", "1"])
    assert result.returncode == 0, result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 3


def test_stream_interval_ms_zero_is_back_to_back() -> None:
    result = run_cli(["stream", "--count", "2", "--interval-ms", "0"])
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 2


def test_stream_rejects_negative_interval_ms() -> None:
    result = run_cli(["stream", "--count", "2", "--interval-ms", "-5"])
    assert result.returncode != 0
    assert "interval-ms" in result.stderr
