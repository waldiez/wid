# Codebase Map

Quick "wiki-style" navigation for the repo.

## Top-Level Areas

- `spec/`: protocol/specification docs and conformance fixtures.
- `tools/`: QA/parity checks (`check_*` scripts).
- `python/`, `rust/`, `go/`, `typescript/`, `c/`, `sh/`: primary implementations.

## Most Important Files

- `README.md`: primary user-facing overview.
- `spec/SPEC.md`: core identifier format spec.
- `spec/CRYPTO_SPEC.md`: signing/verification contract.

## Useful Navigation Commands

```bash
# list files quickly
rg --files

# find where an action is implemented
rg -n "A=sign|A=verify|A=stream|A=next" sh python rust go typescript c

# find QA gates
rg -n "check_capabilities|check_stream_conformance|smoke_crypto" tools Makefile tools/smoke.sh
```
