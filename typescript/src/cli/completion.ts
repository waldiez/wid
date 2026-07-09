
function printBashCompletion(): void {
  process.stdout.write(
    `_wid_complete() {
  local cur="\${COMP_WORDS[COMP_CWORD]}"
  local cmds="next stream healthcheck validate parse help-actions bench selftest completion"
  if [[ "$cur" == *=* ]]; then
    local key="\${cur%%=*}" val="\${cur#*=}" vals=""
    case "$key" in
      A) vals="next stream healthcheck sign verify w-otp help-actions" ;;
      T) vals="sec ms" ;;
      I) vals="auto sh bash" ;;
      E) vals="state stateless sql" ;;
      R) vals="auto null stdout" ;;
      M) vals="true false" ;;
    esac
    local IFS=$'\\n'
    COMPREPLY=(\$(for v in $vals; do [[ "$v" == "$val"* ]] && printf '%s\\n' "\${key}=\${v}"; done))
  else
    local kv="A= W= Z= T= N= L= D= I= E= R= M="
    COMPREPLY=(\$(compgen -W "$cmds $kv" -- "$cur"))
  fi
}
complete -o nospace -F _wid_complete wid-ts
`
  );
}

function printZshCompletion(): void {
  process.stdout.write(
    `#compdef wid-ts
_wid_complete() {
  local cur="\${words[-1]}"
  local -a cmds=(next stream healthcheck validate parse help-actions bench selftest completion)
  if [[ "$cur" == *=* ]]; then
    local key="\${cur%%=*}"
    local -a vals=()
    case "$key" in
      A) vals=(next stream healthcheck sign verify w-otp help-actions) ;;
      T) vals=(sec ms) ;;
      I) vals=(auto sh bash) ;;
      E) vals=(state stateless sql) ;;
      R) vals=(auto null stdout) ;;
      M) vals=(true false) ;;
    esac
    compadd -P "\${key}=" -- "\${vals[@]}"
  else
    compadd -- "\${cmds[@]}" A= W= Z= T= N= L= D= I= E= R= M=
  fi
}
_wid_complete "$@"
compdef _wid_complete wid-ts
`
  );
}

function printFishCompletion(): void {
  process.stdout.write(
    `complete -c wid-ts -e
complete -c wid-ts -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a next -d 'Emit one WID'
complete -c wid-ts -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a stream -d 'Stream WIDs continuously'
complete -c wid-ts -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a healthcheck -d 'Generate and validate a sample WID'
complete -c wid-ts -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a validate -d 'Validate a WID string'
complete -c wid-ts -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a parse -d 'Parse a WID string'
complete -c wid-ts -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a help-actions -d 'Show canonical action matrix'
complete -c wid-ts -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a completion -d 'Print shell completion script'
complete -c wid-ts -f -a 'A=next A=stream A=healthcheck A=sign A=verify A=w-otp A=help-actions' -d 'Action'
complete -c wid-ts -f -a 'T=sec T=ms' -d 'Time unit'
complete -c wid-ts -f -a 'I=auto I=sh I=bash' -d 'Input source'
complete -c wid-ts -f -a 'E=state E=stateless E=sql' -d 'State mode'
complete -c wid-ts -f -a 'R=auto R=null R=stdout' -d 'Transport'
complete -c wid-ts -f -a 'M=true M=false' -d 'Milliseconds mode'
complete -c wid-ts -f -a 'W=' -d 'Sequence width'
complete -c wid-ts -f -a 'Z=' -d 'Padding length'
complete -c wid-ts -f -a 'N=' -d 'Count'
complete -c wid-ts -f -a 'L=' -d 'Interval seconds'
`
  );
}

export function printCompletion(shell: string): void {
  if (shell === "bash") {
    printBashCompletion();
  } else if (shell === "zsh") {
    printZshCompletion();
  } else if (shell === "fish") {
    printFishCompletion();
  } else {
    process.stderr.write(
      `error: unknown shell '${shell}'. Use: wid completion bash|zsh|fish\n`
    );
    process.exit(1);
  }
}
