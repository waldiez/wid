#!/usr/bin/env python3
"""Validate README capability claims against spec/capabilities.json.

The capability matrix (which language implements what) is data in
``spec/capabilities.json``; the README repeats parts of it as prose. This
check fails when the two drift apart.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
CAPS = ROOT / "spec" / "capabilities.json"


def require(text: str, needle: str, errors: list[str]) -> None:
    """Record an error if ``needle`` does not appear verbatim in ``text``."""
    if needle not in text:
        errors.append(f"missing README claim: {needle}")


def find_line(text: str, prefix: str) -> str | None:
    """Return the first line of ``text`` starting with ``prefix``, if any."""
    for line in text.splitlines():
        if line.startswith(prefix):
            return line
    return None


def backtick_tokens(line: str) -> set[str]:
    """Extract backticked tokens from a README line, lowercasing languages."""
    raw: set[str] = set(re.findall(r"`([^`]+)`", line))
    aliases = {
        "TypeScript": "typescript",
        "Rust": "rust",
        "Python": "python",
        "Go": "go",
        "C": "c",
    }
    out: set[str] = set()
    for token in raw:
        out.add(aliases.get(token, token))
    return out


CORE_ACTIONS = {
    "next", "stream", "validate", "parse", "healthcheck", "bench", "selftest"
}


def check_core_only_line(
    readme: str, summary: dict[str, Any], errors: list[str]
) -> None:
    """Check the README's core-CLI-only sentence against the summary."""
    core_only_langs = set(summary["core_cli_only_languages"])
    if not core_only_langs:
        return
    core_only_line = find_line(readme, "- Core-CLI-only implementations:")
    if core_only_line is None:
        errors.append("missing README core-cli-only line")
        return
    got = backtick_tokens(core_only_line)
    if not core_only_langs.issubset(got):
        errors.append("core-cli-only line does not include expected languages")
    if not CORE_ACTIONS.issubset(got):
        errors.append("core-cli-only line is missing one or more core actions")


def check_stream_claims(
    readme: str,
    summary: dict[str, Any],
    langs: list[str],
    per_language: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    """Check E= state modes and stream N=0 semantics claims."""
    state_modes: list[str] = summary["state_modes_generation_sql"]
    for mode in state_modes:
        require(readme, f"- `E={mode}`", errors)

    stream_semantics = summary.get("stream_n0_semantics")
    if stream_semantics == "infinite":
        require(
            readme,
            "- `A=stream N=0` means infinite stream (all primary implementations).",
            errors,
        )

    for lang in langs:
        entry = per_language.get(lang, {})
        if "stream_n0" not in entry:
            errors.append(f"per_language.{lang} missing stream_n0")
        elif entry["stream_n0"] != stream_semantics:
            errors.append(
                f"per_language.{lang}.stream_n0 mismatch:"
                + f" expected {stream_semantics}, got {entry['stream_n0']}"
            )


def check_impl_table(readme: str, langs: list[str], errors: list[str]) -> None:
    """Check the README implementation table lists exactly the languages."""
    table_langs = re.findall(r"\|\s*\d+\s*\|\s*\*\*([^*]+)\*\*", readme)
    mapping = {
        "TypeScript": "typescript",
        "Rust": "rust",
        "Python": "python",
        "Go": "go",
        "C": "c",
        "sh": "sh",
    }
    normalized = [key for item in table_langs if (key := mapping.get(item.strip()))]
    missing = sorted(set(langs) - set(normalized))
    extra = sorted(set(normalized) - set(langs))
    if missing:
        errors.append(f"README implementation table missing languages: {missing}")
    if extra:
        errors.append(f"README implementation table has extra languages: {extra}")


def main() -> int:
    """Compare capabilities.json against the README; 0 iff consistent."""
    errors: list[str] = []

    data: dict[str, Any] = json.loads(CAPS.read_text(encoding="utf-8"))
    readme = README.read_text(encoding="utf-8")

    langs: list[str] = data["languages"]
    per_language: dict[str, dict[str, Any]] = data["per_language"]
    for lang in langs:
        if lang not in per_language:
            errors.append(f"capabilities missing per_language entry: {lang}")

    summary: dict[str, Any] = data["summary"]
    check_core_only_line(readme, summary, errors)
    check_stream_claims(readme, summary, langs, per_language, errors)
    check_impl_table(readme, langs, errors)

    if errors:
        print("Capability consistency check failed:", file=sys.stderr)
        for e in errors:
            print(f"- {e}", file=sys.stderr)
        return 1

    print("Capability consistency check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
