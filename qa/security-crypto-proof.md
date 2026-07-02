# Security/Crypto Proof Ledger

Date: 2026-07-02
Scope: Evidence for the security/crypto claims in this repository, and an
explicit statement of what is **not** covered.

## Two different kinds of check

This repository contains two distinct classes of security check. They are kept
separate here because conflating them overstates coverage:

1. **Cross-language CLI conformance** — checks that drive the six actual CLI
   implementations (`sh`, `python`, `c`, `typescript`, `go`, `rust`) and assert
   they agree. These prove the shipped code behaves correctly.
2. **Specification reference checks** — Python programs under `tools/` that
   implement and exercise the *specification's* reference logic (signed
   envelopes, key rotation, etc.). These prove the spec is self-consistent and
   its negative cases hold. **They do not exercise the six CLIs.**

## 1. Cross-language CLI conformance (drives the real implementations)

| Claim | Proof Command | Observed (2026-07-02) |
|---|---|---|
| `A=sign` / `A=verify` interoperate across all six implementations, and tampered WID/data and wrong keys are rejected | `SMOKE_CRYPTO_STRICT=1 bash tools/smoke_crypto.sh` | `pass=6 fail=0 skip=0` |
| `A=w-otp` (WID-bound HMAC-SHA256 OTP) produces identical codes across all six implementations | `bash tools/check_wotp_parity.sh` | `pass=6 fail=0 skip=0` |

Implemented cryptographic CLI actions are exactly: **`A=sign`, `A=verify`,
`A=w-otp`**. There is intentionally **no** `encrypt`, `decrypt`, or `hash`
action in any implementation (see `spec/CRYPTO_SPEC.md` "Future Considerations").

### Crypto implementation notes (as of CRYPTO_SPEC 1.1.0)

- Signing/verification use each language's native library (Rust
  `ed25519-dalek`; C `libcrypto`/EVP; Go, Python, TS, and — via `openssl(1)` —
  `sh`). No implementation shells out to the `openssl` binary for Rust or C.
- The signed message is the framed canonical message
  `"wid-sig-v1:" || len(WID) || ":" || WID || DATA` (domain-separated,
  length-framed), not a bare `WID||DATA` concatenation.
- OTP verification uses constant-time comparison in every implementation
  (`subtle`, `CRYPTO_memcmp`, `hmac.compare_digest`, `crypto/subtle`,
  `timingSafeEqual`, and HMAC-blinded comparison in `sh`).

## 2. Specification reference checks (Python; do NOT test the CLIs)

The signed-event **envelope** format is defined in `spec/SIGNED_ENVELOPE_SPEC.md`
and is **not implemented by any of the six CLIs** — it currently exists only as
a specification plus the Python reference checks below. Each check implements the
spec's envelope logic in Python (using the `cryptography` library) and asserts
the spec's positive and negative cases:

| Claim (about the spec, not the CLIs) | Proof Command | Expected |
|---|---|---|
| Signed-envelope shape and expiry policy hold | `make signed-envelope-check` | `Signed envelope spec check passed` |
| Tamper matrix holds (tampered id/data, wrong key, expired, malformed ciphertext) | `make security-matrix-check` | `Security matrix check passed` |
| Key rotation overlap/cutover/revocation behavior holds | `make key-rotation-drill-check` | `Key rotation drill check passed` |
| Cross-version envelope compatibility policy holds | `make envelope-compat-check` | `Envelope compatibility check passed` |

Anchors: `spec/SIGNED_ENVELOPE_SPEC.md`, `spec/conformance/security_matrix.json`,
`spec/conformance/signed_envelope_v1*.json`, `tools/check_*.py`.

## What this proves

- The three implemented crypto CLI actions (`sign`, `verify`, `w-otp`) behave
  identically across all six implementations and reject tampering — proven by
  checks that drive the real binaries.
- The signed-envelope specification is internally consistent and its
  security-critical negative cases are executable and enforced (in Python).

## What this does NOT prove

- It is **not** a formal third-party cryptographic audit.
- The signed-envelope / security-matrix / key-rotation / envelope-compat checks
  validate the **specification's Python reference logic only**. They do **not**
  demonstrate that any of the six CLIs implement signed envelopes — none do yet.
- `encrypt` / `decrypt` / `hash` are unimplemented; no claim is made about them.
- It does not prove safety against all side-channel, supply-chain, or
  operational key-management failures. In particular, the `sh` implementation
  passes the OTP/HMAC secret to `openssl(1)` as a process argument (visible via
  `ps`/`/proc` to same-user processes); prefer a non-`sh` implementation when
  secret exposure to local users is a concern.
