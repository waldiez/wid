"""Tests lifecycle."""

# cspell: disable

# pylint: disable=unused-argument
# pyright: reportUnusedParameter=false

import sys
from pathlib import Path
from typing import Any

import pytest

_wid_sys_entry: dict[str, Any] = {"inserted": False, "path": None}


def pytest_sessionstart(session: pytest.Session) -> None:
    """Insert repo root at front of sys.path to prefer local package."""
    # Insert the `python/` package directory so tests import the local package
    pkg_dir = Path(__file__).resolve().parents[1]
    repo_root_str = str(pkg_dir)
    if not sys.path or sys.path[0] != repo_root_str:
        sys.path.insert(0, repo_root_str)
        _wid_sys_entry["inserted"] = True
        _wid_sys_entry["path"] = repo_root_str


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Remove the entry we inserted at session end (if any)."""
    if _wid_sys_entry.get("inserted"):
        try:
            path = _wid_sys_entry.get("path")
            if sys.path and sys.path[0] == path:
                sys.path.pop(0)
            else:
                while path in sys.path:
                    sys.path.remove(path)
        except Exception:  # pylint: disable=broad-exception-caught
            pass
