#!/usr/bin/env python3
"""Key-rotation drill: overlap, cutover, and revocation must behave.

Simulates the documented rotation procedure with two Ed25519 key
generations: during overlap both keys verify, after cutover only the new
key does, and an explicitly revoked key id always fails regardless of
trust-store contents.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519


def b64url(raw: bytes) -> str:
    """Encode bytes as unpadded URL-safe base64."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64url_decode(s: str) -> bytes:
    """Decode unpadded URL-safe base64 back to bytes."""
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sha256_hex(data: bytes) -> str:
    """Return the hex SHA-256 digest of ``data``."""
    h = hashes.Hash(hashes.SHA256())
    h.update(data)
    return h.finalize().hex()


@dataclass
class Envelope:
    """Signed-envelope fields as defined in spec/CRYPTO_SPEC.md."""

    wid: str
    key_id: str
    alg: str
    issued_at: str
    expires_at: str
    data_hash: str
    sig: str


def canonical_payload(env: Envelope) -> bytes:
    """Serialize the envelope fields into the canonical signing message."""
    parts = [env.wid, env.key_id, env.alg, env.issued_at, env.expires_at, env.data_hash]
    return "\n".join(parts).encode("utf-8")


def sign(wid: str, key_id: str, sk: ed25519.Ed25519PrivateKey) -> Envelope:
    """Build and sign a five-minute envelope for ``wid`` under ``key_id``."""
    now = datetime.now(UTC)
    iat = now.isoformat().replace("+00:00", "Z")
    exp = (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    env = Envelope(
        wid=wid,
        key_id=key_id,
        alg="Ed25519",
        issued_at=iat,
        expires_at=exp,
        data_hash=f"sha256:{sha256_hex(wid.encode('utf-8'))}",
        sig="",
    )
    env.sig = b64url(sk.sign(canonical_payload(env)))
    return env


def verify(
    env: Envelope, trusted: dict[str, ed25519.Ed25519PublicKey], revoked: set[str]
) -> bool:
    """Verify against a trust store; revocation beats trust, expiry beats both."""
    if env.key_id in revoked:
        return False
    pk = trusted.get(env.key_id)
    if pk is None or env.alg != "Ed25519":
        return False
    expires = datetime.fromisoformat(env.expires_at.replace("Z", "+00:00"))
    if expires.astimezone(UTC) < datetime.now(UTC):
        return False
    try:
        pk.verify(b64url_decode(env.sig), canonical_payload(env))
        return True
    except Exception:  # pylint: disable=broad-exception-caught
        return False


def main() -> None:
    """Run the three rotation phases and assert each verification outcome."""
    # Phase 0: two key generations for drill.
    old_sk = ed25519.Ed25519PrivateKey.generate()
    new_sk = ed25519.Ed25519PrivateKey.generate()
    old_pk = old_sk.public_key()
    new_pk = new_sk.public_key()

    old_env = sign("20260218T170000.0000Z-node_event", "edge-ed25519-v1", old_sk)
    new_env = sign("20260218T170001.0000Z-node_event", "edge-ed25519-v2", new_sk)

    # Phase 1 (rotation overlap): both keys trusted.
    trust_overlap = {
        "edge-ed25519-v1": old_pk,
        "edge-ed25519-v2": new_pk,
    }
    assert verify(old_env, trust_overlap, revoked=set())
    assert verify(new_env, trust_overlap, revoked=set())

    # Phase 2 (rotation complete): only new key trusted.
    trust_new_only = {"edge-ed25519-v2": new_pk}
    assert not verify(old_env, trust_new_only, revoked=set())
    assert verify(new_env, trust_new_only, revoked=set())

    # Incident drill: explicit revocation wins.
    revoked = {"edge-ed25519-v2"}
    assert not verify(new_env, trust_new_only, revoked=revoked)

    print("Key rotation drill check passed")


if __name__ == "__main__":
    main()
