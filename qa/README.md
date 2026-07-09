# QA Guide

Use this section to verify WID before release/tag. Start by reading `CONTRIBUTING.md` for the recommended workflow, then follow `docs/qa/developer.md` for the QA story. Run `make doctor` and `make quick-check` before the heavier suites so the toolchain and sanity gates are green.

## Quick Links

- [Developer QA](developer.md)
- [Codebase Map](codebase-map.md)
- [Security/Crypto Proof](security-crypto-proof.md)

## Recommended Order

1. Run [Developer QA](developer.md) for full release validation.
2. Use [Codebase Map](codebase-map.md) when you need to inspect or debug.

## Release checklist addendum

The proof documents in this directory are **dated snapshots** of observed
runs, not living documents. Before tagging a release, re-run the cited
checks (`make hardening-check` covers them) and refresh the observed
outputs and `Date:` lines in [Security/Crypto Proof](security-crypto-proof.md)
— a proof ledger older than the code it vouches for is a false assurance.
Also confirm `CHANGELOG.md` and the manifest versions (Cargo/npm/pyproject)
agree with the tag; the `publish` workflow enforces the version match.
