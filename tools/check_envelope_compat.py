#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


REQUIRED = {"wid", "sig", "key_id", "alg", "issued_at", "expires_at", "data_hash", "version"}


def compatible(version: str) -> bool:
    major, _, minor = version.partition(".")
    if not major.isdigit():
        return False
    if int(major) != 1:
        return False
    return minor.isdigit()


def check_case(case: dict[str, object]) -> None:
    expect = case["expect"]
    env = case["envelope"]
    assert isinstance(expect, str)
    assert isinstance(env, dict)
    assert REQUIRED.issubset(env.keys()), f"missing required fields: {REQUIRED - set(env.keys())}"
    version = str(env["version"])
    is_compat = compatible(version)
    if expect == "compatible":
        assert is_compat, f"expected compatible version, got {version}"
    elif expect == "incompatible_major":
        assert not is_compat, f"expected incompatible version, got {version}"
    else:
        raise AssertionError(f"unknown expect={expect}")


def main() -> None:
    p1 = Path("spec/conformance/signed_envelope_v1.json")
    p2 = Path("spec/conformance/signed_envelope_v1_1.json")
    c1 = json.loads(p1.read_text(encoding="utf-8"))
    c2 = json.loads(p2.read_text(encoding="utf-8"))
    assert isinstance(c1, list) and c1
    assert isinstance(c2, list) and c2
    for case in [*c1, *c2]:
        assert isinstance(case, dict)
        check_case(case)
    print("Envelope compatibility check passed")


if __name__ == "__main__":
    main()
