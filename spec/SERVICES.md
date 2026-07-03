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
| Transport labels | `R=mqtt`, `R=ws`, `R=redis` (in addition to the core `auto`/`null`/`stdout`) |

The other five implementations reject these actions (`error: unknown A=...`)
and reject non-core transports with an error that points here. This is
deliberate: the layer used to be duplicated — unspecified and untested — in
all six languages, and the duplication produced real cross-language
divergences. One reference implementation is maintainable; six copies were
not.

## Transports are metadata, not connections

**There is no broker client code in this repository.** `R=` selects a
*label* that is recorded verbatim in each emitted JSON payload
(`"transport": "mqtt"`); the payload itself is always written to stdout.
`R=mqtt`, `R=ws`, `R=redis`, and `R=stdout` produce byte-identical behavior
apart from that label. The only value with a behavioral effect is `R=null`,
which suppresses output entirely. `R=auto` is rewritten to the label `mqtt`
for `saf-wid`/`wir`/`wism`/`wihp`/`wipr`/`duplex`; for `saf` and `run` it is
passed through as the literal label `auto`.

The intended pattern is that a downstream supervisor consumes the stdout
stream and does its own publishing; the label tells it where the payload is
meant to go. If the CLI ever grows a real in-process transport, this section
must be rewritten first.

## Local services — what each action emits

The service actions are periodic JSON emitters: one payload per tick, `L=`
seconds between ticks, `N=` ticks total (`N=0` = run forever). The action
names are historical codenames inherited from the project this layer was
extracted from; treat the `action` string as an opaque channel label that
downstream supervisors route on — several of them
emit identical payloads and differ *only* in that label.

| Action | Alias(es) | Payload per tick |
| :----- | :-------- | :--------------- |
| `saf` | `raf` | heartbeat: `tick`, `transport`, `interval`, `log_level`, `data_dir` (no WID) |
| `saf-wid` | `waf`, `wraf` | heartbeat + a fresh WID, plus `W`/`Z`/`time_unit` |
| `wir` | `witr` | identical shape to `saf` (label differs) |
| `wism` | `wim` | fresh WID + `W`/`Z`, `interval`, `data_dir` |
| `wihp` | `wih` | identical shape to `wism` (label differs) |
| `wipr` | `wip` | identical shape to `wism` (label differs) |
| `duplex` | — | heartbeat with two transport labels (`a_transport` from `R=`, `b_transport` from `I=`, default `ws`) |

## Lifecycle — the daemon

`A=start` spawns the binary again as `__daemon` running `A=run` and detaches
it into its own session (`setsid`), so it survives the terminal that
launched it. Runtime files (`service.pid`, `service.log`) live in a
per-user directory resolved as: `$WID_RUNTIME_DIR` >
`$XDG_STATE_HOME/wid/rust` > `$HOME/.local/state/wid/rust` — *not* relative
to the working directory, so `start`, `status`, and `stop` manage the same
daemon no matter where they run from. One daemon per user.

Safety properties (and their limits):

- The PID file is claimed atomically (`O_CREAT|O_EXCL`); concurrent `start`s
  cannot both win. A stale file left by a dead daemon is reclaimed.
- `stop`/`status` verify (via `/proc/<pid>/cmdline`, where available) that
  the recorded PID still belongs to a wid daemon before signaling it, so a
  recycled PID is never killed.
- `stop` sends SIGTERM, waits up to ~2 s, then escalates to SIGKILL.

This is a development-grade runner, not a production supervisor: there is no
restart-on-crash, no log rotation, and no systemd/launchd integration. If
you need those, run `wid A=run … ` under your init system instead of using
`A=start`.

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
