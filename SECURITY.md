# Security Policy

## Supported Versions

Security fixes are applied to the tip of `main` (no release has been tagged
yet; once `1.x` releases exist, fixes will target the latest released `1.x`
line). Older pre-1.0
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

- **Secrets on the command line.** *Every* implementation accepts the
  `w-otp` secret inline as `KEY=<secret>`, which makes it visible via
  `ps`/`/proc` to other processes of the same user — switching languages does
  not avoid this. To keep the secret out of process arguments, pass a file
  path instead (`KEY=<path>`): all implementations read the key material from
  the file. The `sh` implementation additionally re-exposes an inline secret
  to `openssl(1)` as a process argument. See the "Security considerations"
  section of `spec/CRYPTO_SPEC.md`.
- **`KEY` path/secret ambiguity.** `KEY=<value>` is treated as a file path if
  a file with that exact name exists, and as the literal secret otherwise —
  uniformly in all implementations. An inline secret that happens to match an
  existing filename will silently be replaced by that file's contents. Prefer
  the explicit file form for anything beyond ad-hoc use.
- **WIDs embed timestamps in cleartext.** This is by design (sortability),
  but it means any party that sees a WID learns when it was minted, a
  WID-keyed SQL table reveals row creation times to anyone who can read it,
  and HLC-WIDs additionally name the minting node. Do not use raw WIDs as
  identifiers for people or other privacy-sensitive entities; see "Privacy
  Considerations" in `spec/SPEC.md`.
- **`w-otp` is a truncated MAC, not a rotating OTP.** Verifiers must apply
  rate-limiting/lockout and (if needed) single-use tracking; see
  `spec/CRYPTO_SPEC.md`.
