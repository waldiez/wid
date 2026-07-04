<!-- Keep the intent single and small; large refactors start as an issue. -->

## Summary

<!-- What changes and why. Link the issue if one exists. -->

## Scope

- [ ] Shared CLI surface / identifier grammar → **changed in all six implementations** (Rust, C, Go, Python, TypeScript, sh)
- [ ] Conformance fixtures updated (`spec/conformance/*.json`) for any new/changed behavior
- [ ] Spec updated (`spec/SPEC.md` / `spec/CRYPTO_SPEC.md` / `spec/SERVICES.md`) if behavior or format changed
- [ ] Single-language change only (no shared surface touched)

## QA checklist

- [ ] `make quick-check` passes
- [ ] `make check` (or the language subsets touched) passes
- [ ] `make cli-surface-check` / `make id-conformance` pass if the CLI surface or grammar was touched
- [ ] TypeScript sources changed → `dist/` rebuilt and committed (`bun run build`; install-from-git depends on it, CI gates freshness)
- [ ] `CHANGELOG.md` updated for user-visible changes

## Testing

<!-- Commands you ran and their results; note approximate runtime for slow suites. -->

## Notes / blockers

<!-- Anything reviewers should know: trade-offs, follow-ups, open questions. -->
