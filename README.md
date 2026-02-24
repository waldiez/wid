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
make next           # generate one WID via the canonical sh CLI
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
| 6 | **sh**         | [sh/](sh/)                   | self-test    | Yes    | Canonical POSIX orchestrator       |

<!-- markdownlint-enable MD060 -->

All implementations conform to the same [specification](spec/SPEC.md) and pass the shared conformance fixtures in `spec/conformance/`.

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

| Param | Default | Description                             |
|:-----:|:-------:|:----------------------------------------|
| **W** | 4       | Sequence width — supports 10^W IDs/tick |
| **Z** | 6       | Hex padding length (0 disables)         |
| **T** | `sec`   | Time unit: `sec` or `ms`               |

Full specification with EBNF grammar: [spec/SPEC.md](spec/SPEC.md)

## Install

### Rust

```bash
cargo install waldiez-wid
```

### Python

```bash
pip install waldiez-wid
```

### TypeScript

```bash
npm install @waldiez/wid
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
docker pull ghcr.io/waldiez/wid
docker run --rm ghcr.io/waldiez/wid next
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

-- Time-range scans by WID prefix are zero-cost (lexicographic order = time order)
CREATE INDEX IF NOT EXISTS ix_events_wid_prefix ON events(wid);
```

## License

[MIT](LICENSE)
