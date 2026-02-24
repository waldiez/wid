# Contributing to WID

WID is a multi-language, multi-target reference implementation. This guide keeps newcomers productive fast while keeping the QA gates in reach.

## First five minutes

- Clone the repo and `cd` into it.
- Run `make setup` (installs dependencies across languages).
- Run `make next` to confirm the canonical CLI works.
- Try `make test` or `make quick-check` (see below) to verify the repo is healthy.
- Open `README.md`→`CONTRIBUTING.md`→`docs/qa/developer.md` for deeper context.

## When you’re ready to contribute

1. Branch from `main` or `master` of the host you push to (GitHub/GitLab).
2. Pick a clear single intent (feature/fix/test) and update relevant folders only.
3. Use `make quick-check` for a fast gate, then rerun the detailed suite: `make check` (or the language-specific subset you touched).
4. `git status` should be clean except for your files, then `git add` and `git commit` with a descriptive message.
5. Push your branch and open a merge request with the QA checklist filled in the description.

## Platform prerequisites

- **macOS/Linux**: `bash`, `python3`, `cargo`, `node`/`npm`, `go`, `docker` (optional). `make setup` installs the rest.
- **Windows**: Use Windows Subsystem for Linux (WSL) or Git Bash. `make setup` still works once the shell has `bash` and the same toolchain installed.

## Optional language-specific installs

- `python`: `pip install -e ".[dev]"` (already driven by `python-setup`).
- `rust`: `rustup` toolchain (stable + clippy). `cargo install --path rust` for CLI.
- `typescript`: `npm install` from repo root (tsup build, vitest). `npm run build` to ensure dist.
- `go`: `go install ./go/cmd/wid` for local CLI.

## Workflow expectations

- Keep changes small and focused. Large refactors benefit from design discussions in issues/PR comments.
- Document behavior in the relevant `docs/` or `spec/` file when the change affects behavior.
- Run linters/formatters before committing (`make lint` or the language-specific scripts) and capture failures as part of your PR notes.

## QA checklist for PRs

- `make quick-check` passes locally.
- Relevant implementation tests (`cargo test`, `npm test`, etc.) are green.
- `docs/qa/developer.md` or `docs/qa/README.md` updated if the change affects QA steps.
- `spec/` updated for behavior/format changes.
- PR description includes: summary, testing commands, expected runtime, blockers (if any).
