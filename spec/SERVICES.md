# WID Services — Rust-only Layer

Version: 1.0.0
Status: Informational — describes the Rust implementation's extra surface

## Scope

Beyond the core identifier surface that all six implementations share
(`next`, `stream`, `validate`, `parse`, `healthcheck`, `bench`, `selftest`,
plus the crypto actions `sign`, `verify`, `w-otp` and `E=sql` persistence),
the **Rust implementation only** ships a service layer:

| Group | Actions |
| :---- | :------ |
| Lifecycle | `A=start`, `A=stop`, `A=status`, `A=logs`, `A=run` |
| Introspection | `A=discover`, `A=scaffold` |
| Local services | `A=saf`, `A=saf-wid`, `A=wir`, `A=wism`, `A=wihp`, `A=wipr`, `A=duplex` |
| Transports | `R=mqtt`, `R=ws`, `R=redis` (in addition to the core `auto`/`null`/`stdout`) |

The other five implementations reject these actions (`error: unknown A=...`)
and reject non-core transports with an error that points here. This is
deliberate: the layer used to be duplicated — unspecified and untested — in
all six languages, and the duplication produced real cross-language
divergences. One reference implementation is maintainable; six copies were
not.

## Semantics (current, reference-level)

- **Lifecycle** — `start` daemonizes a WID-emitting service loop (PID/log
  files under the runtime directory), `stop`/`status`/`logs` manage it.
- **Local services** — `saf`/`saf-wid`/`wir`/`wism`/`wihp`/`wipr`/`duplex`
  are periodic JSON emitters (tick, WID, transport metadata) intended as
  building blocks for SYNAPSE-side supervisors.
- **Transports** — best-effort adapters; when a broker/endpoint is not
  reachable the payload falls back to stdout.

These semantics are descriptive of the Rust implementation, not (yet) a
conformance target — there is deliberately no cross-language conformance
suite for this layer, and no other implementation should grow one ad hoc.
If the layer ever needs a second implementation, this document must first be
promoted to a real specification with fixtures.

## Explicitly removed

A `self.check-update` action (an unauthenticated GitHub API phone-home) used
to exist in the C, Python, and sh implementations. It was removed entirely:
package managers own updates, and a CLI that silently calls out to the
network on an ID-generation tool is a liability, not a feature.
