#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

STRICT="${SMOKE_CRYPTO_STRICT:-0}"
mkdir -p .local/crypto-smoke .local/go-cache

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

PASS_NAMES=""
FAIL_NAMES=""
SKIP_NAMES=""

# Implementations that passed their self-test, captured for the cross-impl
# interop matrix (name + invocation command string), parallel arrays.
XV_NAMES=()
XV_CMDS=()

say() {
  printf '[crypto-smoke] %s\n' "$*"
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

choose_python_cmd() {
  local cand
  for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        printf '%s\n' "$cand"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_CMD=""
if PYTHON_CMD="$(choose_python_cmd)"; then
  :
else
  say "No python>=3.10 found; python CLI crypto check will be skipped."
fi

PRIV_KEY=".local/crypto-smoke/ed25519_priv.pem"
PUB_KEY=".local/crypto-smoke/ed25519_pub.pem"
DATA_FILE=".local/crypto-smoke/data.txt"
DATA_BAD_FILE=".local/crypto-smoke/data_bad.txt"
ERR_FILE=".local/crypto-smoke/.err.txt"
OUT_FILE=".local/crypto-smoke/.sig.txt"

printf 'crypto-smoke data\n' > "$DATA_FILE"
printf 'tampered crypto-smoke data\n' > "$DATA_BAD_FILE"

openssl genpkey -algorithm Ed25519 -out "$PRIV_KEY" >/dev/null 2>&1
openssl pkey -in "$PRIV_KEY" -pubout -out "$PUB_KEY" >/dev/null 2>&1

OPENSSL_ED25519_OK=0
{
  msg_tmp="$(mktemp)"
  sig_tmp="$(mktemp)"
  printf 'probe' > "$msg_tmp"
  if openssl pkeyutl -sign -inkey "$PRIV_KEY" -rawin -in "$msg_tmp" -out "$sig_tmp" >/dev/null 2>&1; then
    OPENSSL_ED25519_OK=1
  fi
  rm -f "$msg_tmp" "$sig_tmp"
}
if [[ "$OPENSSL_ED25519_OK" -eq 1 ]]; then
  say "OpenSSL Ed25519 pkeyutl support detected."
else
  say "OpenSSL Ed25519 pkeyutl support missing; openssl-dependent CLIs will be skipped."
fi

NODE_ED25519_OK=0
if command -v node >/dev/null 2>&1; then
  if node - <<'NODE' >/dev/null 2>&1
const fs = require("fs");
const c = require("node:crypto");
const priv = fs.readFileSync(".local/crypto-smoke/ed25519_priv.pem");
const pub = fs.readFileSync(".local/crypto-smoke/ed25519_pub.pem");
const msg = Buffer.from("probe");
const sig = c.sign(null, msg, c.createPrivateKey(priv));
if (!c.verify(null, msg, c.createPublicKey(pub), sig)) process.exit(1);
NODE
  then
    NODE_ED25519_OK=1
  fi
fi
if [[ "$NODE_ED25519_OK" -eq 1 ]]; then
  say "Node Ed25519 sign/verify support detected."
else
  say "Node Ed25519 support missing; TypeScript CLI crypto check will be skipped."
fi

if [[ -f dist/cli.js ]]; then
  :
elif command -v npm >/dev/null 2>&1; then
  if ! npm run build >/dev/null; then
    say "TypeScript build failed; TypeScript will be skipped."
  fi
else
  say "TypeScript dist missing and npm unavailable."
fi

if command -v go >/dev/null 2>&1; then
  if ! GOCACHE="$PWD/.local/go-cache" go build -o go/cmd/wid/wid ./go/cmd/wid >/dev/null; then
    say "Go build failed; Go will be skipped."
  fi
fi

if command -v cargo >/dev/null 2>&1; then
  if ! cargo build -q >/dev/null; then
    say "Rust build failed; Rust will be skipped."
  fi
fi

if command -v make >/dev/null 2>&1; then
  if ! make -C c setup >/dev/null; then
    say "C build failed; C will be skipped."
  fi
fi

WID_SAMPLE=""
if [[ -f dist/cli.js ]]; then
  WID_SAMPLE="$(node dist/cli.js A=next W=4 Z=0 T=sec 2>/dev/null | head -n 1 || true)"
fi
if [[ -z "$WID_SAMPLE" ]]; then
  WID_SAMPLE="$(bash sh/wid A=next I=sh W=4 Z=0 T=sec 2>/dev/null | head -n 1 || true)"
fi
if [[ -z "$WID_SAMPLE" ]]; then
  say "Unable to generate WID sample; aborting."
  exit 1
fi
say "Using WID sample: $WID_SAMPLE"

run_case() {
  local name="$1"
  local dep="$2"
  shift 2
  local cmd_str="$*"
  local sig
  local otp_json
  local otp

  case "$dep" in
    openssl)
      if [[ "$OPENSSL_ED25519_OK" -ne 1 ]]; then
        mark_skip "$name" "requires OpenSSL Ed25519 pkeyutl"
        return 0
      fi
      ;;
    node)
      if [[ "$NODE_ED25519_OK" -ne 1 ]]; then
        mark_skip "$name" "requires Node Ed25519 backend support"
        return 0
      fi
      ;;
    none)
      ;;
    *)
      mark_fail "$name" "invalid dependency tag: $dep"
      return 0
      ;;
  esac

  if ! sig="$("$@" A=sign WID="$WID_SAMPLE" KEY="$PRIV_KEY" DATA="$DATA_FILE" 2>"$ERR_FILE" | tail -n 1)"; then
    if is_runtime_cache_error; then
      mark_skip "$name" "host runtime cache/lock permission issue"
      return 0
    fi
    mark_fail "$name" "sign failed: $(tr '\n' ' ' < "$ERR_FILE")"
    return 0
  fi
  sig="$(printf '%s' "$sig" | tr -d '[:space:]')"
  if [[ -z "${sig// }" ]]; then
    mark_fail "$name" "empty signature output"
    return 0
  fi

  if ! "$@" A=verify WID="$WID_SAMPLE" KEY="$PUB_KEY" SIG="$sig" DATA="$DATA_FILE" >"$OUT_FILE" 2>"$ERR_FILE"; then
    if is_runtime_cache_error; then
      mark_skip "$name" "host runtime cache/lock permission issue"
      return 0
    fi
    mark_fail "$name" "verify failed: $(tr '\n' ' ' < "$ERR_FILE")"
    return 0
  fi

  if "$@" A=verify WID="$WID_SAMPLE" KEY="$PUB_KEY" SIG="$sig" DATA="$DATA_BAD_FILE" >"$OUT_FILE" 2>"$ERR_FILE"; then
    mark_fail "$name" "verify unexpectedly accepted tampered data"
    return 0
  fi

  if ! otp_json="$("$@" A=w-otp MODE=gen KEY="smoke-secret" WID="$WID_SAMPLE" DIGITS=6 2>"$ERR_FILE")"; then
    if is_runtime_cache_error; then
      mark_skip "$name" "host runtime cache/lock permission issue"
      return 0
    fi
    mark_fail "$name" "w-otp gen failed: $(tr '\n' ' ' < "$ERR_FILE")"
    return 0
  fi
  otp="$(printf '%s' "$otp_json" | sed -nE 's/.*"otp":"([0-9]{4,10})".*/\1/p' | head -n1)"
  if [[ -z "$otp" ]]; then
    mark_fail "$name" "w-otp gen returned no otp"
    return 0
  fi

  if ! "$@" A=w-otp MODE=verify KEY="smoke-secret" WID="$WID_SAMPLE" CODE="$otp" DIGITS=6 >"$OUT_FILE" 2>"$ERR_FILE"; then
    if is_runtime_cache_error; then
      mark_skip "$name" "host runtime cache/lock permission issue"
      return 0
    fi
    mark_fail "$name" "w-otp verify failed: $(tr '\n' ' ' < "$ERR_FILE")"
    return 0
  fi

  if [[ "$otp" != "000000" ]] && "$@" A=w-otp MODE=verify KEY="smoke-secret" WID="$WID_SAMPLE" CODE="000000" DIGITS=6 >"$OUT_FILE" 2>"$ERR_FILE"; then
    mark_fail "$name" "w-otp verify unexpectedly accepted invalid code"
    return 0
  fi

  XV_NAMES+=("$name")
  XV_CMDS+=("$cmd_str")
  mark_pass "$name"
}

run_case "sh" openssl bash sh/wid I=sh

if [[ -n "$PYTHON_CMD" ]]; then
  run_case "python" none env PYTHONPATH=python "$PYTHON_CMD" -m wid
else
  mark_skip "python" "python>=3.10 not found"
fi

if [[ -f dist/cli.js ]]; then
  run_case "typescript" node node dist/cli.js
else
  mark_skip "typescript" "dist/cli.js missing"
fi

if [[ -x go/cmd/wid/wid ]]; then
  run_case "go" none go/cmd/wid/wid
else
  mark_skip "go" "go binary missing"
fi

if [[ -x target/debug/wid ]]; then
  run_case "rust" openssl target/debug/wid
else
  mark_skip "rust" "rust binary missing"
fi

if [[ -x c/.build/wid ]]; then
  run_case "c" openssl c/.build/wid
else
  mark_skip "c" "c binary missing"
fi


# Cross-implementation interop: a signature produced by ANY implementation must
# verify under EVERY implementation. The per-impl self-tests above only prove
# each impl agrees with itself, so they cannot catch one impl diverging from the
# others (e.g. a stale build or a canonical-message mismatch); this matrix does.
if [[ "${#XV_NAMES[@]}" -ge 2 ]]; then
  say "Cross-impl interop matrix: ${#XV_NAMES[@]} implementations (${XV_NAMES[*]})"
  xv_fail=0
  for i in "${!XV_NAMES[@]}"; do
    signer="${XV_NAMES[$i]}"
    scmd="${XV_CMDS[$i]}"
    if ! xsig="$($scmd A=sign WID="$WID_SAMPLE" KEY="$PRIV_KEY" DATA="$DATA_FILE" 2>/dev/null | tail -n 1)"; then
      mark_fail "xinterop:$signer(sign)" "signer failed to produce a signature"
      xv_fail=1
      continue
    fi
    xsig="$(printf '%s' "$xsig" | tr -d '[:space:]')"
    for j in "${!XV_NAMES[@]}"; do
      verifier="${XV_NAMES[$j]}"
      vcmd="${XV_CMDS[$j]}"
      if ! $vcmd A=verify WID="$WID_SAMPLE" KEY="$PUB_KEY" SIG="$xsig" DATA="$DATA_FILE" >/dev/null 2>&1; then
        mark_fail "xinterop:$signer->$verifier" "signature from $signer rejected by $verifier"
        xv_fail=1
      fi
    done
  done
  if [[ "$xv_fail" -eq 0 ]]; then
    mark_pass "cross-impl-interop(${#XV_NAMES[@]}x${#XV_NAMES[@]})"
  fi
fi

say "Summary: pass=$PASS_COUNT fail=$FAIL_COUNT skip=$SKIP_COUNT"
if [[ -n "$PASS_NAMES" ]]; then say "Passed: $PASS_NAMES"; fi
if [[ -n "$SKIP_NAMES" ]]; then say "Skipped: $SKIP_NAMES"; fi
if [[ -n "$FAIL_NAMES" ]]; then say "Failed: $FAIL_NAMES"; fi

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  exit 1
fi
if [[ "$STRICT" == "1" && "$SKIP_COUNT" -gt 0 ]]; then
  say "SMOKE_CRYPTO_STRICT=1 and skips detected."
  exit 1
fi

exit 0
