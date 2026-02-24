#!/usr/bin/env sh
# All external commands use absolute paths or are replaced with shell built-ins
# because PATH may be completely stripped when this script runs under act.
set -eu

# Append a directory to $GITHUB_PATH for subsequent workflow steps.
_add_to_github_path() {
  if [ -n "${GITHUB_PATH:-}" ] && [ -d "$1" ]; then
    printf '%s\n' "$1" >> "$GITHUB_PATH"
    echo "  -> added $1 to GITHUB_PATH"
  fi
}

# ── bash ──────────────────────────────────────────────────────────────────────
if command -v bash >/dev/null 2>&1; then
  echo "bash already present: $(command -v bash)"
else
  _bash=""
  for _b in /bin/bash /usr/bin/bash /usr/local/bin/bash; do
    if [ -x "$_b" ]; then _bash="$_b"; break; fi
  done
  if [ -n "$_bash" ]; then
    echo "bash found at $_bash (not in PATH)"
    _add_to_github_path "${_bash%/*}"       # shell built-in; no dirname needed
  elif [ -x /usr/bin/apt-get ]; then
    /usr/bin/apt-get update -qq && /usr/bin/apt-get install -y bash
    _add_to_github_path /bin
  elif command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y bash
    _add_to_github_path /bin
  elif [ -x /sbin/apk ]; then
    /sbin/apk add --no-cache bash
    _add_to_github_path /bin
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache bash
    _add_to_github_path /bin
  else
    echo "Could not install bash: no apt-get/apk found" >&2
    exit 1
  fi
fi

# ── node ──────────────────────────────────────────────────────────────────────
# act builds the PATH for action steps (docker exec [node ...]) from the
# workflow environment, which excludes /opt/acttoolcache.  We find node via
# shell globs (no find/sort/tail needed) and inject its directory via
# $GITHUB_PATH so all subsequent steps — shell and JS actions alike — work.
if command -v node >/dev/null 2>&1; then
  echo "node already present: $(command -v node)"
else
  _node=""

  # Standard locations
  for _n in /usr/bin/node /usr/local/bin/node /usr/bin/nodejs /usr/local/bin/nodejs; do
    if [ -x "$_n" ]; then _node="$_n"; break; fi
  done

  # act toolcache: /opt/acttoolcache/node/<version>/<arch>/bin/node
  if [ -z "$_node" ]; then
    for _base in /opt/acttoolcache/node /opt/hostedtoolcache/node; do
      for _n in "$_base"/*/*/bin/node; do
        if [ -x "$_n" ]; then _node="$_n"; break 2; fi
      done
    done
  fi

  # nvm: /root/.nvm/versions/node/<version>/bin/node
  if [ -z "$_node" ]; then
    for _base in /usr/local/nvm/versions/node /root/.nvm/versions/node /home/runner/.nvm/versions/node; do
      for _n in "$_base"/*/bin/node; do
        if [ -x "$_n" ]; then _node="$_n"; break 2; fi
      done
    done
  fi

  if [ -n "$_node" ]; then
    echo "node found at $_node (not in PATH)"
    _add_to_github_path "${_node%/*}"       # shell built-in; no dirname needed
  else
    echo "WARNING: node not found; JS-based GitHub Actions may fail" >&2
  fi
fi
