//! CLI error types and exit helpers — the shared cross-language contract
//! (spec/quick-usage.md "Exit codes"): usage errors exit 2, operational
//! failures exit 1.

use std::process;

/// CLI error carrying its exit code.
pub(crate) enum CliError {
    /// Malformed invocation: unknown command/flag/key/action, missing
    /// required value or argument, out-of-range parameter. Exit 2.
    Usage(String),
    /// The operation itself failed: invalid id, verification failure,
    /// missing/unreadable key or data files, runtime errors. Exit 1.
    Fail(String),
}

impl CliError {
    pub(crate) fn exit_code(&self) -> i32 {
        match self {
            CliError::Usage(_) => 2,
            CliError::Fail(_) => 1,
        }
    }

    pub(crate) fn message(&self) -> &str {
        match self {
            CliError::Usage(m) | CliError::Fail(m) => m,
        }
    }
}

pub(crate) fn usage(msg: impl Into<String>) -> CliError {
    CliError::Usage(msg.into())
}

pub(crate) fn fail(msg: impl Into<String>) -> CliError {
    CliError::Fail(msg.into())
}

pub(crate) fn exit_on_error(res: Result<(), CliError>) {
    if let Err(err) = res {
        eprintln!("error: {}", err.message());
        process::exit(err.exit_code());
    }
}
