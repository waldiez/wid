"""Cryptographic CLI actions: Ed25519 sign/verify and WID-bound w-otp.

The ``cryptography`` imports stay inside the sign/verify handlers on purpose:
the core CLI works without the optional extra, and a missing dependency stays
an operational failure (exit 1) rather than a usage error (exit 2).
"""

# pyright: reportUnusedCallResult=false,reportAny=false

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ..core import parse_time_unit
from ..wid import WidGen


def _require_canon(canon: dict[str, str], key: str, message: str) -> str:
    """Return a required canonical parameter or raise the usage error.

    Missing required parameters are usage errors (ValueError -> exit 2);
    indexing ``canon[...]`` directly raised an uncaught KeyError traceback.
    """
    value = canon.get(key, "")
    if not value:
        raise ValueError(message)
    return value


def run_sign_mode(canon: dict[str, str]) -> None:
    """Handle ``A=sign``: Ed25519-sign a WID (plus optional payload)."""
    # Validate required params (usage errors, exit 2) BEFORE importing
    # cryptography: a missing optional dependency is an operational failure
    # (ImportError -> exit 1), and must not mask a missing KEY= usage error.
    wid_str = _require_canon(canon, "WID", "WID=<wid_string> required for A=sign")
    raw_key = _require_canon(canon, "KEY", "KEY=<private_key_path> required for A=sign")

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key_path = Path(raw_key).expanduser().resolve()
    data_path_str = canon.get("DATA")
    out_path_str = canon.get("OUT")

    if not key_path.exists():
        raise FileNotFoundError(f"private key file not found: {key_path}")

    try:
        with open(key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
    except ValueError as exc:
        # Bad key material is an operational failure (exit 1), not a usage
        # error: cryptography raises ValueError, which would exit 2.
        raise RuntimeError("sign failed (ensure Ed25519 private key PEM)") from exc

    if not isinstance(private_key, ed25519.Ed25519PrivateKey):
        raise TypeError("Loaded key is not an Ed25519 private key.")

    # Canonical message: "wid-sig-v1:" + len(WID) + ":" + WID + DATA. The domain
    # prefix and explicit WID byte-length frame the WID/DATA boundary.
    wid_bytes = wid_str.encode("utf-8")
    message = f"wid-sig-v1:{len(wid_bytes)}:".encode("ascii") + wid_bytes
    if data_path_str:
        data_path = Path(data_path_str).expanduser().resolve()
        if not data_path.exists():
            raise FileNotFoundError(f"data file not found: {data_path}")
        with open(data_path, "rb") as f:
            message += f.read()

    signature = private_key.sign(message)
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")

    if out_path_str:
        out_path = Path(out_path_str).expanduser().resolve()
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(encoded_signature)
    else:
        print(encoded_signature, flush=True)


def run_verify_mode(canon: dict[str, str]) -> None:
    """Handle ``A=verify``: check an Ed25519 signature for a WID."""
    # Validate required params (usage errors, exit 2) BEFORE importing
    # cryptography, so a missing optional dependency (ImportError -> exit 1)
    # never masks a missing KEY=/SIG=/WID= usage error.
    wid_str = _require_canon(canon, "WID", "WID=<wid_string> required for A=verify")
    raw_key = _require_canon(
        canon, "KEY", "KEY=<public_key_path> required for A=verify"
    )
    sig_str = _require_canon(
        canon, "SIG", "SIG=<signature_string> required for A=verify"
    )

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key_path = Path(raw_key).expanduser().resolve()
    data_path_str = canon.get("DATA")

    if not key_path.exists():
        raise FileNotFoundError(f"public key file not found: {key_path}")

    try:
        with open(key_path, "rb") as f:
            public_key = serialization.load_pem_public_key(f.read())
    except ValueError as exc:
        # Bad key material is an operational failure (exit 1), not a usage
        # error: cryptography raises ValueError, which would exit 2.
        raise RuntimeError(
            "invalid public key (ensure Ed25519 public key PEM)"
        ) from exc

    if not isinstance(public_key, ed25519.Ed25519PublicKey):
        raise TypeError("Loaded key is not an Ed25519 public key.")

    # Canonical message: "wid-sig-v1:" + len(WID) + ":" + WID + DATA. The domain
    # prefix and explicit WID byte-length frame the WID/DATA boundary.
    wid_bytes = wid_str.encode("utf-8")
    message = f"wid-sig-v1:{len(wid_bytes)}:".encode("ascii") + wid_bytes
    if data_path_str:
        data_path = Path(data_path_str).expanduser().resolve()
        if not data_path.exists():
            raise FileNotFoundError(f"data file not found: {data_path}")
        with open(data_path, "rb") as f:
            message += f.read()

    try:
        # Add padding back; base64 raises binascii.Error (a ValueError
        # subclass) on garbage, which would exit 2 as a usage error — but a
        # malformed signature is a verification failure (exit 1) everywhere.
        decoded_signature = base64.urlsafe_b64decode(sig_str + "===")
    except ValueError as exc:
        raise RuntimeError("invalid signature encoding") from exc

    try:
        public_key.verify(decoded_signature, message)
        print("Signature valid.", flush=True)
        sys.exit(0)
    except InvalidSignature:
        print("Signature invalid.", file=sys.stderr, flush=True)
        sys.exit(1)
    except Exception as e:
        print(f"Verification error: {e}", file=sys.stderr, flush=True)
        sys.exit(1)


def _resolve_wotp_secret(raw_key: str) -> str:
    """Treat KEY= as a file path if one exists, else as the literal secret."""
    key_path = Path(raw_key).expanduser().resolve()
    if key_path.exists() and key_path.is_file():
        return key_path.read_text(encoding="utf-8").strip()
    return raw_key.strip()


def _wotp_code(secret: str, wid: str, digits: int) -> str:
    """Derive the truncated HMAC-SHA256 OTP for ``wid`` (CRYPTO_SPEC)."""
    key = secret.encode("utf-8")
    digest = hmac.new(key, wid.encode("utf-8"), hashlib.sha256).digest()
    binary = int.from_bytes(digest[:4], "big", signed=False)
    return str(binary % (10**digits)).zfill(digits)


def _wotp_wid_tick_ms(wid_str: str) -> int:
    """Extract the WID's timestamp in epoch milliseconds for age checks.

    Raises ``RuntimeError`` (not ``ValueError``) on a malformed timestamp:
    verification *outcomes* exit 1 in every implementation, while this CLI
    reserves exit 2 for usage errors (``ValueError``).
    """
    invalid = "WID timestamp is invalid for time-window verification"
    ts = wid_str.split(".", 1)[0]
    if "T" not in ts:
        raise RuntimeError(invalid)
    date_part, time_part = ts.split("T", 1)
    if len(date_part) != 8 or len(time_part) not in {6, 9}:
        raise RuntimeError(invalid)
    fmt = "%Y%m%dT%H%M%S%f" if len(time_part) == 9 else "%Y%m%dT%H%M%S"
    try:
        dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise RuntimeError(invalid) from exc
    return int(dt.timestamp() * 1000)


# One branch per MODE/parameter rule; mirrors the other implementations.
def run_wotp_mode(  # noqa: C901
    canon: dict[str, str], w_val: int, z_val: int, time_unit: str
) -> None:
    """Handle ``A=w-otp MODE=gen|verify``: WID-bound one-time codes."""
    mode = canon.get("MODE", "gen").strip().lower()
    if mode not in {"gen", "verify"}:
        raise ValueError("MODE must be gen or verify for A=w-otp")
    if "KEY" not in canon:
        raise ValueError("KEY=<secret_or_path> required for A=w-otp")
    secret = _resolve_wotp_secret(canon["KEY"])
    if not secret:
        raise ValueError("w-otp secret cannot be empty")

    digits_raw = canon.get("DIGITS", "6")
    if not digits_raw.isdigit():
        raise ValueError("DIGITS must be an integer")
    digits = int(digits_raw)
    if digits < 4 or digits > 10:
        raise ValueError("DIGITS must be between 4 and 10")
    max_age_raw = canon.get("MAX_AGE_SEC", "0")
    max_future_raw = canon.get("MAX_FUTURE_SEC", "5")
    if not max_age_raw.isdigit():
        raise ValueError("MAX_AGE_SEC must be a non-negative integer")
    if not max_future_raw.isdigit():
        raise ValueError("MAX_FUTURE_SEC must be a non-negative integer")
    max_age_sec = int(max_age_raw)
    max_future_sec = int(max_future_raw)

    wid_str = canon.get("WID", "").strip()
    if not wid_str and mode == "gen":
        unit = parse_time_unit(time_unit)
        gen = WidGen(w=w_val, z=z_val, time_unit=unit)
        wid_str = gen.next()
    if not wid_str:
        raise ValueError("WID=<wid_string> required for A=w-otp MODE=verify")

    otp = _wotp_code(secret, wid_str, digits)
    if mode == "gen":
        record = {"wid": wid_str, "otp": otp, "digits": digits}
        print(json.dumps(record, separators=(",", ":")))
        return

    code = canon.get("CODE", "").strip()
    if not code:
        raise ValueError("CODE=<otp_code> required for A=w-otp MODE=verify")
    # Freshness failures are verification *outcomes*, not usage errors:
    # RuntimeError exits 1, matching the other five implementations
    # (ValueError would exit 2 here).
    if max_age_sec > 0 or max_future_sec > 0:
        wid_ms = _wotp_wid_tick_ms(wid_str)
        now_ms = int(time.time() * 1000)
        delta_ms = now_ms - wid_ms
        if delta_ms < 0 and -delta_ms > max_future_sec * 1000:
            raise RuntimeError("OTP invalid: WID timestamp is too far in the future")
        if delta_ms >= 0 and max_age_sec > 0 and delta_ms > max_age_sec * 1000:
            raise RuntimeError("OTP invalid: WID timestamp is too old")
    if hmac.compare_digest(otp, code):
        print("OTP valid.", flush=True)
        return
    print("OTP invalid.", file=sys.stderr, flush=True)
    sys.exit(1)
