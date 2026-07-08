//! Shell completion scripts for bash, zsh, and fish.

use std::process;

pub(crate) fn print_completion(shell: &str) {
    match shell {
        "bash" => print!(
            r#"_wid_complete() {{
  local cur="${{COMP_WORDS[COMP_CWORD]}}"
  local cmds="next stream healthcheck validate parse help-actions bench selftest completion"
  if [[ "$cur" == *=* ]]; then
    local key="${{cur%%=*}}" val="${{cur#*=}}" vals=""
    case "$key" in
      A) vals="next stream healthcheck sign verify w-otp discover scaffold run start stop status logs saf saf-wid wir wism wihp wipr duplex help-actions" ;;
      T) vals="sec ms" ;;
      I) vals="auto sh bash" ;;
      E) vals="state stateless sql" ;;
      R) vals="auto mqtt ws redis null stdout" ;;
      M) vals="true false" ;;
    esac
    local IFS=$'\n'
    COMPREPLY=($(for v in $vals; do [[ "$v" == "$val"* ]] && printf '%s\n' "${{key}}=${{v}}"; done))
  else
    local kv="A= W= Z= T= N= L= D= I= E= R= M="
    COMPREPLY=($(compgen -W "$cmds $kv" -- "$cur"))
  fi
}}
complete -o nospace -F _wid_complete wid
"#
        ),
        "zsh" => print!(
            r#"#compdef wid
_wid_complete() {{
  local cur="${{words[-1]}}"
  local -a cmds=(next stream healthcheck validate parse help-actions bench selftest completion)
  if [[ "$cur" == *=* ]]; then
    local key="${{cur%%=*}}"
    local -a vals=()
    case "$key" in
      A) vals=(next stream healthcheck sign verify w-otp discover scaffold run start stop status logs saf saf-wid wir wism wihp wipr duplex help-actions) ;;
      T) vals=(sec ms) ;;
      I) vals=(auto sh bash) ;;
      E) vals=(state stateless sql) ;;
      R) vals=(auto mqtt ws redis null stdout) ;;
      M) vals=(true false) ;;
    esac
    compadd -P "${{key}}=" -- "${{vals[@]}}"
  else
    compadd -- "${{cmds[@]}}" A= W= Z= T= N= L= D= I= E= R= M=
  fi
}}
_wid_complete "$@"
"#
        ),
        "fish" => print!(
            r#"complete -c wid -e
complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a next -d 'Emit one WID'
complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a stream -d 'Stream WIDs continuously'
complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a healthcheck -d 'Generate and validate a sample WID'
complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a validate -d 'Validate a WID string'
complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a parse -d 'Parse a WID string'
complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a help-actions -d 'Show canonical action matrix'
complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a completion -d 'Print shell completion script'
complete -c wid -f -a 'A=next A=stream A=healthcheck A=sign A=verify A=w-otp A=start A=stop A=status A=logs A=help-actions' -d 'Action'
complete -c wid -f -a 'T=sec T=ms' -d 'Time unit'
complete -c wid -f -a 'I=auto I=sh I=bash' -d 'Input source'
complete -c wid -f -a 'E=state E=stateless E=sql' -d 'State mode'
complete -c wid -f -a 'R=auto R=mqtt R=ws R=redis R=null R=stdout' -d 'Transport'
complete -c wid -f -a 'M=true M=false' -d 'Milliseconds mode'
complete -c wid -f -a 'W=' -d 'Sequence width'
complete -c wid -f -a 'Z=' -d 'Padding length'
complete -c wid -f -a 'N=' -d 'Count'
complete -c wid -f -a 'L=' -d 'Interval seconds'
"#
        ),
        _ => {
            eprintln!("error: unknown shell '{shell}'. Use: wid completion bash|zsh|fish");
            process::exit(1);
        }
    }
}
