//! Service-layer orchestration: daemon lifecycle (start/stop/status/logs),
//! scaffold, discover, and the per-tick service actions (saf, saf-wid, wir,
//! wism, wihp, wipr, duplex, run).
//!
//! This module is Rust-only; the other five implementations reject service
//! actions (see spec/SERVICES.md).

use std::env;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::Duration;

use serde_json::json;
use wid::WidGen;

use super::args::{CanonOpts, is_local_service_transport};
use super::error::{CliError, fail, usage};

/// Base directory for resolving relative `D=` / data / runtime paths.
///
/// Data and runtime files are resolved relative to the current working
/// directory. An earlier revision walked parent directories looking for an
/// `implementations/` + `README.md` repo-root marker, but that marker never
/// matched this repository's layout (top-level `rust/`, `c/`, … — there is no
/// `implementations/` directory) and always fell through to the cwd, so the
/// walk was dead code and has been removed.
pub(crate) fn workspace_root() -> PathBuf {
    env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

pub(crate) fn resolve_data_dir(root: &Path, d: &str) -> PathBuf {
    if d.is_empty() {
        root.join(".local").join("services")
    } else {
        let p = PathBuf::from(d);
        if p.is_absolute() { p } else { root.join(p) }
    }
}

/// Runtime dir for the daemon's PID/log files. Anchored to a per-user
/// location so `start` and `stop` manage the same daemon regardless of the
/// working directory they run from: `$WID_RUNTIME_DIR` >
/// `$XDG_STATE_HOME/wid/rust` > `$HOME/.local/state/wid/rust`, falling back
/// to `<cwd>/.local/wid/rust` only when no HOME is available.
pub(crate) fn runtime_dir(root: &Path) -> PathBuf {
    if let Ok(d) = env::var("WID_RUNTIME_DIR")
        && !d.is_empty()
    {
        return PathBuf::from(d);
    }
    if let Ok(d) = env::var("XDG_STATE_HOME")
        && !d.is_empty()
    {
        return PathBuf::from(d).join("wid").join("rust");
    }
    if let Ok(h) = env::var("HOME")
        && !h.is_empty()
    {
        return PathBuf::from(h)
            .join(".local")
            .join("state")
            .join("wid")
            .join("rust");
    }
    root.join(".local").join("wid").join("rust")
}

pub(crate) fn runtime_pid_file(root: &Path) -> PathBuf {
    runtime_dir(root).join("service.pid")
}

pub(crate) fn runtime_log_file(root: &Path) -> PathBuf {
    runtime_dir(root).join("service.log")
}

pub(crate) fn parse_pid(path: &Path) -> Option<i32> {
    let content = fs::read_to_string(path).ok()?;
    content.trim().parse::<i32>().ok()
}

#[cfg(unix)]
fn pid_alive(pid: i32) -> bool {
    if pid <= 0 {
        return false;
    }
    // Signal 0 probes existence; EPERM means it exists but isn't ours.
    let rc = unsafe { libc::kill(pid, 0) };
    rc == 0 || io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
}

#[cfg(not(unix))]
fn pid_alive(_pid: i32) -> bool {
    false
}

/// Refuse to signal a PID whose /proc cmdline no longer looks like our
/// daemon — after a crash or reboot the pid file can point at a recycled
/// PID belonging to an unrelated process. Platforms without /proc cannot
/// verify and trust the pid file as before.
fn pid_is_wid_daemon(pid: i32) -> bool {
    match fs::read(format!("/proc/{pid}/cmdline")) {
        Ok(bytes) => String::from_utf8_lossy(&bytes).contains("__daemon"),
        Err(_) => true,
    }
}

#[cfg(unix)]
fn kill_pid(pid: i32) -> bool {
    if pid <= 0 {
        return false;
    }
    if unsafe { libc::kill(pid, libc::SIGTERM) } != 0 {
        return false;
    }
    // Give it up to ~2s to exit cleanly before escalating.
    for _ in 0..40 {
        if !pid_alive(pid) {
            return true;
        }
        thread::sleep(Duration::from_millis(50));
    }
    let rc = unsafe { libc::kill(pid, libc::SIGKILL) };
    rc == 0 || !pid_alive(pid)
}

#[cfg(not(unix))]
fn kill_pid(_pid: i32) -> bool {
    false
}

pub(crate) fn run_service_action(c: &CanonOpts, action: &str) -> Result<(), CliError> {
    let root = workspace_root();
    let data_dir = resolve_data_dir(&root, &c.d);
    fs::create_dir_all(&data_dir).map_err(|e| fail(format!("failed to create data dir: {e}")))?;
    let (_state_mode, mut transport) = super::canonical::parse_state_and_transport(c);
    let log_level = env::var("LOG_LEVEL").unwrap_or_else(|_| "INFO".to_string());

    if action == "saf-wid"
        || action == "wir"
        || action == "wism"
        || action == "wihp"
        || action == "wipr"
        || action == "duplex"
    {
        if transport == "auto" {
            transport = "mqtt".to_string();
        }
        if !is_local_service_transport(&transport) {
            return Err(usage(format!(
                "invalid transport for A={action}: {transport}"
            )));
        }
    }

    let mut wid_gen =
        WidGen::new_with_time_unit(c.w, c.z, c.t).map_err(|e| usage(e.to_string()))?;
    let iterations = if c.n == 0 { usize::MAX } else { c.n };
    let mut i = 0usize;

    while i < iterations {
        let tick = i + 1;
        let payload = match action {
            "saf" => json!({
                "impl":"rust","action":"saf","tick":tick,"transport":transport,
                "interval":c.l,"log_level":log_level,"data_dir":data_dir
            }),
            "saf-wid" => json!({
                "impl":"rust","action":"saf-wid","tick":tick,"transport":transport,
                "wid":wid_gen.next_wid(),"W":c.w,"Z":c.z,"time_unit":c.t.as_str(),
                "interval":c.l,"log_level":log_level,"data_dir":data_dir
            }),
            "wir" => json!({
                "impl":"rust","action":"wir","tick":tick,"transport":transport,
                "interval":c.l,"log_level":log_level,"data_dir":data_dir
            }),
            "wism" => json!({
                "impl":"rust","action":"wism","tick":tick,"transport":transport,
                "wid":wid_gen.next_wid(),"W":c.w,"Z":c.z,"interval":c.l,"data_dir":data_dir
            }),
            "wihp" => json!({
                "impl":"rust","action":"wihp","tick":tick,"transport":transport,
                "wid":wid_gen.next_wid(),"W":c.w,"Z":c.z,"interval":c.l,"data_dir":data_dir
            }),
            "wipr" => json!({
                "impl":"rust","action":"wipr","tick":tick,"transport":transport,
                "wid":wid_gen.next_wid(),"W":c.w,"Z":c.z,"interval":c.l,"data_dir":data_dir
            }),
            "duplex" => {
                let mut b_transport = "ws".to_string();
                if c.i != "auto" && is_local_service_transport(&c.i) {
                    b_transport = c.i.clone();
                }
                json!({
                    "impl":"rust","action":"duplex","tick":tick,
                    "a_transport":transport,"b_transport":b_transport,
                    "interval":c.l,"data_dir":data_dir
                })
            }
            "run" => json!({
                "impl":"rust","action":"run","tick":tick,"transport":transport,
                "interval":c.l,"data_dir":data_dir
            }),
            _ => return Err(usage(format!("unknown service action: {action}"))),
        };

        if transport != "null" {
            println!(
                "{}",
                serde_json::to_string(&payload).map_err(|e| fail(e.to_string()))?
            );
            io::stdout().flush().map_err(|e| fail(e.to_string()))?;
        }

        i += 1;
        if i < iterations && c.l > 0 {
            thread::sleep(Duration::from_secs(c.l as u64));
        }
    }

    Ok(())
}

pub(crate) fn run_discover() -> Result<(), CliError> {
    let payload = json!({
        "impl":"rust",
        "orchestration":"native",
        "actions":["discover","scaffold","run","start","stop","status","logs","saf","saf-wid","wir","wism","wihp","wipr","duplex"],
        "transports":["auto","mqtt","ws","redis","null","stdout"]
    });
    println!(
        "{}",
        serde_json::to_string(&payload).map_err(|e| fail(e.to_string()))?
    );
    Ok(())
}

pub(crate) fn run_scaffold(c: &CanonOpts) -> Result<(), CliError> {
    if c.d.is_empty() {
        return Err(usage("D=<name> required for A=scaffold"));
    }
    let root = workspace_root();
    let target = resolve_data_dir(&root, &c.d);
    fs::create_dir_all(target.join("state"))
        .map_err(|e| fail(format!("failed to scaffold state dir: {e}")))?;
    fs::create_dir_all(target.join("logs"))
        .map_err(|e| fail(format!("failed to scaffold logs dir: {e}")))?;
    println!("scaffolded {}", target.display());
    Ok(())
}

pub(crate) fn run_status() -> Result<(), CliError> {
    let root = workspace_root();
    let pid_file = runtime_pid_file(&root);
    let log_file = runtime_log_file(&root);
    if let Some(pid) = parse_pid(&pid_file)
        && pid_alive(pid)
        && pid_is_wid_daemon(pid)
    {
        println!(
            "wid-rust status=running pid={} log={}",
            pid,
            log_file.display()
        );
        return Ok(());
    }
    println!("wid-rust status=stopped");
    Ok(())
}

pub(crate) fn run_logs() -> Result<(), CliError> {
    let root = workspace_root();
    let log_file = runtime_log_file(&root);
    match fs::read_to_string(&log_file) {
        Ok(content) => {
            print!("{content}");
            Ok(())
        }
        Err(e) if e.kind() == io::ErrorKind::NotFound => {
            println!("wid-rust logs: empty");
            Ok(())
        }
        Err(e) => Err(fail(format!("failed to read logs: {e}"))),
    }
}

pub(crate) fn run_stop() -> Result<(), CliError> {
    let root = workspace_root();
    let pid_file = runtime_pid_file(&root);
    let Some(pid) = parse_pid(&pid_file) else {
        println!("wid-rust stop: not running");
        return Ok(());
    };
    if !pid_alive(pid) {
        let _ = fs::remove_file(&pid_file);
        println!("wid-rust stop: not running");
        return Ok(());
    }
    if !pid_is_wid_daemon(pid) {
        let _ = fs::remove_file(&pid_file);
        println!("wid-rust stop: stale pid file (pid={pid} is another process); removed");
        return Ok(());
    }
    if kill_pid(pid) {
        let _ = fs::remove_file(&pid_file);
        println!("wid-rust stop: stopped pid={pid}");
        Ok(())
    } else {
        Err(fail(format!("failed to stop pid={pid}")))
    }
}

pub(crate) fn daemon_kv_args(c: &CanonOpts, action: &str) -> Vec<String> {
    vec![
        format!("A={action}"),
        format!("W={}", c.w),
        format!("L={}", c.l),
        format!("D={}", if c.d.is_empty() { "#" } else { &c.d }),
        format!("I={}", c.i),
        format!("E={}", c.e),
        format!("Z={}", c.z),
        format!("T={}", c.t.as_str()),
        format!("R={}", c.r),
        format!("M={}", if c.m { "true" } else { "false" }),
        format!("N={}", c.n),
    ]
}

pub(crate) fn run_start(c: &CanonOpts) -> Result<(), CliError> {
    let root = workspace_root();
    let runtime = runtime_dir(&root);
    fs::create_dir_all(&runtime).map_err(|e| fail(format!("failed to create runtime dir: {e}")))?;
    let pid_file = runtime_pid_file(&root);
    let log_file = runtime_log_file(&root);

    // Claim the pid file atomically (create_new) so two concurrent starts
    // cannot both pass a check-then-write race. A stale file left by a dead
    // daemon is removed and the claim retried once.
    let mut claimed = None;
    for _ in 0..2 {
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&pid_file)
        {
            Ok(f) => {
                claimed = Some(f);
                break;
            }
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                if let Some(pid) = parse_pid(&pid_file)
                    && pid_alive(pid)
                    && pid_is_wid_daemon(pid)
                {
                    println!(
                        "wid-rust start: already-running pid={} log={}",
                        pid,
                        log_file.display()
                    );
                    return Ok(());
                }
                let _ = fs::remove_file(&pid_file);
            }
            Err(e) => return Err(fail(format!("failed to create pid file: {e}"))),
        }
    }
    let Some(mut pid_handle) = claimed else {
        return Err(fail("failed to claim pid file (concurrent start?)"));
    };

    let log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_file)
        .map_err(|e| fail(format!("failed to open log file: {e}")))?;
    let log_err = log
        .try_clone()
        .map_err(|e| fail(format!("failed to clone log fd: {e}")))?;

    let exe =
        env::current_exe().map_err(|e| fail(format!("failed to resolve current exe: {e}")))?;
    let mut cmd = Command::new(exe);
    cmd.arg("__daemon")
        .args(daemon_kv_args(c, "run"))
        .stdin(Stdio::null())
        .stdout(Stdio::from(log))
        .stderr(Stdio::from(log_err));
    // Detach into a new session so the daemon survives the terminal/session
    // that launched it (it would otherwise stay in the launching process
    // group and die with it).
    #[cfg(unix)]
    unsafe {
        use std::os::unix::process::CommandExt;
        cmd.pre_exec(|| {
            if libc::setsid() == -1 {
                return Err(io::Error::last_os_error());
            }
            Ok(())
        });
    }
    let child = match cmd.spawn() {
        Ok(child) => child,
        Err(e) => {
            let _ = fs::remove_file(&pid_file);
            return Err(fail(format!("failed to start daemon: {e}")));
        }
    };

    if let Err(e) = pid_handle.write_all(child.id().to_string().as_bytes()) {
        let _ = fs::remove_file(&pid_file);
        return Err(fail(format!("failed to write pid file: {e}")));
    }
    println!(
        "wid-rust start: started pid={} log={}",
        child.id(),
        log_file.display()
    );
    Ok(())
}
