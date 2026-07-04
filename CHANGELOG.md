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
- Memory-safety gates for the C implementation: `make c-sanitize` reruns the
  unit tests and CLI selftest under ASan+UBSan (recovery disabled), and
  `make c-fuzz` drives the header's untrusted-input parsers
  (`wid_validate_ex`/`wid_parse_ex`, plain and HLC, including out-of-range
  W/Z) with libFuzzer (`c/fuzz/fuzz_parse.c`). Both run in CI (`c-sanitize`
  job) and in the publish gate. First fuzz run: ~4.3M execs, no findings.
- Formatting is now enforced, not optional: `make rust-lint` runs
  `cargo fmt --check`, `make go-lint` fails on unformatted files via `gofmt
  -l` even when golangci-lint is absent (previously CI silently fell back to
  `go vet` only), ESLint covers `typescript/test/` in addition to `src/`,
  and `make fmt` formats Python, Rust, Go, and C.

### Fixed
- TypeScript parse: years 0000–0099 were shifted to 1900–1999 by
  `Date.UTC`'s two-digit-year mapping (`00500212T…` parsed as 1950 while
  Rust/Python/Go return year 50), and leap days in that range were judged
  against the remapped year. The literal 4-digit year is now pinned via
  `setUTCFullYear`, the day/month roundtrip check gained a year check, the
  duplicated timestamp parser in `wid.ts`/`hlc.ts` was deduplicated into
  `time.ts`, and a low-year conformance fixture (`wid_low_year_w4_z0`) now
  pins acceptance across all six implementations.
- README: relative links (spec documents, implementation directories,
  LICENSE) are now absolute `github.com/waldiez/wid` URLs. GitHub, npm, and
  crates.io resolve or rewrite relative README links, but PyPI renders the
  README verbatim, so every relative link would 404 on the project page.
- Publish workflow: the pre-publish test job now mirrors the main CI gates
  (stream conformance, strict CLI-surface, w-otp parity, strict crypto
  smoke, C sanitizer) instead of a subset — a tag can no longer publish
  code that a main-branch CI run would fail. npm publishes with
  `--provenance`; the unconditional Docker `latest` tag was removed so a
  prerelease tag (e.g. `v1.1.0-rc.1`) cannot hijack `latest`
  (metadata-action's `latest=auto` applies it to stable semver tags only).
- Pages deploy triggered only on `docs/index.html` while deploying the whole
  `docs/` folder, silently leaving the published site stale after edits to
  any other docs file; it now triggers on `docs/**`.
- sh: `A=sign`/`A=verify`/selftest temp files are now removed by an EXIT
  trap even when the script dies between `mktemp` and the eager cleanup
  (previously an early `die` — e.g. an invalid signature encoding — leaked
  the message/signature temp files).
- CI Go toolchain bumped 1.22 → 1.25: 1.22 is outside Go's two-release
  security-fix window (`go.mod` keeps `go 1.22` as the library's minimum).
- Go and Rust `A=w-otp`: the OTP modulus (`10^DIGITS`, CRYPTO_SPEC) was
  computed in 32 bits, which cannot hold `10^10`. At `DIGITS=10` Go's
  `uint32` wrapped the modulus to `1410065408` (a *different* code than the
  other implementations for roughly two-thirds of HMAC values) and Rust's
  `saturating_mul` clamped it to `2^32-1` (divergent only for an HMAC word of
  exactly `0xffffffff`). Both now use 64-bit arithmetic.
- `tools/check_wotp_parity.sh` only exercised `DIGITS=6`, so the above
  divergence sat behind a green gate. It now round-trips gen/verify at
  `DIGITS` 4, 6, and 10 against a probe WID chosen so its 32-bit HMAC word
  (`0xf960d3a5`) makes wrap/saturation bugs deterministically visible rather
  than dependent on the sample's hash value.
- sh: when no `python3 >= 3.10` was on PATH and the `uv` fallback *failed*,
  canonical delegation (`I=auto`/`py`) exited 0 with no output (a failed
  `if` condition returns success from a function under `set -e`); it now
  fails with a clean `error: …`.
- C: removed the `has_unsafe_shell_char` filter from the canonical parser.
  The C CLI never shells out (sqlite3/libcrypto are linked directly), and
  the filter made C the only implementation to reject KEY/DATA/OUT values
  containing quotes, `;`, `&`, `|`, or backticks that the other five accept.
- Scoped the shared-SQLite "no duplicate WIDs" guarantee to the CLI `E=sql`
  path (which allocates via compare-and-swap): the library-level stores
  (Python `SqliteWidStateStore`, TypeScript `createNodeSqliteWidStateStore`)
  are last-writer-wins and now document that they are single-process only.
  README no longer implies otherwise, and it now discloses that `make next`
  (`I=auto`) delegates to the Python implementation when one is present.
- TypeScript canonical parser: values containing `=` (e.g.
  `KEY=abc=def`, base64 secrets) were silently truncated at the second `=`
  by `split("=", 2)`, so the same w-otp secret produced a *different* code
  than the other five implementations. Now parses on the first `=` only;
  a cross-language parity gate in `cli_surface.json` pins this.
- TypeScript manifest (`WidFile.fromBytes`): now rejects unknown header
  versions and truncated manifest bodies, matching Rust's
  `UnsupportedVersion`/`DataTooSmall`.
- Unified the default `E=sql` state database location to
  `<cwd>/.local/services/wid_state.sqlite` in all six implementations.
  Python previously defaulted to `~/.local/wid/services/` and sh to the
  repository root, silently splitting the shared monotonic state.
- sh: `stream --count 0` streamed 10 IDs instead of forever; 0 now means
  unbounded everywhere (flag and canonical mode alike).
- Python CLI flag mode: unknown flags were silently ignored in
  `validate`/`parse`, `--time-unit moo` was silently read as `ms`, and a
  missing key file (or missing `cryptography` install) printed a raw
  traceback. All now exit with a clean `error: …`.
- Extreme/corrupt resume-state ticks now saturate to the formattable range
  in **all six** implementations (previously Rust-only): TS/Go emitted
  malformed >8-digit-year IDs, Python raised, C's `strftime` could return
  garbage.
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
- `make go-lint` had a broken `&&`/`||` chain that could never fail on
  golangci-lint findings (and hid dead code, since deleted).

### Pre-release breaking reshapes (never released, listed for `main` trackers)
- Signing message framing (`wid-sig-v1:` + WID byte length) replaced bare
  `WID || DATA`; old signatures no longer verify (CRYPTO_SPEC 1.1.0).
- SQL state key unified to `wid:W:Z:T` (language tag dropped) so
  implementations share monotonic state.
- Service layer and `self.check-update` removed from C/Go/Python/TS/sh;
  the service layer is Rust-only.
- W/Z bounds unified to W∈[1,18], Z∈[0,64], reject-not-clamp, in every CLI.
- TypeScript's non-standard plain-WID "scope" extension removed.
- Running `wid` with no arguments now prints usage and exits 2 in every
  implementation (Python and sh used to silently emit one ID); the
  Python-only `WID_DEFAULT_MODE` environment variable is gone.
- Python-only flag-mode extras removed (`--format jsonl`, `--interval-ms`,
  `--cadence`, `--healthcheck-cmd`, and ~20 unregistered service entry
  points): the flag surface is now identical across implementations.
- Go library: sequence state widened to `int64`
  (`State`/`RestoreState`/`Observe` signatures changed) so `W=18` cannot
  overflow on 32-bit GOARCH.
