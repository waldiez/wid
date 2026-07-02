# Security Policy

## Supported Versions

Security fixes are applied to the latest released `1.x` line. Older pre-1.0
snapshots are not maintained.

| Version | Supported |
| ------- | --------- |
| 1.x     | ✅        |
| < 1.0   | ❌        |

## Reporting a Vulnerability

Please report security issues **privately** — do not open a public issue or PR
for an unfixed vulnerability.

- Email `development @ waldiez.io`, or
- Use GitHub's private ["Report a vulnerability"](https://github.com/waldiez/wid/security/advisories/new) advisory flow.

Please include, where possible: affected implementation(s) and version, a
description of the issue and its impact, and minimal steps or a proof of
concept to reproduce.

### What to expect

- **Acknowledgement:** within 3 business days.
- **Initial assessment:** within 7 business days.
- We will coordinate a fix and a disclosure timeline with you, and credit you in
  the release notes unless you prefer to remain anonymous. Please allow us a
  reasonable window to ship a fix before any public disclosure.

## Known limitations (not tracked as vulnerabilities)

- **`sh` implementation and secrets.** The `sh` implementation passes the
  `w-otp` HMAC secret to `openssl(1)` as a process argument, so it can be
  visible via `ps`/`/proc` to other processes of the same user. Prefer a
  non-`sh` implementation when local secret exposure matters. See the
  "Security considerations" section of `spec/CRYPTO_SPEC.md`.
- **`w-otp` is a truncated MAC, not a rotating OTP.** Verifiers must apply
  rate-limiting/lockout and (if needed) single-use tracking; see
  `spec/CRYPTO_SPEC.md`.
