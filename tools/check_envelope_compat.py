#!/usr/bin/env python3
"""Check signed-envelope version compatibility fixtures.

Walks the v1 and v1.1 envelope fixtures in ``spec/conformance/`` and asserts
that every case carries the required fields and that its ``version`` is
classified (same-major = compatible) the way the case's ``expect`` says.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

REQUIRED = {
    "wid", "sig", "key_id", "alg", "issued_at", "expires_at", "data_hash", "version"
}


def compatible(version: str) -> bool:
    """Return True if ``version`` is a well-formed 1.x envelope version."""
    major, _, minor = version.partition(".")
    if not major.isdigit():
        return False
    if int(major) != 1:
        return False
    return minor.isdigit()


def check_case(case: dict[str, object]) -> None:
    """Assert one fixture case matches its declared ``expect`` outcome."""
    expect = case["expect"]
    env_obj = case["envelope"]
    assert isinstance(expect, str)
    assert isinstance(env_obj, dict)
    env = cast("dict[str, object]", env_obj)
    missing = REQUIRED - set(env.keys())
    assert not missing, f"missing required fields: {missing}"
    version = str(env["version"])
    is_compat = compatible(version)
    if expect == "compatible":
        assert is_compat, f"expected compatible version, got {version}"
    elif expect == "incompatible_major":
        assert not is_compat, f"expected incompatible version, got {version}"
    else:
        raise AssertionError(f"unknown expect={expect}")


def main() -> None:
    """Run every case from both envelope fixture files."""
    p1 = Path("spec/conformance/signed_envelope_v1.json")
    p2 = Path("spec/conformance/signed_envelope_v1_1.json")
    c1: list[dict[str, object]] = json.loads(p1.read_text(encoding="utf-8"))
    c2: list[dict[str, object]] = json.loads(p2.read_text(encoding="utf-8"))
    assert isinstance(c1, list) and c1
    assert isinstance(c2, list) and c2
    for case in [*c1, *c2]:
        assert isinstance(case, dict)
        check_case(case)
    print("Envelope compatibility check passed")


if __name__ == "__main__":
    main()
