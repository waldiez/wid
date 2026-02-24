#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[hardening] starting"

echo "[hardening] release gates"
make release-check
bash tools/smoke.sh
SMOKE_CRYPTO_STRICT=1 bash tools/smoke_crypto.sh
make signed-envelope-check
make security-matrix-check
make key-rotation-drill-check
make envelope-compat-check
SOAK_SECONDS="${SOAK_SECONDS:-15}" make soak-check

echo "[hardening] path hygiene"
if rg -n -e "/Users/[A-Za-z0-9._-]+" -e "/home/[A-Za-z0-9._-]+" README.md docs spec tools Makefile; then
  echo "[hardening] FAIL: absolute host paths found in public files"
  exit 1
fi

echo "[hardening] packaging hygiene"
if [ ! -f "typescript/dist/cli.js" ]; then
  echo "[hardening] FAIL: typescript/dist/cli.js missing (run: npm run build)"
  exit 1
fi

echo "[hardening] service semantics spot-check"
lines="$(node typescript/dist/cli.js A=stream N=3 L=0 W=4 Z=0 T=sec | wc -l | tr -d ' ')"
if [ "$lines" != "3" ]; then
  echo "[hardening] FAIL: expected 3 lines from bounded stream; got $lines"
  exit 1
fi

echo "[hardening] sql persistence spot-check"
a="$(node typescript/dist/cli.js A=next E=sql D=.local/sql-hardening W=4 Z=0 T=sec)"
b="$(node typescript/dist/cli.js A=next E=sql D=.local/sql-hardening W=4 Z=0 T=sec)"
if [ "$a" = "$b" ]; then
  echo "[hardening] FAIL: consecutive SQL IDs are equal"
  exit 1
fi

echo "[hardening] PASS"
