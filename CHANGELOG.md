# Changelog

All notable changes to WID are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/). The identifier grammar itself is versioned by
`spec/SPEC.md`; the crypto surface by `spec/CRYPTO_SPEC.md` (currently
1.1.0 — see its changelog for the signing-message framing change).

## [Unreleased]

Nothing has been tagged or published yet; everything below describes the
state the first release (`v1.0.0`) will ship with. Users tracking `main`
before the first tag should note the **pre-release breaking reshapes**
called out at the bottom.

### Added
- WID and HLC-WID generation, validation, and parsing in six implementations
  (Rust, C, Go, Python, TypeScript, Bash) conforming to one spec
  (`spec/SPEC.md`), with shared executable conformance fixtures
  (`spec/conformance/`) driven against all six real CLIs in CI.
- Crypto surface (`spec/CRYPTO_SPEC.md` 1.1.0): Ed25519 `sign`/`verify` over
  a length-framed, domain-separated canonical message, and `w-otp`, a
  WID-bound truncated HMAC with a documented threat model. Native crypto in
  all implementations except `sh` (which drives the `openssl` CLI and is
  documented as unsuitable for production secrets).
- `E=sql`: cross-process, cross-language monotonic state in SQLite, sharing
  one language-agnostic state row.
- Rust-only service layer (`spec/SERVICES.md`): dev-grade daemon lifecycle
  plus periodic JSON emitters with transport *labels* (metadata only — no
  broker clients).
- Rust/TS-only WIDM manifest module (see README "Extensions beyond the
  spec").

### Fixed
- Unified the canonical `A=stream` cadence across all six CLIs: an unset or
  placeholder `L` emits back-to-back; only an explicit `L=n` sleeps n seconds
  between emissions. Previously Rust/Go/C ignored `L=` entirely while
  Python/TS/sh slept the 3600 s service default per line.
- sh: ms-precision ticks were corrupt (16-digit values) on systems where
  `date` expands `%3N`/`%N` to microseconds (uutils coreutils, the default on
  newer Ubuntu); the capability probe now requires exact digit counts.
- Python CLI: flag-mode subcommands (`next --W 19`, …) now exit with a clean
  `error: …` instead of an uncaught traceback, matching canonical mode.
- Rust daemon (`A=start`): detaches via `setsid`, claims the PID file
  atomically, verifies PID identity before signaling (no killing recycled
  PIDs), and anchors runtime files to `$XDG_STATE_HOME`/`$HOME/.local/state`
  instead of the working directory.
- Rust library: removed the vestigial `scope` parameter from `WidGen::new`/
  `new_with_time_unit` (and `WidError::InvalidScope`); extreme/corrupt ticks
  now saturate instead of panicking.
- Renamed the manifest container type `SynapseFile` → `WidFile` and its magic
  `SYNM` → `WIDM` (Rust + TypeScript; format was never released).

### Pre-release breaking reshapes (never released, listed for `main` trackers)
- Signing message framing (`wid-sig-v1:` + WID byte length) replaced bare
  `WID || DATA`; old signatures no longer verify (CRYPTO_SPEC 1.1.0).
- SQL state key unified to `wid:W:Z:T` (language tag dropped) so
  implementations share monotonic state.
- Service layer and `self.check-update` removed from C/Go/Python/TS/sh;
  the service layer is Rust-only.
- W/Z bounds unified to W∈[1,18], Z∈[0,64], reject-not-clamp, in every CLI.
- TypeScript's non-standard plain-WID "scope" extension removed.
