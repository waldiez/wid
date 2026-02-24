#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def parse_rfc3339_utc(value: str) -> datetime | None:
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(UTC)


def is_hex64(s: str) -> bool:
    return len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def validate_shape(env: dict[str, object]) -> tuple[bool, str]:
    required = ["version", "wid", "sig", "key_id", "alg", "issued_at", "expires_at", "data_hash"]
    for k in required:
        if k not in env:
            return False, f"missing field: {k}"
        if not isinstance(env[k], str) or not str(env[k]).strip():
            return False, f"invalid field: {k}"
    if env["alg"] != "Ed25519":
        return False, "alg must be Ed25519"
    version = str(env["version"])
    if not version.startswith("1."):
        return False, "version must be 1.x"
    iat = parse_rfc3339_utc(str(env["issued_at"]))
    exp = parse_rfc3339_utc(str(env["expires_at"]))
    if iat is None or exp is None:
        return False, "issued_at/expires_at must be RFC3339 UTC"
    if exp < iat:
        return False, "expires_at before issued_at"
    dh = str(env["data_hash"])
    if not dh.startswith("sha256:"):
        return False, "data_hash must start with sha256:"
    if not is_hex64(dh.split(":", 1)[1]):
        return False, "data_hash must be sha256:<64 lowercase hex>"
    return True, "ok"


def main() -> None:
    path = Path("spec/conformance/signed_envelope.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data, "signed_envelope.json must be a non-empty array"

    now = datetime.now(UTC)
    for case in data:
        assert isinstance(case, dict), "case must be object"
        expect = case.get("expect")
        env = case.get("envelope")
        assert isinstance(expect, str), "case expect must be string"
        assert isinstance(env, dict), "case envelope must be object"

        ok, msg = validate_shape(env)
        assert ok, f"{case.get('name')}: invalid shape: {msg}"

        exp = parse_rfc3339_utc(str(env["expires_at"]))
        assert exp is not None
        if expect == "invalid_expired":
            assert exp < now, f"{case.get('name')}: expected expired envelope"
        elif expect == "valid":
            assert exp > now, f"{case.get('name')}: expected non-expired envelope"
        else:
            raise AssertionError(f"{case.get('name')}: unknown expect={expect}")

    print("Signed envelope spec check passed")


if __name__ == "__main__":
    main()
