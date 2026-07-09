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
# /home/runner is the well-known GitHub Actions user whose nvm install
# ensure_bash.sh deliberately probes -- not a leaked host path.
if rg -n -e "/Users/[A-Za-z0-9._-]+" -e "/home/[A-Za-z0-9._-]+" README.md docs spec tools Makefile | rg -v '/home/runner'; then
  echo "[hardening] FAIL: absolute host paths found in public files"
  exit 1
fi

echo "[hardening] packaging hygiene"
if [ ! -f "dist/cli.js" ]; then
  echo "[hardening] FAIL: dist/cli.js missing (run: bun run build)"
  exit 1
fi

echo "[hardening] service semantics spot-check"
lines="$(node dist/cli.js A=stream N=3 L=0 W=4 Z=0 T=sec | wc -l | tr -d ' ')"
if [ "$lines" != "3" ]; then
  echo "[hardening] FAIL: expected 3 lines from bounded stream; got $lines"
  exit 1
fi

echo "[hardening] sql persistence spot-check"
a="$(node dist/cli.js A=next E=sql D=.local/sql-hardening W=4 Z=0 T=sec)"
b="$(node dist/cli.js A=next E=sql D=.local/sql-hardening W=4 Z=0 T=sec)"
if [ "$a" = "$b" ]; then
  echo "[hardening] FAIL: consecutive SQL IDs are equal"
  exit 1
fi

echo "[hardening] PASS"
