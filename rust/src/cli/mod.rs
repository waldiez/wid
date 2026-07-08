//! CLI module: argument parsing, command dispatch, service orchestration,
//! cryptographic actions, SQL persistence, and shell completion.

pub(crate) mod args;
pub(crate) mod canonical;
pub(crate) mod commands;
pub(crate) mod completion;
pub(crate) mod crypto;
pub(crate) mod error;
pub(crate) mod service;
pub(crate) mod sql;

pub(crate) use canonical::run_canonical;
pub(crate) use commands::{
    run_bench, run_healthcheck, run_next, run_parse, run_selftest, run_stream, run_validate,
};
pub(crate) use completion::print_completion;
pub(crate) use error::exit_on_error;
