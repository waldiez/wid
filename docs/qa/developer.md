# Developer QA Playbook

Date: 2026-02-24

## 0) Open Repo Root

Open a terminal in the repo root. Before running the fast readiness gates, execute `make doctor` (toolchain check) and `make quick-check` (Python/TS/Go tests + `sh/wid next`) to catch common issues early.

## Toolchain expectations

| Tool | Baseline |
| --- | --- |
| `cargo` / `rustc` | stable (see `Cargo.toml`). |
| `python3` | `>= 3.10` (see `pyproject.toml`: `requires-python`). |
| `go` | `1.22` (see `go.mod`). |
| `node`/`npm` | Use the version that produced the committed `package-lock.json` (run `node --version`/`npm --version` to stay consistent). |
| `cc` | C11-capable compiler (gcc or clang). |
| `bash` | `>= 4.0` (required by `sh/wid` and most QA scripts). |

## 1) Fast Readiness Gates

```bash
python3 tools/check_capabilities.py
python3 tools/check_stream_conformance.py
bash tools/smoke_crypto.sh
sh tools/smoke.sh
```

Pass criteria:
- all commands exit `0`
- crypto summary is `pass=15 fail=0 skip=0`

## 2) Strict Crypto Gate

```bash
SMOKE_CRYPTO_STRICT=1 bash tools/smoke_crypto.sh
```

Pass criteria:
- exit `0`
- summary shows `fail=0 skip=0`

## 3) Full Build/Test Sweep

```bash
make release-check
npm run lint && npm run typecheck && npm run test
pytest -q python/tests
go test ./...
cargo test -q
make -C c test
```

## 4) Spot-Checks

### Canonical stream semantics

```bash
node typescript/dist/cli.js A=stream N=3 L=0 W=4 Z=0 T=sec | wc -l
```

Expected: `3`

### SQL persistence

```bash
node typescript/dist/cli.js A=next E=sql D=.local/sql-qa W=4 Z=0 T=sec
node typescript/dist/cli.js A=next E=sql D=.local/sql-qa W=4 Z=0 T=sec
```

Expected: second ID is later than first.

## 5) Path Hygiene Check (Before Commit)

Ensure no machine-specific absolute paths leaked into public files:

```bash
rg -n -e "/Users/[A-Za-z0-9._-]+" -e "/home/[A-Za-z0-9._-]+" README.md docs spec tools Makefile
```

Pass criteria:
- no output

## 6) Go/No-Go

Release-ready when all sections above are green.

## Maintenance reminder

- Re-run `make doctor` and `make quick-check` in your local branch after major dependency upgrades or before merging to ensure the fast gate stays reliable.
- Include the same commands in automation (CI workflow or scheduled task) so the quick-feedback loop stays exercised.
