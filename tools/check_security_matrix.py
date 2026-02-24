#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import hashes, hmac, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass
class Envelope:
    wid: str
    sig: str
    key_id: str
    alg: str
    issued_at: str
    expires_at: str
    data_hash: str


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64url_decode(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sha256_hex(data: bytes) -> str:
    digest = hashes.Hash(hashes.SHA256())
    digest.update(data)
    return digest.finalize().hex()


def canonical_payload(env: Envelope) -> bytes:
    return (
        f"{env.wid}\n{env.key_id}\n{env.alg}\n{env.issued_at}\n{env.expires_at}\n{env.data_hash}".encode("utf-8")
    )


def parse_utc(v: str) -> datetime:
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    return datetime.fromisoformat(v).astimezone(UTC)


def verify_envelope(env: Envelope, pub: ed25519.Ed25519PublicKey) -> bool:
    if env.alg != "Ed25519":
        return False
    if parse_utc(env.expires_at) < datetime.now(UTC):
        return False
    try:
        pub.verify(b64url_decode(env.sig), canonical_payload(env))
        return True
    except Exception:
        return False


def main() -> None:
    matrix = json.loads(Path("spec/conformance/security_matrix.json").read_text(encoding="utf-8"))
    ids = {x["id"] for x in matrix if x.get("required")}

    wid = "20260218T170000.0000Z-edge01-event"
    payload = b"important event payload"
    data_hash = f"sha256:{sha256_hex(payload)}"

    priv_a = ed25519.Ed25519PrivateKey.generate()
    pub_a = priv_a.public_key()
    priv_b = ed25519.Ed25519PrivateKey.generate()
    pub_b = priv_b.public_key()

    now = datetime.now(UTC)
    issued = now.isoformat().replace("+00:00", "Z")
    future = (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    past = (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")

    env = Envelope(
        wid=wid,
        sig="",
        key_id="edge01-ed25519-v1",
        alg="Ed25519",
        issued_at=issued,
        expires_at=future,
        data_hash=data_hash,
    )
    env.sig = b64url(priv_a.sign(canonical_payload(env)))

    # tampered_wid
    tampered = Envelope(**{**env.__dict__, "wid": wid.replace("0000", "0001")})
    assert not verify_envelope(tampered, pub_a), "tampered_wid should fail"

    # tampered_data
    tampered_data = Envelope(**{**env.__dict__, "data_hash": f"sha256:{'0'*64}"})
    assert not verify_envelope(tampered_data, pub_a), "tampered_data should fail"

    # wrong_key
    assert not verify_envelope(env, pub_b), "wrong_key should fail"

    # expired_envelope
    expired = Envelope(**{**env.__dict__, "expires_at": past})
    expired.sig = b64url(priv_a.sign(canonical_payload(expired)))
    assert not verify_envelope(expired, pub_a), "expired_envelope should fail"

    # malformed_ciphertext
    key = AESGCM.generate_key(bit_length=256)
    aes = AESGCM(key)
    nonce = b"0123456789ab"
    ct = aes.encrypt(nonce, payload, None)
    malformed = ct[:-8]
    failed = False
    try:
        _ = aes.decrypt(nonce, malformed, None)
    except Exception:
        failed = True
    assert failed, "malformed_ciphertext should fail"

    # Ensure required ids covered
    covered = {"tampered_wid", "tampered_data", "wrong_key", "expired_envelope", "malformed_ciphertext"}
    missing = ids - covered
    assert not missing, f"missing required security cases: {sorted(missing)}"

    print("Security matrix check passed")


if __name__ == "__main__":
    main()
