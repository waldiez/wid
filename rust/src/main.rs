//! `wid` CLI binary: canonical KEY=VALUE and flag-mode front end over the
//! library, plus the Rust-only service layer (see `spec/SERVICES.md`).

mod cli;

use std::env;
use std::process;

fn print_help() {
    eprintln!(
        "wid - WID/HLC-WID generator CLI\n\n\
Usage:\n  wid next [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms]\n  wid stream [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--count <n>]\n  wid validate <id> [--kind wid|hlc] [--W <n>] [--Z <n>] [--time-unit sec|ms]\n  wid parse <id> [--kind wid|hlc] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--json]\n  wid healthcheck [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--json]\n  wid bench [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--count <n>]\n\n\
Canonical mode:\n  wid W=# A=# L=# D=# I=# E=# Z=# T=sec|ms R=auto|mqtt|ws|redis|null|stdout N=#\n  wid A=w-otp MODE=gen|verify KEY=<secret|path> [WID=<wid>] [CODE=<otp>] [DIGITS=6] [MAX_AGE_SEC=0] [MAX_FUTURE_SEC=5]\n  For A=stream: N=0 means infinite stream\n  E supports: state | stateless | sql\n"
    );
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();

    if args.is_empty() {
        print_help();
        process::exit(2);
    }

    // Daemon subprocess: re-invoked by `A=start` with `__daemon` as argv[0].
    if args[0] == "__daemon" {
        let daemon_args: Vec<String> = args[1..].to_vec();
        cli::exit_on_error(cli::run_canonical(&daemon_args));
        return;
    }

    // Canonical KEY=VALUE mode (any arg contains '=').
    if args.iter().any(|a| a.contains('=')) {
        cli::exit_on_error(cli::run_canonical(&args));
        return;
    }

    if args[0] == "-h" || args[0] == "--help" || args[0] == "help" {
        print_help();
        return;
    }

    if args[0] == "help-actions" {
        cli::canonical::print_actions();
        return;
    }

    let cmd = args[0].as_str();
    let rest = &args[1..];

    if cmd == "completion" {
        let shell = rest.first().map(|s| s.as_str()).unwrap_or("");
        if shell.is_empty() {
            eprintln!("usage: wid completion bash|zsh|fish");
            process::exit(1);
        }
        cli::print_completion(shell);
        return;
    }

    let res = match cmd {
        "next" => cli::run_next(rest),
        "stream" => cli::run_stream(rest, 0),
        "healthcheck" => cli::run_healthcheck(rest),
        "validate" => cli::run_validate(rest),
        "parse" => cli::run_parse(rest),
        "bench" => cli::run_bench(rest),
        "selftest" => cli::run_selftest(),
        _ => {
            eprintln!("error: unknown command: {cmd}");
            process::exit(2);
        }
    };

    cli::exit_on_error(res);
}
