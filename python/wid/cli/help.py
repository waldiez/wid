"""Help and usage text for the wid CLI."""

from __future__ import annotations

import sys
from typing import TextIO


def print_actions() -> None:
    """Print the canonical action matrix (A=...)."""
    print("""wid action matrix

Core ID:
  A=next | A=stream | A=healthcheck
  A=sign | A=verify | A=w-otp

Services (Rust implementation only -- see spec/SERVICES.md):
  A=start | A=stop | A=status | A=logs | A=run | A=discover | A=scaffold
  A=saf | A=saf-wid | A=wir | A=wism | A=wihp | A=wipr | A=duplex

Help:
  A=help-actions

State mode:
  E=state | E=stateless | E=sql
""")


def print_usage(stream: TextIO = sys.stdout) -> None:
    """Print CLI usage to ``stream`` (stdout for help, stderr on error)."""
    print(
        """wid python CLI

Usage:
  python -m wid [next|stream|healthcheck|help-actions] [options]
  python -m wid A=<action> W=<n> Z=<n> ...

Commands:
  next         Emit one ID.
  stream       Emit IDs continuously (or until --count).
  validate     Validate an ID string.
  parse        Parse an ID string.
  healthcheck  Generate one sample and validate format.
  bench        Benchmark generation throughput.
  selftest     Run built-in sanity checks (silent, exit 0/1).
  help-actions Show canonical action matrix (A=...).
  sign         Canonical mode only:
               A=sign WID=<wid> KEY=<priv.pem> [DATA=<path>] [OUT=<path>].
  verify       Canonical mode only:
               A=verify WID=<wid> KEY=<pub.pem> SIG=<sig> [DATA=<path>].
  w-otp        Canonical mode only:
               A=w-otp MODE=gen|verify KEY=<secret|path> [WID=<wid>]
               [CODE=<otp>] [DIGITS=<n>] [MAX_AGE_SEC=<n>] [MAX_FUTURE_SEC=<n>].

Examples:
  python -m wid next
  python -m wid stream --kind wid --W 4 --Z 0
  python -m wid healthcheck --kind hlc --W 4 --Z 0 --node edge01
  python -m wid A=next W=4 Z=0 T=sec
""",
        file=stream,
    )
