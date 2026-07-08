//! Canonical KEY=VALUE dispatch: parses the WALDIEZ grammar and routes
//! to the appropriate handler. This is the shared entry point used by
//! `sh/wid` (`I=auto`) and by the `__daemon` subprocess.

use super::args::{self, CanonOpts};
use super::commands;
use super::crypto;
use super::error::{CliError, usage};
use super::service;
use super::sql;

/// Split `E=<state_mode>[+<transport>]` or `E=<state_mode>[,<transport>]`
/// into its two parts. The transport default is taken from the canonical
/// `R=` key; the transport half is only used when `R=auto`.
pub(crate) fn parse_state_and_transport(c: &CanonOpts) -> (String, String) {
    let mut state_mode = c.e.clone();
    let mut transport = c.r.clone();
    if let Some((left, right)) = c.e.split_once('+') {
        state_mode = left.to_string();
        if transport == "auto" {
            transport = right.to_string();
        }
    } else if let Some((left, right)) = c.e.split_once(',') {
        state_mode = left.to_string();
        if transport == "auto" {
            transport = right.to_string();
        }
    }
    (state_mode, transport)
}

pub(crate) fn print_actions() {
    println!(
        "wid action matrix\n\n\
Core ID:\n  A=next | A=stream | A=healthcheck | A=sign | A=verify | A=w-otp\n\n\
Service lifecycle (native):\n  A=discover | A=scaffold | A=run | A=start | A=stop | A=status | A=logs\n\n\
Service modules (native):\n  A=saf      (alias: raf)\n  A=saf-wid  (aliases: waf, wraf)\n  A=wir      (alias: witr)\n  A=wism     (alias: wim)\n  A=wihp     (alias: wih)\n  A=wipr     (alias: wip)\n  A=duplex\n\n\
Help:\n  A=help-actions\n\n\
State mode:\n  E=state | E=stateless | E=sql"
    );
}

pub(crate) fn run_native_orchestration(c: &CanonOpts) -> Result<(), CliError> {
    match c.a.as_str() {
        "discover" => service::run_discover(),
        "scaffold" => service::run_scaffold(c),
        "run" => service::run_service_action(c, "run"),
        "start" => service::run_start(c),
        "stop" => service::run_stop(),
        "status" => service::run_status(),
        "logs" => service::run_logs(),
        "saf" => service::run_service_action(c, "saf"),
        "saf-wid" => service::run_service_action(c, "saf-wid"),
        "wir" => service::run_service_action(c, "wir"),
        "wism" => service::run_service_action(c, "wism"),
        "wihp" => service::run_service_action(c, "wihp"),
        "wipr" => service::run_service_action(c, "wipr"),
        "duplex" => service::run_service_action(c, "duplex"),
        _ => Err(usage(format!("unknown A={}", c.a))),
    }
}

pub(crate) fn run_canonical(args: &[String]) -> Result<(), CliError> {
    let c = args::parse_canonical(args).map_err(usage)?;

    if c.a == "help-actions" {
        print_actions();
        return Ok(());
    }
    if c.a == "sign" {
        return crypto::run_sign(&c);
    }
    if c.a == "verify" {
        return crypto::run_verify(&c);
    }
    if c.a == "w-otp" {
        return crypto::run_wotp(&c);
    }

    let (state_mode, _) = parse_state_and_transport(&c);
    if state_mode == "sql" && (c.a == "next" || c.a == "stream") {
        return match c.a.as_str() {
            "next" => sql::run_canonical_sql_next(&c),
            "stream" => sql::run_canonical_sql_stream(&c),
            _ => unreachable!(),
        };
    }

    match c.a.as_str() {
        "next" | "stream" | "healthcheck" => {
            let mut base = vec![
                "--kind".to_string(),
                "wid".to_string(),
                "--W".to_string(),
                c.w.to_string(),
                "--Z".to_string(),
                c.z.to_string(),
                "--time-unit".to_string(),
                c.t.as_str().to_string(),
            ];

            match c.a.as_str() {
                "next" => commands::run_next(&base),
                "stream" => {
                    base.push("--count".to_string());
                    base.push(c.n.to_string());
                    commands::run_stream(&base, if c.l_explicit { c.l as u64 } else { 0 })
                }
                "healthcheck" => {
                    base.push("--json".to_string());
                    commands::run_healthcheck(&base)
                }
                _ => unreachable!(),
            }
        }
        _ => run_native_orchestration(&c),
    }
}
