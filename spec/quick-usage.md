# WID Quick Usage

WID is a time-ordered, human-readable, collision-resistant identifier format for distributed and Spatial Web systems.

## Spatial Web Focus

Use WID where events move across edge devices, twins, and cloud services:

- Edge sensors and robotics: ordered IDs for ingest and replay.
- Digital twins: stable, sortable timeline keys across producers.
- Multi-producer causality and producer routing: HLC-WID with node identity
  (`...Z-node42[-pad]`, e.g. `20260224T124504.0204Z-rpi_kitchen_event` —
  note this is the HLC form; validate it with `--kind hlc`).

```text
WID       TIMESTAMP . SEQ Z [ - PAD ]
HLC-WID   TIMESTAMP . LC  Z - NODE [ - PAD ]
```

Examples:

```text
20260217T143052.0000Z-a3f91c
20260217T143052.0000Z-node01-a3f91c
20260217T143052789.0042Z-e7b3a1
```

## Core Commands

```bash
# One ID
wid next

# Stream IDs
wid stream --count 10

# HLC-WID
wid next --kind hlc --node sensor42

# Millisecond precision
wid next --time-unit ms

# Validate / parse
wid validate 20260217T143052.0000Z-a3f91c
wid parse 20260217T143052.0000Z-a3f91c --json
```

## Service/SQL Essentials

```text
wid W=# A=# L=# D=# I=# E=# Z=# T=sec|ms R=auto|mqtt|ws|redis|null|stdout N=#
```

Key semantics:
- `A=stream N=0` means infinite stream.
- `E=sql` stores generator state in `D/wid_state.sqlite`.
- `R=` (service actions) exists only in the Rust implementation, and the
  transport name is advisory metadata in the emitted JSON — all output goes
  to stdout regardless. See [SERVICES.md](SERVICES.md).
- Persist with `wid` as PK in sinks:

```sql
CREATE TABLE events (
  wid TEXT PRIMARY KEY,
  payload JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

## Context Belongs in Columns, Not in the ID

WIDs deliberately carry no semantic "scope": a plain WID's suffix is random
hex padding only, and every implementation rejects arbitrary text there. If
you need to identify the producer, use the HLC form's node field
(`...Z-rpi_kitchen_event`), whose charset is `[A-Za-z0-9_]`. Titles,
categories, and other context go in ordinary columns next to the `wid`
primary key — see the README's "Identity vs. Events" section for why
long-lived semantic IDs are an anti-pattern.

Use database uniqueness + retry on conflict for hard de-duplication guarantees.
