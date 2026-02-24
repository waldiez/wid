# WID Quick Usage

WID is a time-ordered, human-readable, collision-resistant identifier format for distributed and Spatial Web systems.

## Spatial Web Focus

Use WID where events move across edge devices, twins, and cloud services:

- Edge sensors and robotics: ordered IDs for ingest and replay.
- Digital twins: stable, sortable timeline keys across producers.
- Semantic/agent routing: self-describing IDs like `20260224T124504.0204Z-rpi_kitchen_event`.
- Multi-producer causality: HLC-WID with node identity (`...Z-node42[-pad]`).

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
wid validate 20260217T143052.0000Z-a3f91c --json
wid parse 20260217T143052.0000Z-a3f91c --json
```

## Service/SQL Essentials

```text
wid W=# A=# L=# D=# I=# E=# Z=# T=sec|ms R=auto|mqtt|ws|redis|null|stdout N=#
```

Key semantics:
- `A=stream N=0` means infinite stream.
- `E=sql` stores generator state in `D/wid_state.sqlite`.
- Persist with `wid` as PK in sinks:

```sql
CREATE TABLE events (
  wid TEXT PRIMARY KEY,
  payload JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

## Self-Describing Pattern

Keep rows lean by embedding stable context in ID scope/suffix when it fits your model:

```text
20260224T124504.0204Z-imaging-this-is-the-title
```

Use database uniqueness + retry on conflict for hard de-duplication guarantees.
