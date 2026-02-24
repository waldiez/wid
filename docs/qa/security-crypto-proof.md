# Security/Crypto Proof Ledger

Date: 2026-02-24
Scope: Evidence for security/crypto claims in this repository.

## Claims And Verifiable Evidence

| Claim | Proof Command | Expected/Observed Result |
|---|---|---|
| Cross-language crypto actions conform (`sign`, `verify`, `encrypt`, `decrypt`, `hash`) | `SMOKE_CRYPTO_STRICT=1 bash tools/smoke_crypto.sh` | `pass=15 fail=0 skip=0` (observed on 2026-02-18) |
| Signed-envelope shape and expiry policy are enforced | `make signed-envelope-check` | `Signed envelope spec check passed` |
| Security tamper matrix is enforced | `make security-matrix-check` | `Security matrix check passed` |
| Key rotation overlap/cutover/revocation behavior is validated | `make key-rotation-drill-check` | `Key rotation drill check passed` |
| Cross-version envelope compatibility policy is enforced | `make envelope-compat-check` | `Envelope compatibility check passed` |

## Specification Anchors

- Envelope spec: `spec/SIGNED_ENVELOPE_SPEC.md`
- Envelope compatibility fixtures: `spec/conformance/signed_envelope_v1.json`, `spec/conformance/signed_envelope_v1_1.json`
- Security matrix fixtures: `spec/conformance/security_matrix.json`
- Crypto spec: `spec/CRYPTO_SPEC.md`
- Key rotation: `tools/check_key_rotation_drill.py`

## Threat Cases Covered By Executable Checks

- Tampered ID (`tampered_wid`) -> verification fails.
- Tampered data hash (`tampered_data`) -> verification fails.
- Wrong verification key (`wrong_key`) -> verification fails.
- Expired envelope (`expired_envelope`) -> rejected.
- Malformed ciphertext (`malformed_ciphertext`) -> decryption fails.

All of the above are asserted by `tools/check_security_matrix.py` against `spec/conformance/security_matrix.json`.

## Reproducible Full Gate

```bash
make hardening-check
```

This currently includes crypto/security/conformance gates plus stream/service/path/package/SQL checks.

## What This Proves

- Implementation behavior matches the repository's crypto/security claims under the tested conditions.
- Security-critical negative tests are not only documented, but executable and enforced.

## What This Does Not Prove

- It is not a formal third-party cryptographic audit.
- It does not prove safety against all side-channel, supply-chain, or operational key-management failures.
