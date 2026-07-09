"""Shell completion scripts (bash/zsh/fish) for the wid CLI."""

from __future__ import annotations

import sys


def _fish_completion() -> str:
    """Build the fish completion."""
    guard = (
        "not __fish_seen_subcommand_from next stream healthcheck validate"
        + " parse help-actions bench selftest completion"
    )
    subcommands = (
        ("next", "Emit one WID"),
        ("stream", "Stream WIDs continuously"),
        ("healthcheck", "Generate and validate a sample WID"),
        ("validate", "Validate a WID string"),
        ("parse", "Parse a WID string"),
        ("help-actions", "Show canonical action matrix"),
        ("completion", "Print shell completion script"),
    )
    lines = ["complete -c wid -e"]
    lines += [
        f"complete -c wid -f -n '{guard}' -a {cmd} -d '{desc}'"
        for cmd, desc in subcommands
    ]
    lines += [
        "complete -c wid -f -a 'A=next A=stream A=healthcheck A=sign"
        + " A=verify A=w-otp A=help-actions' -d 'Action'",
        "complete -c wid -f -a 'T=sec T=ms' -d 'Time unit'",
        "complete -c wid -f -a 'I=auto I=sh I=bash' -d 'Input source'",
        "complete -c wid -f -a 'E=state E=stateless E=sql' -d 'State mode'",
        "complete -c wid -f -a 'R=auto R=null R=stdout' -d 'Transport'",
        "complete -c wid -f -a 'M=true M=false' -d 'Milliseconds mode'",
        "complete -c wid -f -a 'W=' -d 'Sequence width'",
        "complete -c wid -f -a 'Z=' -d 'Padding length'",
        "complete -c wid -f -a 'N=' -d 'Count'",
        "complete -c wid -f -a 'L=' -d 'Interval seconds'",
    ]
    return "\n".join(lines)


def _zsh_completion() -> str:
    """Build the zsh completion."""
    # fmt: off
    return r"""#compdef wid
_wid_complete() {
  local cur="${words[-1]}"
  local -a cmds=(
    next stream healthcheck validate parse
    help-actions bench selftest completion
  )
  if [[ "$cur" == *=* ]]; then
    local key="${cur%%=*}"
    local -a vals=()
    case "$key" in
      A) vals=(next stream healthcheck sign verify w-otp help-actions) ;;
      T) vals=(sec ms) ;;
      I) vals=(auto sh bash) ;;
      E) vals=(state stateless sql) ;;
      R) vals=(auto null stdout) ;;
      M) vals=(true false) ;;
    esac
    compadd -P "${key}=" -- "${vals[@]}"
  else
    compadd -- "${cmds[@]}" A= W= Z= T= N= L= D= I= E= R= M=
  fi
}
_wid_complete """ + '"$@"'


# fmt: on


def _bash_completion() -> str:
    return r"""_wid_complete() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local cmds="next stream healthcheck validate parse help-actions bench \
selftest completion"
  if [[ "$cur" == *=* ]]; then
    local key="${cur%%=*}" val="${cur#*=}" vals=""
    case "$key" in
      A) vals="next stream healthcheck sign verify w-otp help-actions" ;;
      T) vals="sec ms" ;;
      I) vals="auto sh bash" ;;
      E) vals="state stateless sql" ;;
      R) vals="auto null stdout" ;;
      M) vals="true false" ;;
    esac
    local IFS=$'\n'
    COMPREPLY=($(for v in $vals; do
      [[ "$v" == "$val"* ]] && printf '%s\n' "${key}=${v}"
    done))
  else
    local kv="A= W= Z= T= N= L= D= I= E= R= M="
    COMPREPLY=($(compgen -W "$cmds $kv" -- "$cur"))
  fi
}
complete -o nospace -F _wid_complete wid"""


def print_completion(shell: str) -> None:
    """Print a bash/zsh/fish completion script for the wid CLI.

    Only values the CLI actually accepts are advertised: service actions
    and broker transports are Rust-only and rejected here.
    """
    if shell == "bash":
        print(_bash_completion())
    elif shell == "zsh":
        print(_zsh_completion())
    elif shell == "fish":
        print(_fish_completion())
    else:
        print(
            f"error: unknown shell '{shell}'. Use: wid completion bash|zsh|fish",
            file=sys.stderr,
        )
        sys.exit(1)
