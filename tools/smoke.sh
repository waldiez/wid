#!/usr/bin/env sh
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# 1) Repo gates
python3 tools/check_capabilities.py
python3 tools/check_stream_conformance.py

# 2) Crypto parity smoke
if ! bash tools/smoke_crypto.sh; then
  echo "Crypto parity smoke reported failures (non-blocking in smoke.sh)." >&2
fi
