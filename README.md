# WID

<!-- markdownlint-disable MD033 -->
<p align="center">
  <img src="https://waldiez.github.io/media/wid.svg" alt="WID logo" title="WID logo">
</p>

[![CI](https://github.com/waldiez/wid/actions/workflows/ci.yml/badge.svg)](https://github.com/waldiez/wid/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Time-ordered, human-readable, collision-resistant identifiers for distributed systems.

```text
Simple WID         20260217T143052.0000Z-a3f91c
Distributed HLC    20260217T143052.0000Z-node01-a3f91c
Millisecond mode   20260217T143052789.0042Z-e7b3a1
                   ╰─── timestamp ───╯╰seq╯ ╰─pad─╯
```

## Why WID?

| Property                    | UUID v4 | UUID v7 | ULID  | KSUID | **WID** | **HLC-WID** |
| --------------------------: | :---:   | :---:   | :---: | :---: | :-----: | :---------: |
| Time-sortable               | No      | Yes     | Yes   | Yes   | **Yes** | **Yes**     |
| Human-readable timestamp    | No      | No      | No    | No    | **Yes** | **Yes**     |
| Collision-resistant         | Yes     | Yes     | Yes   | Yes   | **Yes** | **Yes**     |
| No coordination needed      | Yes     | Yes     | Yes   | Yes   | **Yes** | **Yes**     |
| Distributed causal ordering | No      | No      | No    | No    | No      | **Yes**     |
| Configurable precision      | No      | No      | No    | No    | **Yes** | **Yes**     |
| Debuggable at a glance      | No      | No      | No    | No    | **Yes** | **Yes**     |

## Quick Start

```bash
git clone https://github.com/waldiez/wid && cd wid
make next           # one WID via sh/wid (I=auto delegates to the Python
                    # implementation when present; I=sh forces pure shell)
make quick-check    # fast gate across all implementations
```

```bash
# Generate
wid next                                  # → 20260217T143052.0000Z-a3f91c
wid next --kind hlc --node sensor42       # → …0000Z-sensor42-a3f91c
wid next --time-unit ms                   # millisecond precision

# Stream
wid stream --count 10                     # 10 WIDs, back-to-back

# Validate / parse
wid validate 20260217T143052.0000Z-a3f91c
wid parse    20260217T143052.0000Z-a3f91c --json
```

All implementations accept the same flag matrix (`--kind`, `--node`, `--W`, `--Z`, `--time-unit`, etc.) defined in [`spec/quick-usage.md`](spec/quick-usage.md).

## Implementations

<!-- markdownlint-disable MD060 -->

| # | Language       | Source                       | Tests        | Crypto | Notes                              |
|:-:|:--------------:|:----------------------------:|:------------:|:------:|:-----------------------------------|
| 1 | **Rust**       | [rust/](rust/)               | `cargo test` | Yes    | Reference implementation · Docker  |
| 2 | **Python**     | [python/](python/)           | `pytest`     | Yes    | Async generators · `aiosqlite` SQL |
| 3 | **C**          | [c/](c/)                     | custom       | Yes    | Single-header `wid.h`              |
| 4 | **TypeScript** | [typescript/](typescript/)   | `vitest`     | Yes    | ESM + CJS · browser-ready          |
| 5 | **Go**         | [go/](go/)                   | `go test`    | Yes    | Thread-safe · stdlib only          |
| 6 | **sh**         | [sh/](sh/)                   | self-test    | Yes    | Canonical Bash orchestrator       |

<!-- markdownlint-enable MD060 -->

All implementations conform to the same [specification](spec/SPEC.md). Cross-language conformance is enforced in CI by executable harnesses that drive every implementation against the shared fixtures in `spec/conformance/`:

- `make id-conformance` — `valid.json` / `invalid.json` (identifier accept/reject) across all six
- `make cli-surface-check` — `cli_surface.json`: the shared flag matrix, defaults table, stream cadence, error surface (clean rejection, no crash), unbounded-stream semantics (`--count 0` / `N=0`), and cross-language output parity (identical w-otp codes from identical inputs, including values containing `=`) across all six
- `make stream-conformance` — streaming behavior
- `tools/check_wotp_parity.sh` and `tools/smoke_crypto.sh` — crypto (`sign`/`verify`/`w-otp`) parity and interop

The conformance promise covers the core surface. The service layer (daemons,
periodic emitters, MQTT/WS/Redis transports) lives **only in the Rust
implementation** — see [spec/SERVICES.md](spec/SERVICES.md).

- Core-CLI-only implementations: `C`, `Go`, `Python`, `TypeScript`, `sh` — they implement `next`, `stream`, `validate`, `parse`, `healthcheck`, `bench`, `selftest` (plus `sign`/`verify`/`w-otp` and `E=sql`), and reject service actions.

## Format

```text
WID       TIMESTAMP . SEQ Z [ - PAD ]
HLC-WID   TIMESTAMP . LC  Z - NODE [ - PAD ]
```
<!-- markdownlint-disable MD060 -->

| Component   | Description                                             | Example            |
|------------:|:--------------------------------------------------------|:-------------------|
| `TIMESTAMP` | UTC, `YYYYMMDDTHHMMSS` or `YYYYMMDDTHHMMSSmmm`          | `20260217T143052`  |
| `SEQ`/`LC`  | Zero-padded sequence or logical counter (width **W**)   | `0000`             |
| `Z`         | Literal `Z` (UTC marker + separator)                   | `Z`                |
| `NODE`      | Alphanumeric + underscore identifier (HLC only)        | `node01`           |
| `PAD`       | Random lowercase hex (length **Z**)                    | `a3f91c`           |

<!-- markdownlint-disable MD036 -->
**Parameters**
<!-- markdownlint-enable MD036 -->

| Param | Default | Range | Description                             |
|:-----:|:-------:|:-----:|:----------------------------------------|
| **W** | 4       | 1–18  | Sequence width — supports 10^W IDs/tick |
| **Z** | 6       | 0–64  | Hex padding length (0 disables)         |
| **T** | `sec`   | —     | Time unit: `sec` or `ms`               |

Out-of-range `W`/`Z` are rejected (never clamped) by every CLI and every
library API — with one documented exception: the C single-header's
`wid_gen_init_ex()` returns `void` and cannot report an error, so it clamps
to the valid range as a last resort. Validate `W`/`Z` before calling it when
embedding the header (the C CLI does, and rejects).
`10^18 - 1` is the largest sequence that fits in a signed 64-bit integer.

Full specification with EBNF grammar: [spec/SPEC.md](spec/SPEC.md)

## Identity vs. Events — the recommended pattern

WIDs name *moments*, not *things*. They embed their creation timestamp in
cleartext on purpose (that is what makes them sortable and debuggable), so
they are the right identifier for occurrences — sensor readings, presence
events, zone transitions, transactions — and the wrong one for long-lived
entities such as people, devices, or places.

Give entities a stable, non-temporal identifier (for example one derived from
the entity's public key), and stamp every occurrence involving them with a
WID:

```sql
CREATE TABLE events (
  wid       TEXT PRIMARY KEY,   -- when/what happened (sortable, HLC-mergeable)
  entity_id TEXT NOT NULL,      -- stable key-derived identity (no timestamp)
  payload   BLOB
);
```

For distributed writers, use HLC-WIDs and derive the `node` tag from something
globally meaningful (e.g. a public-key fingerprint) rather than a chosen name,
and raise `Z` (up to 64 hex chars = 256 random bits; `Z=32` gives UUID-class
collision resistance) when IDs are minted without coordination.

See "Privacy considerations" in [spec/SPEC.md](spec/SPEC.md) before exposing
WIDs to parties who should not learn timing information.

## Install

> No release has been tagged yet, so the packages are not on the public
> registries. Until the first tagged release (which will publish
> `waldiez-wid` to crates.io/PyPI, `@waldiez/wid` to npm, and images to
> ghcr.io), install straight from this repository — all of the following
> work today:

> **Binary name collision:** the Rust, Python, and Go installs each put a
> binary named `wid` on your PATH (npm's is `wid-ts`). If you install more
> than one, whichever comes first in PATH order silently wins — pick one
> implementation for your shell, or invoke the others by full path.

### Rust

```bash
cargo install --git https://github.com/waldiez/wid
```

### Python

```bash
pip install git+https://github.com/waldiez/wid
```

### TypeScript

```bash
npm install github:waldiez/wid   # dist/ is committed, so git installs work
```

### Go

```bash
go install github.com/waldiez/wid/go/cmd/wid@latest
```

### C

```c
// Single header — copy c/include/wid.h into your project
#include "wid.h"
```

### Docker

```bash
docker build -t wid . && docker run --rm wid next
```

## Build

```bash
make setup          # install language tooling
make test           # all language test suites
make check          # lint + type-check + test
make bench-matrix   # cross-language benchmark
make docker         # build Docker image
make clean          # remove build artifacts
```

Per-language helpers: `make rust-test`, `make python-check`, `make ts-build`, `make go-next`, etc.

## Cryptographic Signatures

- **`wid A=sign`** — Ed25519 signature over a WID + optional payload.
- **`wid A=verify`** — Verify signature against a WID and public key.
- **`wid A=w-otp`** — WID-bound OTP (`MODE=gen|verify`): HMAC-SHA256 keyed on the WID.

Full specification: [spec/CRYPTO_SPEC.md](spec/CRYPTO_SPEC.md)

## SQL Persistence

When using `E=sql`, generator state (`last_tick`, `last_seq`) is persisted per key and resumed across restarts.

The state key is language-agnostic (`wid:W:Z:T`), so all six implementations
coordinate through the same row per generator shape: different languages can
safely share one `wid_state.sqlite` without minting duplicate WIDs.

This no-duplicates guarantee applies to the **CLI `E=sql` path**, which
allocates every WID through a compare-and-swap on the state row. The
library-level SQLite stores (Python `SqliteWidStateStore`, TypeScript
`createNodeSqliteWidStateStore`) are plain last-writer-wins persistence for a
single process resuming its own generator — they do not serialize concurrent
writers.

The default database location is `<working directory>/.local/services/wid_state.sqlite`
in every implementation, so processes only share state when they run from the
same directory (or pass the same explicit `D=<dir>`). Set `D=` when writers
start from different places.

State modes:

- `E=state`
- `E=stateless`
- `E=sql`

- `A=stream N=0` means infinite stream (all primary implementations).

```sql
CREATE TABLE IF NOT EXISTS wid_state (
  k TEXT PRIMARY KEY,
  last_tick INTEGER NOT NULL,
  last_seq INTEGER NOT NULL
);
```

WID as a primary key:

```sql
CREATE TABLE events (
  wid TEXT PRIMARY KEY,
  payload JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Time-range scans by WID prefix ride the PRIMARY KEY index for free
-- (lexicographic order = time order); no extra index is needed.
```

## Extensions beyond the spec

The Rust and TypeScript libraries additionally ship a **WID manifest
module** (`Manifest` / `WidFile`): a small binary container format — 4-byte
magic `WIDM`, versioned header, JSON manifest, SHA-256 payload hash — for
stamping payload blobs with a WID and integrity hash. This is deliberately
**not** part of the WID specification and exists only in Rust and
TypeScript; the CLIs do not expose it and the conformance suite does not
cover it. Treat it as a library convenience, not a cross-language guarantee.

## License

[MIT](LICENSE)
