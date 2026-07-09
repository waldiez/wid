"""CLI entrypoints for emit, stream, and healthcheck modes."""

from __future__ import annotations

import subprocess
import sys

from .canonical import run_canonical
from .commands import (
    run_bench_mode,
    run_emit_mode,
    run_healthcheck_mode,
    run_parse_mode,
    run_selftest_mode,
    run_validate_mode,
)
from .completion import print_completion
from .help import print_actions, print_usage

__all__ = ["hlc_wid_main", "main"]


def main() -> None:
    """Wid main entrypoint."""
    if len(sys.argv) >= 2 and sys.argv[1] in {"-h", "--help", "help"}:
        print_usage()
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "completion":
        if len(sys.argv) < 3:
            print("usage: wid completion bash|zsh|fish", file=sys.stderr)
            sys.exit(1)
        print_completion(sys.argv[2])
        return

    try:
        if run_canonical(sys.argv[1:]):
            return
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    except (RuntimeError, OSError, TypeError, ImportError) as exc:
        # OSError: missing key/data files; ImportError: cryptography not
        # installed; TypeError: wrong key type. Same contract as the other
        # implementations: `error: ...` on stderr, never a traceback.
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)

    # Flag-mode subcommands share the canonical mode's error contract:
    # invalid values exit with a clean `error: ...`, never a traceback.
    try:
        _dispatch_flag_mode()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    except (RuntimeError, OSError, TypeError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


def _dispatch_flag_mode() -> None:
    # No arguments prints usage and exits 2, matching every other
    # implementation (a bare `wid` used to silently emit one ID).
    """Dispatch flag-mode subcommands (next, stream, validate, ...)."""
    if len(sys.argv) == 1:
        print_usage(sys.stderr)
        sys.exit(2)

    cmd = sys.argv[1]
    if cmd in {"next", "stream"}:
        run_emit_mode(cmd, sys.argv[2:])
        return

    if cmd == "help-actions":
        print_actions()
        return

    if cmd == "healthcheck":
        run_healthcheck_mode(sys.argv[2:])
        return

    if cmd == "validate":
        run_validate_mode(sys.argv[2:])
        return

    if cmd == "parse":
        run_parse_mode(sys.argv[2:])
        return

    if cmd == "bench":
        run_bench_mode(sys.argv[2:])
        return

    if cmd == "selftest":
        run_selftest_mode()
        return

    print(f"Unknown command: {cmd}", file=sys.stderr)
    sys.exit(2)


def _run_cli_entry(args: list[str]) -> None:
    """Run the CLI with an explicit argv (used by the hlc-wid entry point)."""
    original = list(sys.argv)
    try:
        sys.argv = [sys.argv[0], *args, *original[1:]]
        main()
    finally:
        sys.argv = original


def hlc_wid_main() -> None:
    """Default hlc-wid command."""
    _run_cli_entry(["next", "--kind", "hlc"])
