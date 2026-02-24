#!/usr/bin/env python3
"""Validate README capability claims against spec/capabilities.json."""

# pylint: skip-file
# flake8: noqa: D103, C901, E501
# pyright: reportArgumentType=false,reportAny=false

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
CAPS = ROOT / "spec" / "capabilities.json"


def require(text: str, needle: str, errors: list[str]) -> None:
    if needle not in text:
        errors.append(f"missing README claim: {needle}")


def find_line(text: str, prefix: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line
    return None


def backtick_tokens(line: str) -> set[str]:
    raw = set(re.findall(r"`([^`]+)`", line))
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


def main() -> int:
    errors: list[str] = []

    data = json.loads(CAPS.read_text(encoding="utf-8"))
    readme = README.read_text(encoding="utf-8")

    langs = data["languages"]
    per_language = data["per_language"]
    for lang in langs:
        if lang not in per_language:
            errors.append(f"capabilities missing per_language entry: {lang}")

    summary = data["summary"]

    core_only_langs = set(summary["core_cli_only_languages"])
    core_only_line = find_line(readme, "- Core-CLI-only implementations:")
    if core_only_langs:
        if core_only_line is None:
            errors.append("missing README core-cli-only line")
        else:
            got = backtick_tokens(core_only_line)
            if not core_only_langs.issubset(got):
                errors.append("core-cli-only line does not include expected languages")
            if not {
                "next",
                "stream",
                "validate",
                "parse",
                "healthcheck",
                "bench",
                "selftest",
            }.issubset(got):
                errors.append("core-cli-only line is missing one or more core actions")

    state_modes = summary["state_modes_generation_sql"]
    for mode in state_modes:
        require(readme, f"- `E={mode}`", errors)

    stream_semantics = summary.get("stream_n0_semantics")
    if stream_semantics == "infinite":
        require(readme, "- `A=stream N=0` means infinite stream (all primary implementations).", errors)

    for lang in langs:
        entry = per_language.get(lang, {})
        if "stream_n0" not in entry:
            errors.append(f"per_language.{lang} missing stream_n0")
        elif entry["stream_n0"] != stream_semantics:
            errors.append(
                f"per_language.{lang}.stream_n0 mismatch: expected {stream_semantics}, got {entry['stream_n0']}"
            )

    table_langs = re.findall(r"\|\s*\d+\s*\|\s*\*\*([^*]+)\*\*", readme)
    normalized: list[str] = []
    mapping = {"TypeScript": "typescript", "Rust": "rust", "Python": "python", "Go": "go", "C": "c", "sh": "sh"}
    for item in table_langs:
        key = mapping.get(item.strip())
        if key:
            normalized.append(key)
    missing = sorted(set(langs) - set(normalized))
    extra = sorted(set(normalized) - set(langs))
    if missing:
        errors.append(f"README implementation table missing languages from capabilities: {missing}")
    if extra:
        errors.append(f"README implementation table has extra languages not in capabilities: {extra}")

    if errors:
        print("Capability consistency check failed:", file=sys.stderr)
        for e in errors:
            print(f"- {e}", file=sys.stderr)
        return 1

    print("Capability consistency check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
