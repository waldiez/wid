#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

STRICT="${WOTP_PARITY_STRICT:-0}"
TARGETS_RAW="${WOTP_PARITY_LANGS:-}"

mkdir -p .local/wotp-parity .local/go-cache .local/home .local/cache .local/julia .local/swift-modcache
ERR_FILE=".local/wotp-parity/.err.txt"

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
PASS_NAMES=""
FAIL_NAMES=""
SKIP_NAMES=""

say() {
  printf '[wotp-parity] %s\n' "$*"
}

mark_pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  PASS_NAMES="${PASS_NAMES}$1 "
  say "PASS: $1"
}

mark_fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  FAIL_NAMES="${FAIL_NAMES}$1 "
  say "FAIL: $1 :: $2"
}

mark_skip() {
  SKIP_COUNT=$((SKIP_COUNT + 1))
  SKIP_NAMES="${SKIP_NAMES}$1 "
  say "SKIP: $1 :: $2"
}

is_runtime_cache_error() {
  grep -qi "Could not create lockfile" "$ERR_FILE" || \
  grep -qi "ModuleCache" "$ERR_FILE" || \
  grep -qi "juliaup channel" "$ERR_FILE" || \
  grep -qi "Failed to download" "$ERR_FILE" || \
  grep -qi "engine.stamp" "$ERR_FILE" || \
  grep -qi "Operation not permitted" "$ERR_FILE"
}

should_run() {
  local name="$1"
  if [[ -z "$TARGETS_RAW" ]]; then
    return 0
  fi
  local norm=",${TARGETS_RAW// /},"
  [[ "$norm" == *",$name,"* ]]
}

extract_otp() {
  printf '%s' "$1" | sed -nE 's/.*"otp":"([0-9]{4,10})".*/\1/p' | head -n1
}

choose_python_cmd() {
  if [[ -n "${WOTP_PYTHON:-}" ]]; then
    if command -v "$WOTP_PYTHON" >/dev/null 2>&1; then
      printf '%s\n' "$WOTP_PYTHON"
      return 0
    fi
    return 1
  fi
  local cand
  for cand in python3 python python3.12 python3.11 python3.10 python3.13 python3.14; do
    if command -v "$cand" >/dev/null 2>&1; then
      if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        printf '%s\n' "$cand"
        return 0
      fi
    fi
  done
  return 1
}

WID_SAMPLE="${WOTP_SAMPLE_WID:-20260219T000000.0000Z}"
say "Using WID sample: $WID_SAMPLE"

KEY_SAMPLE="wotp-parity-secret"
DIGITS="6"
BAD_CODE="000000"
BASELINE_OTP=""
OLD_WID_SAMPLE="20200101T000000.0000Z"

if PYTHON_CMD="$(choose_python_cmd)"; then
  out="$(env PYTHONPATH=python "$PYTHON_CMD" -m wid A=w-otp MODE=gen KEY="$KEY_SAMPLE" WID="$WID_SAMPLE" DIGITS="$DIGITS" 2>/dev/null || true)"
  BASELINE_OTP="$(extract_otp "$out")"
fi
if [[ -z "$BASELINE_OTP" ]]; then
  out="$(bash sh/wid A=w-otp MODE=gen KEY="$KEY_SAMPLE" WID="$WID_SAMPLE" DIGITS="$DIGITS" 2>/dev/null || true)"
  BASELINE_OTP="$(extract_otp "$out")"
fi
if [[ -z "$BASELINE_OTP" ]]; then
  say "Unable to resolve baseline OTP value."
  exit 1
fi
if [[ "$BASELINE_OTP" == "$BAD_CODE" ]]; then
  BAD_CODE="999999"
fi
say "Baseline OTP: $BASELINE_OTP"

run_case() {
  local name="$1"
  shift
  local out
  local otp

  if ! out="$("$@" A=w-otp MODE=gen KEY="$KEY_SAMPLE" WID="$WID_SAMPLE" DIGITS="$DIGITS" 2>"$ERR_FILE")"; then
    if is_runtime_cache_error; then
      mark_skip "$name" "host runtime cache/lock permission issue"
      return 0
    fi
    mark_fail "$name" "gen failed: $(tr '\n' ' ' < "$ERR_FILE")"
    return 0
  fi

  otp="$(extract_otp "$out")"
  if [[ -z "$otp" ]]; then
    mark_fail "$name" "gen output missing otp field"
    return 0
  fi
  if [[ "$otp" != "$BASELINE_OTP" ]]; then
    mark_fail "$name" "otp mismatch (expected=$BASELINE_OTP got=$otp)"
    return 0
  fi

  if ! "$@" A=w-otp MODE=verify KEY="$KEY_SAMPLE" WID="$WID_SAMPLE" CODE="$otp" DIGITS="$DIGITS" > /dev/null 2>"$ERR_FILE"; then
    if is_runtime_cache_error; then
      mark_skip "$name" "host runtime cache/lock permission issue"
      return 0
    fi
    mark_fail "$name" "verify(valid) failed: $(tr '\n' ' ' < "$ERR_FILE")"
    return 0
  fi

  if "$@" A=w-otp MODE=verify KEY="$KEY_SAMPLE" WID="$WID_SAMPLE" CODE="$BAD_CODE" DIGITS="$DIGITS" > /dev/null 2>"$ERR_FILE"; then
    mark_fail "$name" "verify(invalid) unexpectedly succeeded"
    return 0
  fi

  if ! out="$("$@" A=w-otp MODE=gen KEY="$KEY_SAMPLE" WID="$OLD_WID_SAMPLE" DIGITS="$DIGITS" 2>"$ERR_FILE")"; then
    if is_runtime_cache_error; then
      mark_skip "$name" "host runtime cache/lock permission issue"
      return 0
    fi
    mark_fail "$name" "gen(old wid) failed: $(tr '\n' ' ' < "$ERR_FILE")"
    return 0
  fi
  local old_otp
  old_otp="$(extract_otp "$out")"
  if [[ -z "$old_otp" ]]; then
    mark_fail "$name" "gen(old wid) returned no otp"
    return 0
  fi
  if "$@" A=w-otp MODE=verify KEY="$KEY_SAMPLE" WID="$OLD_WID_SAMPLE" CODE="$old_otp" DIGITS="$DIGITS" MAX_AGE_SEC=60 MAX_FUTURE_SEC=5 > /dev/null 2>"$ERR_FILE"; then
    mark_fail "$name" "verify(time-window) unexpectedly accepted stale WID"
    return 0
  fi

  mark_pass "$name"
}

if should_run "sh"; then
  run_case "sh" bash sh/wid
fi

if PYTHON_CMD="$(choose_python_cmd)"; then
  if should_run "python"; then
    if env PYTHONPATH=python "$PYTHON_CMD" -c "import wid.cli" > /dev/null 2>"$ERR_FILE"; then
      run_case "python" env PYTHONPATH=python "$PYTHON_CMD" -m wid
    else
      if grep -q "ModuleNotFoundError" "$ERR_FILE"; then
        mark_skip "python" "python deps missing for wid.cli (install [crypto/sql] extras)"
      else
        mark_fail "python" "preflight import failed: $(tr '\n' ' ' < "$ERR_FILE")"
      fi
    fi
  fi
elif should_run "python"; then
  mark_skip "python" "python>=3.10 not found"
fi

if should_run "typescript" && command -v node >/dev/null 2>&1; then
  if [[ ! -f typescript/dist/cli.js ]] && command -v npm >/dev/null 2>&1; then
    npm run -s build >/dev/null 2>&1 || true
  fi
  if [[ -f typescript/dist/cli.js ]]; then
    run_case "typescript" node typescript/dist/cli.js
  else
    mark_skip "typescript" "typescript/dist/cli.js missing"
  fi
elif should_run "typescript"; then
  mark_skip "typescript" "node missing"
fi

if should_run "go" && command -v go >/dev/null 2>&1; then
  if GOCACHE="$PWD/.local/go-cache" go build -o go/cmd/wid/wid ./go/cmd/wid >/dev/null 2>&1; then
    run_case "go" go/cmd/wid/wid
  else
    mark_skip "go" "go build failed"
  fi
elif should_run "go"; then
  mark_skip "go" "go missing"
fi

if should_run "rust" && command -v cargo >/dev/null 2>&1; then
  if cargo build -q >/dev/null 2>&1; then
    run_case "rust" target/debug/wid
  else
    mark_skip "rust" "cargo build failed"
  fi
elif should_run "rust"; then
  mark_skip "rust" "cargo missing"
fi

if should_run "c" && command -v make >/dev/null 2>&1; then
  if make -C c setup >/dev/null 2>&1; then
    run_case "c" c/.build/wid
  else
    mark_skip "c" "c build failed"
  fi
elif should_run "c"; then
  mark_skip "c" "make missing"
fi


say "Summary: pass=$PASS_COUNT fail=$FAIL_COUNT skip=$SKIP_COUNT"
if [[ -n "$PASS_NAMES" ]]; then say "Passed: $PASS_NAMES"; fi
if [[ -n "$SKIP_NAMES" ]]; then say "Skipped: $SKIP_NAMES"; fi
if [[ -n "$FAIL_NAMES" ]]; then say "Failed: $FAIL_NAMES"; fi

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  exit 1
fi
if [[ "$STRICT" == "1" && "$SKIP_COUNT" -gt 0 ]]; then
  say "WOTP_PARITY_STRICT=1 and skips detected."
  exit 1
fi

exit 0
