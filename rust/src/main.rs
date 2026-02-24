use std::env;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::{self, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::json;
use wid::{
    HLCWidGen, TimeUnit, WidGen, parse_hlc_wid_with_unit, parse_wid_with_unit,
    validate_hlc_wid_with_unit, validate_wid_with_unit,
};

#[derive(Debug, Clone)]
struct ValidateOpts {
    kind: String,
    w: usize,
    z: usize,
    time_unit: TimeUnit,
}

impl Default for ValidateOpts {
    fn default() -> Self {
        Self {
            kind: "wid".to_string(),
            w: 4,
            z: 6,
            time_unit: TimeUnit::Sec,
        }
    }
}

#[derive(Debug, Clone)]
struct EmitOpts {
    kind: String,
    node: String,
    w: usize,
    z: usize,
    time_unit: TimeUnit,
    count: usize,
}

#[derive(Debug, Clone)]
struct CanonOpts {
    a: String,
    w: usize,
    l: usize,
    d: String,
    i: String,
    e: String,
    z: usize,
    t: TimeUnit,
    r: String,
    m: bool,
    n: usize,
    wid: String,
    key: String,
    sig: String,
    data: String,
    out: String,
    mode: String,
    code: String,
    digits: usize,
    max_age_sec: u64,
    max_future_sec: u64,
}

fn default_node() -> String {
    env::var("NODE").unwrap_or_else(|_| "rust".to_string())
}

fn print_help() {
    eprintln!(
        "wid - WID/HLC-WID generator CLI\n\n\
Usage:\n  wid next [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms]\n  wid stream [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--count <n>]\n  wid validate <id> [--kind wid|hlc] [--W <n>] [--Z <n>] [--time-unit sec|ms]\n  wid parse <id> [--kind wid|hlc] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--json]\n  wid healthcheck [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--json]\n  wid bench [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--count <n>]\n\
Canonical mode:\n  wid W=# A=# L=# D=# I=# E=# Z=# T=sec|ms R=auto|mqtt|ws|redis|null|stdout N=#\n  wid A=w-otp MODE=gen|verify KEY=<secret|path> [WID=<wid>] [CODE=<otp>] [DIGITS=6] [MAX_AGE_SEC=0] [MAX_FUTURE_SEC=5]\n  For A=stream: N=0 means infinite stream\n  E supports: state | stateless | sql\n"
    );
}

fn print_actions() {
    println!(
        "wid action matrix\n\n\
Core ID:\n  A=next | A=stream | A=healthcheck | A=sign | A=verify | A=w-otp\n\n\
Service lifecycle (native):\n  A=discover | A=scaffold | A=run | A=start | A=stop | A=status | A=logs\n\n\
Service modules (native):\n  A=saf      (alias: raf)\n  A=saf-wid  (aliases: waf, wraf)\n  A=wir      (alias: witr)\n  A=wism     (alias: wim)\n  A=wihp     (alias: wih)\n  A=wipr     (alias: wip)\n  A=duplex\n\n\
Help:\n  A=help-actions\n\n\
State mode:\n  E=state | E=stateless | E=sql"
    );
}

fn parse_time_unit(s: &str) -> Result<TimeUnit, String> {
    TimeUnit::parse(s).ok_or_else(|| "time-unit must be sec or ms".to_string())
}

fn parse_validate_flags(args: &[String]) -> Result<ValidateOpts, String> {
    let mut opts = ValidateOpts::default();
    let mut i = 0;

    while i < args.len() {
        match args[i].as_str() {
            "--kind" => {
                if i + 1 >= args.len() {
                    return Err("missing value for --kind".to_string());
                }
                opts.kind = args[i + 1].clone();
                i += 2;
            }
            "--W" => {
                if i + 1 >= args.len() {
                    return Err("missing value for --W".to_string());
                }
                opts.w = args[i + 1]
                    .parse::<usize>()
                    .map_err(|_| "invalid integer for --W".to_string())?;
                i += 2;
            }
            "--Z" => {
                if i + 1 >= args.len() {
                    return Err("missing value for --Z".to_string());
                }
                opts.z = args[i + 1]
                    .parse::<usize>()
                    .map_err(|_| "invalid integer for --Z".to_string())?;
                i += 2;
            }
            "--time-unit" | "--T" => {
                if i + 1 >= args.len() {
                    return Err("missing value for --time-unit".to_string());
                }
                opts.time_unit = parse_time_unit(&args[i + 1])?;
                i += 2;
            }
            _ => return Err(format!("unknown flag: {}", args[i])),
        }
    }

    match opts.kind.as_str() {
        "wid" | "hlc" => Ok(opts),
        _ => Err("--kind must be one of: wid, hlc".to_string()),
    }
}

fn parse_emit_flags(args: &[String], allow_count: bool) -> Result<EmitOpts, String> {
    let mut opts = EmitOpts {
        kind: "wid".to_string(),
        node: default_node(),
        w: 4,
        z: 6,
        time_unit: TimeUnit::Sec,
        count: 0,
    };

    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--kind" => {
                if i + 1 >= args.len() {
                    return Err("missing value for --kind".to_string());
                }
                opts.kind = args[i + 1].clone();
                i += 2;
            }
            "--node" => {
                if i + 1 >= args.len() {
                    return Err("missing value for --node".to_string());
                }
                opts.node = args[i + 1].clone();
                i += 2;
            }
            "--W" => {
                if i + 1 >= args.len() {
                    return Err("missing value for --W".to_string());
                }
                opts.w = args[i + 1]
                    .parse::<usize>()
                    .map_err(|_| "invalid integer for --W".to_string())?;
                i += 2;
            }
            "--Z" => {
                if i + 1 >= args.len() {
                    return Err("missing value for --Z".to_string());
                }
                opts.z = args[i + 1]
                    .parse::<usize>()
                    .map_err(|_| "invalid integer for --Z".to_string())?;
                i += 2;
            }
            "--time-unit" | "--T" => {
                if i + 1 >= args.len() {
                    return Err("missing value for --time-unit".to_string());
                }
                opts.time_unit = parse_time_unit(&args[i + 1])?;
                i += 2;
            }
            "--count" if allow_count => {
                if i + 1 >= args.len() {
                    return Err("missing value for --count".to_string());
                }
                opts.count = args[i + 1]
                    .parse::<usize>()
                    .map_err(|_| "invalid integer for --count".to_string())?;
                i += 2;
            }
            _ => return Err(format!("unknown flag: {}", args[i])),
        }
    }

    match opts.kind.as_str() {
        "wid" | "hlc" => Ok(opts),
        _ => Err("--kind must be one of: wid, hlc".to_string()),
    }
}

fn run_next(args: &[String]) -> Result<(), String> {
    let opts = parse_emit_flags(args, false)?;

    if opts.kind == "wid" {
        let mut generator = WidGen::new_with_time_unit(opts.w, opts.z, None, opts.time_unit)
            .map_err(|e| e.to_string())?;
        println!("{}", generator.next_wid());
    } else {
        let mut generator =
            HLCWidGen::new_with_time_unit(opts.node, opts.w, opts.z, opts.time_unit)
                .map_err(|e| e.to_string())?;
        println!("{}", generator.next_hlc_wid());
    }

    Ok(())
}

fn run_stream(args: &[String]) -> Result<(), String> {
    let opts = parse_emit_flags(args, true)?;
    let mut emitted = 0usize;

    if opts.kind == "wid" {
        let mut generator = WidGen::new_with_time_unit(opts.w, opts.z, None, opts.time_unit)
            .map_err(|e| e.to_string())?;
        loop {
            if opts.count > 0 && emitted >= opts.count {
                break;
            }
            println!("{}", generator.next_wid());
            io::stdout().flush().map_err(|e| e.to_string())?;
            emitted += 1;
        }
    } else {
        let mut generator =
            HLCWidGen::new_with_time_unit(opts.node, opts.w, opts.z, opts.time_unit)
                .map_err(|e| e.to_string())?;
        loop {
            if opts.count > 0 && emitted >= opts.count {
                break;
            }
            println!("{}", generator.next_hlc_wid());
            io::stdout().flush().map_err(|e| e.to_string())?;
            emitted += 1;
        }
    }

    Ok(())
}

fn run_healthcheck(args: &[String]) -> Result<(), String> {
    let mut json_mode = false;
    let mut tail: Vec<String> = Vec::new();
    for arg in args {
        if arg == "--json" {
            json_mode = true;
        } else {
            tail.push(arg.clone());
        }
    }

    let opts = parse_emit_flags(&tail, false)?;

    if opts.kind == "wid" {
        let mut generator = WidGen::new_with_time_unit(opts.w, opts.z, None, opts.time_unit)
            .map_err(|e| e.to_string())?;
        let sample = generator.next_wid();
        let ok = validate_wid_with_unit(&sample, opts.w, opts.z, opts.time_unit);

        if json_mode {
            let payload = json!({
                "ok": ok,
                "kind": opts.kind,
                "W": opts.w,
                "Z": opts.z,
                "time_unit": opts.time_unit.as_str(),
                "sample_id": sample,
            });
            println!(
                "{}",
                serde_json::to_string(&payload).map_err(|e| e.to_string())?
            );
        } else {
            println!(
                "ok={} kind={} sample={}",
                if ok { "true" } else { "false" },
                opts.kind,
                sample
            );
        }

        if ok {
            Ok(())
        } else {
            Err("healthcheck failed".to_string())
        }
    } else {
        let mut generator =
            HLCWidGen::new_with_time_unit(opts.node, opts.w, opts.z, opts.time_unit)
                .map_err(|e| e.to_string())?;
        let sample = generator.next_hlc_wid();
        let ok = validate_hlc_wid_with_unit(&sample, opts.w, opts.z, opts.time_unit);

        if json_mode {
            let payload = json!({
                "ok": ok,
                "kind": opts.kind,
                "W": opts.w,
                "Z": opts.z,
                "time_unit": opts.time_unit.as_str(),
                "sample_id": sample,
            });
            println!(
                "{}",
                serde_json::to_string(&payload).map_err(|e| e.to_string())?
            );
        } else {
            println!(
                "ok={} kind={} sample={}",
                if ok { "true" } else { "false" },
                opts.kind,
                sample
            );
        }

        if ok {
            Ok(())
        } else {
            Err("healthcheck failed".to_string())
        }
    }
}

fn run_validate(args: &[String]) -> Result<(), String> {
    if args.is_empty() {
        return Err("validate requires an id".to_string());
    }

    let id = args[0].clone();
    let opts = parse_validate_flags(&args[1..])?;

    let ok = if opts.kind == "wid" {
        validate_wid_with_unit(&id, opts.w, opts.z, opts.time_unit)
    } else {
        validate_hlc_wid_with_unit(&id, opts.w, opts.z, opts.time_unit)
    };

    println!("{}", if ok { "true" } else { "false" });
    if ok {
        Ok(())
    } else {
        Err("invalid wid".to_string())
    }
}

fn run_parse(args: &[String]) -> Result<(), String> {
    if args.is_empty() {
        return Err("parse requires an id".to_string());
    }

    let id = args[0].clone();
    let mut json_out = false;

    let mut tail: Vec<String> = Vec::new();
    for arg in &args[1..] {
        if arg == "--json" {
            json_out = true;
        } else {
            tail.push(arg.clone());
        }
    }

    let opts = parse_validate_flags(&tail)?;

    if opts.kind == "wid" {
        let parsed =
            parse_wid_with_unit(&id, opts.w, opts.z, opts.time_unit).map_err(|e| e.to_string())?;
        if json_out {
            let payload = json!({
                "raw": parsed.raw,
                "timestamp": parsed.timestamp.to_rfc3339(),
                "sequence": parsed.sequence,
                "padding": parsed.padding,
            });
            println!(
                "{}",
                serde_json::to_string(&payload).map_err(|e| e.to_string())?
            );
        } else {
            println!("raw={}", parsed.raw);
            println!("timestamp={}", parsed.timestamp.to_rfc3339());
            println!("sequence={}", parsed.sequence);
            println!("padding={}", parsed.padding.unwrap_or_default());
        }
    } else {
        let parsed = parse_hlc_wid_with_unit(&id, opts.w, opts.z, opts.time_unit)
            .map_err(|e| e.to_string())?;
        if json_out {
            let payload = json!({
                "raw": parsed.raw,
                "timestamp": parsed.timestamp.to_rfc3339(),
                "logical_counter": parsed.logical_counter,
                "node": parsed.node,
                "padding": parsed.padding,
            });
            println!(
                "{}",
                serde_json::to_string(&payload).map_err(|e| e.to_string())?
            );
        } else {
            println!("raw={}", parsed.raw);
            println!("timestamp={}", parsed.timestamp.to_rfc3339());
            println!("logical_counter={}", parsed.logical_counter);
            println!("node={}", parsed.node);
            println!("padding={}", parsed.padding.unwrap_or_default());
        }
    }

    Ok(())
}

fn run_bench(args: &[String]) -> Result<(), String> {
    let mut opts = parse_emit_flags(args, true)?;
    if opts.count == 0 {
        opts.count = 100_000;
    }

    let start = Instant::now();

    if opts.kind == "wid" {
        let mut generator = WidGen::new_with_time_unit(opts.w, opts.z, None, opts.time_unit)
            .map_err(|e| e.to_string())?;
        for _ in 0..opts.count {
            let _ = generator.next_wid();
        }
    } else {
        let mut generator =
            HLCWidGen::new_with_time_unit(opts.node.clone(), opts.w, opts.z, opts.time_unit)
                .map_err(|e| e.to_string())?;
        for _ in 0..opts.count {
            let _ = generator.next_hlc_wid();
        }
    }

    let secs = start.elapsed().as_secs_f64().max(1e-9);
    let ips = opts.count as f64 / secs;

    let payload = json!({
        "impl": "rust",
        "kind": opts.kind,
        "W": opts.w,
        "Z": opts.z,
        "time_unit": opts.time_unit.as_str(),
        "n": opts.count,
        "seconds": secs,
        "ids_per_sec": ips,
    });
    println!(
        "{}",
        serde_json::to_string(&payload).map_err(|e| e.to_string())?
    );
    Ok(())
}

fn is_transport(s: &str) -> bool {
    matches!(s, "mqtt" | "ws" | "redis" | "null" | "stdout" | "auto")
}

fn is_local_service_transport(s: &str) -> bool {
    matches!(s, "mqtt" | "ws" | "redis" | "null" | "stdout")
}

fn workspace_root() -> PathBuf {
    let cwd = env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let mut cur = cwd.as_path();
    loop {
        if cur.join("implementations").exists() && cur.join("README.md").exists() {
            return cur.to_path_buf();
        }
        if let Some(parent) = cur.parent() {
            cur = parent;
        } else {
            return cwd;
        }
    }
}

fn resolve_data_dir(root: &Path, d: &str) -> PathBuf {
    if d.is_empty() {
        root.join(".local").join("services")
    } else {
        let p = PathBuf::from(d);
        if p.is_absolute() { p } else { root.join(p) }
    }
}

fn runtime_dir(root: &Path) -> PathBuf {
    root.join(".local").join("wid").join("rust")
}

fn runtime_pid_file(root: &Path) -> PathBuf {
    runtime_dir(root).join("service.pid")
}

fn runtime_log_file(root: &Path) -> PathBuf {
    runtime_dir(root).join("service.log")
}

fn parse_state_and_transport(c: &CanonOpts) -> (String, String) {
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

fn parse_pid(path: &Path) -> Option<i32> {
    let content = fs::read_to_string(path).ok()?;
    content.trim().parse::<i32>().ok()
}

fn pid_alive(pid: i32) -> bool {
    if pid <= 0 {
        return false;
    }
    Command::new("kill")
        .arg("-0")
        .arg(pid.to_string())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn kill_pid(pid: i32) -> bool {
    if pid <= 0 {
        return false;
    }
    if Command::new("kill")
        .arg(pid.to_string())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
    {
        return true;
    }
    Command::new("kill")
        .args(["-9", &pid.to_string()])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn run_service_action(c: &CanonOpts, action: &str) -> Result<(), String> {
    let root = workspace_root();
    let data_dir = resolve_data_dir(&root, &c.d);
    fs::create_dir_all(&data_dir).map_err(|e| format!("failed to create data dir: {e}"))?;
    let (_state_mode, mut transport) = parse_state_and_transport(c);
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
            return Err(format!("invalid transport for A={action}: {transport}"));
        }
    }

    let mut wid_gen = WidGen::new_with_time_unit(c.w, c.z, None, c.t).map_err(|e| e.to_string())?;
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
            _ => return Err(format!("unknown service action: {action}")),
        };

        if transport != "null" {
            println!(
                "{}",
                serde_json::to_string(&payload).map_err(|e| e.to_string())?
            );
            io::stdout().flush().map_err(|e| e.to_string())?;
        }

        i += 1;
        if i < iterations && c.l > 0 {
            thread::sleep(Duration::from_secs(c.l as u64));
        }
    }

    Ok(())
}

fn run_discover() -> Result<(), String> {
    let payload = json!({
        "impl":"rust",
        "orchestration":"native",
        "actions":["discover","scaffold","run","start","stop","status","logs","saf","saf-wid","wir","wism","wihp","wipr","duplex"],
        "transports":["auto","mqtt","ws","redis","null","stdout"]
    });
    println!(
        "{}",
        serde_json::to_string(&payload).map_err(|e| e.to_string())?
    );
    Ok(())
}

fn run_scaffold(c: &CanonOpts) -> Result<(), String> {
    if c.d.is_empty() {
        return Err("D=<name> required for A=scaffold".to_string());
    }
    let root = workspace_root();
    let target = resolve_data_dir(&root, &c.d);
    fs::create_dir_all(target.join("state"))
        .map_err(|e| format!("failed to scaffold state dir: {e}"))?;
    fs::create_dir_all(target.join("logs"))
        .map_err(|e| format!("failed to scaffold logs dir: {e}"))?;
    println!("scaffolded {}", target.display());
    Ok(())
}

fn run_status() -> Result<(), String> {
    let root = workspace_root();
    let pid_file = runtime_pid_file(&root);
    let log_file = runtime_log_file(&root);
    if let Some(pid) = parse_pid(&pid_file)
        && pid_alive(pid)
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

fn run_logs() -> Result<(), String> {
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
        Err(e) => Err(format!("failed to read logs: {e}")),
    }
}

fn run_stop() -> Result<(), String> {
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
    if kill_pid(pid) {
        let _ = fs::remove_file(&pid_file);
        println!("wid-rust stop: stopped pid={pid}");
        Ok(())
    } else {
        Err(format!("failed to stop pid={pid}"))
    }
}

fn daemon_kv_args(c: &CanonOpts, action: &str) -> Vec<String> {
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

fn run_start(c: &CanonOpts) -> Result<(), String> {
    let root = workspace_root();
    let runtime = runtime_dir(&root);
    fs::create_dir_all(&runtime).map_err(|e| format!("failed to create runtime dir: {e}"))?;
    let pid_file = runtime_pid_file(&root);
    let log_file = runtime_log_file(&root);

    if let Some(pid) = parse_pid(&pid_file)
        && pid_alive(pid)
    {
        println!(
            "wid-rust start: already-running pid={} log={}",
            pid,
            log_file.display()
        );
        return Ok(());
    }

    let log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_file)
        .map_err(|e| format!("failed to open log file: {e}"))?;
    let log_err = log
        .try_clone()
        .map_err(|e| format!("failed to clone log fd: {e}"))?;

    let exe = env::current_exe().map_err(|e| format!("failed to resolve current exe: {e}"))?;
    let child = Command::new(exe)
        .arg("__daemon")
        .args(daemon_kv_args(c, "run"))
        .stdout(Stdio::from(log))
        .stderr(Stdio::from(log_err))
        .spawn()
        .map_err(|e| format!("failed to start daemon: {e}"))?;

    fs::write(&pid_file, child.id().to_string())
        .map_err(|e| format!("failed to write pid file: {e}"))?;
    println!(
        "wid-rust start: started pid={} log={}",
        child.id(),
        log_file.display()
    );
    Ok(())
}

fn run_native_orchestration(c: &CanonOpts) -> Result<(), String> {
    match c.a.as_str() {
        "discover" => run_discover(),
        "scaffold" => run_scaffold(c),
        "run" => run_service_action(c, "run"),
        "start" => run_start(c),
        "stop" => run_stop(),
        "status" => run_status(),
        "logs" => run_logs(),
        "saf" => run_service_action(c, "saf"),
        "saf-wid" => run_service_action(c, "saf-wid"),
        "wir" => run_service_action(c, "wir"),
        "wism" => run_service_action(c, "wism"),
        "wihp" => run_service_action(c, "wihp"),
        "wipr" => run_service_action(c, "wipr"),
        "duplex" => run_service_action(c, "duplex"),
        _ => Err(format!("unknown A={}", c.a)),
    }
}

fn parse_canonical(args: &[String]) -> Result<CanonOpts, String> {
    let mut o = CanonOpts {
        a: "next".to_string(),
        w: 4,
        l: 3600,
        d: String::new(),
        i: "auto".to_string(),
        e: "state".to_string(),
        z: 6,
        t: TimeUnit::Sec,
        r: "auto".to_string(),
        m: false,
        n: 0,
        wid: String::new(),
        key: String::new(),
        sig: String::new(),
        data: String::new(),
        out: String::new(),
        mode: String::new(),
        code: String::new(),
        digits: 6,
        max_age_sec: 0,
        max_future_sec: 5,
    };

    for arg in args {
        let Some((k, v0)) = arg.split_once('=') else {
            return Err(format!("expected KEY=VALUE, got '{arg}'"));
        };
        let mut v = v0;
        if v == "#" {
            v = match k {
                "A" => "next",
                "W" => "4",
                "L" => "3600",
                "D" => "",
                "I" => "auto",
                "E" => "state",
                "Z" => "6",
                "T" => "sec",
                "R" => "auto",
                "M" => "false",
                "N" => "0",
                "DIGITS" => "6",
                "MAX_AGE_SEC" => "0",
                "MAX_FUTURE_SEC" => "5",
                _ => v,
            };
        }

        match k {
            "A" => o.a = v.to_lowercase(),
            "W" => o.w = v.parse().map_err(|_| "invalid W".to_string())?,
            "L" => o.l = v.parse().map_err(|_| "invalid L".to_string())?,
            "D" => o.d = v.to_string(),
            "I" => o.i = v.to_string(),
            "E" => o.e = v.to_string(),
            "Z" => o.z = v.parse().map_err(|_| "invalid Z".to_string())?,
            "T" => o.t = parse_time_unit(v)?,
            "R" => o.r = v.to_string(),
            "M" => {
                let n = v.to_ascii_lowercase();
                o.m = matches!(n.as_str(), "1" | "true" | "yes" | "y" | "on")
            }
            "N" => o.n = v.parse().map_err(|_| "invalid N".to_string())?,
            "WID" => o.wid = v.to_string(),
            "KEY" => o.key = v.to_string(),
            "SIG" => o.sig = v.to_string(),
            "DATA" => o.data = v.to_string(),
            "OUT" => o.out = v.to_string(),
            "MODE" => o.mode = v.to_string(),
            "CODE" => o.code = v.to_string(),
            "DIGITS" => o.digits = v.parse().map_err(|_| "invalid DIGITS".to_string())?,
            "MAX_AGE_SEC" => {
                o.max_age_sec = v.parse().map_err(|_| "invalid MAX_AGE_SEC".to_string())?
            }
            "MAX_FUTURE_SEC" => {
                o.max_future_sec = v.parse().map_err(|_| "invalid MAX_FUTURE_SEC".to_string())?
            }
            _ => return Err(format!("unknown key: {k}")),
        }
    }

    if o.m {
        o.t = TimeUnit::Ms;
    }

    o.a = match o.a.as_str() {
        "id" | "default" => "next".to_string(),
        "hc" => "healthcheck".to_string(),
        "raf" => "saf".to_string(),
        "waf" | "wraf" => "saf-wid".to_string(),
        "witr" => "wir".to_string(),
        "wim" => "wism".to_string(),
        "wih" => "wihp".to_string(),
        "wip" => "wipr".to_string(),
        _ => o.a,
    };

    if o.w == 0 {
        return Err("W must be > 0".to_string());
    }
    if !is_transport(&o.r) {
        return Err("invalid R transport".to_string());
    }

    Ok(o)
}

fn run_canonical(args: &[String]) -> Result<(), String> {
    let c = parse_canonical(args)?;

    if c.a == "help-actions" {
        print_actions();
        return Ok(());
    }
    if c.a == "sign" {
        return run_sign(&c);
    }
    if c.a == "verify" {
        return run_verify(&c);
    }
    if c.a == "w-otp" {
        return run_wotp(&c);
    }

    let (state_mode, _) = parse_state_and_transport(&c);
    if state_mode == "sql" && (c.a == "next" || c.a == "stream") {
        return match c.a.as_str() {
            "next" => run_canonical_sql_next(&c),
            "stream" => run_canonical_sql_stream(&c),
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
                "next" => run_next(&base),
                "stream" => {
                    base.push("--count".to_string());
                    base.push(c.n.to_string());
                    run_stream(&base)
                }
                "healthcheck" => {
                    base.push("--json".to_string());
                    run_healthcheck(&base)
                }
                _ => unreachable!(),
            }
        }
        _ => run_native_orchestration(&c),
    }
}

fn build_sign_verify_message(c: &CanonOpts, msg_path: &Path) -> Result<(), String> {
    if c.wid.trim().is_empty() {
        return Err("WID=<wid_string> required".to_string());
    }
    fs::write(msg_path, c.wid.as_bytes()).map_err(|e| format!("failed to write message: {e}"))?;
    if !c.data.trim().is_empty() {
        let data = fs::read(&c.data).map_err(|_| format!("data file not found: {}", c.data))?;
        let mut f = OpenOptions::new()
            .append(true)
            .open(msg_path)
            .map_err(|e| format!("failed to append data: {e}"))?;
        f.write_all(&data)
            .map_err(|e| format!("failed to append data: {e}"))?;
    }
    Ok(())
}

fn b64url_encode_file(path: &Path) -> Result<String, String> {
    let out = Command::new("sh")
        .arg("-lc")
        .arg(format!(
            "openssl base64 -A < '{}' | tr '+/' '-_' | tr -d '='",
            path.display()
        ))
        .output()
        .map_err(|_| "openssl not found".to_string())?;
    if !out.status.success() {
        return Err("failed to encode signature".to_string());
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

fn b64url_decode_to_file(sig: &str, out_file: &Path) -> Result<(), String> {
    let mut std = sig.replace('-', "+").replace('_', "/");
    match std.len() % 4 {
        2 => std.push_str("=="),
        3 => std.push('='),
        1 => return Err("invalid base64url signature length".to_string()),
        _ => {}
    }
    fs::write(out_file, std.as_bytes())
        .map_err(|e| format!("failed to write signature temp: {e}"))?;
    let st = Command::new("openssl")
        .arg("base64")
        .arg("-A")
        .arg("-d")
        .arg("-in")
        .arg(out_file)
        .arg("-out")
        .arg(format!("{}.bin", out_file.display()))
        .status()
        .map_err(|_| "openssl not found".to_string())?;
    if !st.success() {
        return Err("invalid signature encoding".to_string());
    }
    fs::rename(format!("{}.bin", out_file.display()), out_file)
        .map_err(|e| format!("failed to finalize signature temp: {e}"))?;
    Ok(())
}

fn run_sign(c: &CanonOpts) -> Result<(), String> {
    if c.key.trim().is_empty() {
        return Err("KEY=<private_key_path> required for A=sign".to_string());
    }
    if !Path::new(&c.key).exists() {
        return Err(format!("private key file not found: {}", c.key));
    }
    let root = workspace_root();
    let dir = root.join(".local").join("wid").join("rust");
    fs::create_dir_all(&dir).map_err(|e| format!("failed to create runtime dir: {e}"))?;
    let msg = dir.join(format!("sign_msg_{}.bin", process::id()));
    let sig = dir.join(format!("sign_sig_{}.bin", process::id()));
    build_sign_verify_message(c, &msg)?;
    let st = Command::new("openssl")
        .arg("pkeyutl")
        .arg("-sign")
        .arg("-inkey")
        .arg(&c.key)
        .arg("-rawin")
        .arg("-in")
        .arg(&msg)
        .arg("-out")
        .arg(&sig)
        .status()
        .map_err(|_| "openssl not found".to_string())?;
    if !st.success() {
        let _ = fs::remove_file(&msg);
        let _ = fs::remove_file(&sig);
        return Err("sign failed (ensure Ed25519 private key PEM)".to_string());
    }
    let encoded = b64url_encode_file(&sig)?;
    let _ = fs::remove_file(&msg);
    let _ = fs::remove_file(&sig);
    if c.out.trim().is_empty() {
        println!("{encoded}");
    } else {
        fs::write(&c.out, encoded.as_bytes())
            .map_err(|e| format!("failed to write OUT file: {e}"))?;
    }
    Ok(())
}

fn run_verify(c: &CanonOpts) -> Result<(), String> {
    if c.key.trim().is_empty() {
        return Err("KEY=<public_key_path> required for A=verify".to_string());
    }
    if c.sig.trim().is_empty() {
        return Err("SIG=<signature_string> required for A=verify".to_string());
    }
    if !Path::new(&c.key).exists() {
        return Err(format!("public key file not found: {}", c.key));
    }
    let root = workspace_root();
    let dir = root.join(".local").join("wid").join("rust");
    fs::create_dir_all(&dir).map_err(|e| format!("failed to create runtime dir: {e}"))?;
    let msg = dir.join(format!("verify_msg_{}.bin", process::id()));
    let sig = dir.join(format!("verify_sig_{}.bin", process::id()));
    build_sign_verify_message(c, &msg)?;
    b64url_decode_to_file(&c.sig, &sig)?;
    let st = Command::new("openssl")
        .arg("pkeyutl")
        .arg("-verify")
        .arg("-pubin")
        .arg("-inkey")
        .arg(&c.key)
        .arg("-sigfile")
        .arg(&sig)
        .arg("-rawin")
        .arg("-in")
        .arg(&msg)
        .status()
        .map_err(|_| "openssl not found".to_string())?;
    let _ = fs::remove_file(&msg);
    let _ = fs::remove_file(&sig);
    if st.success() {
        println!("Signature valid.");
        return Ok(());
    }
    Err("Signature invalid.".to_string())
}

fn resolve_wotp_secret(raw: &str) -> Result<String, String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err("w-otp secret cannot be empty".to_string());
    }
    if Path::new(trimmed).is_file() {
        let s =
            fs::read_to_string(trimmed).map_err(|e| format!("failed to read secret file: {e}"))?;
        return Ok(s.trim().to_string());
    }
    Ok(trimmed.to_string())
}

fn compute_wotp(secret: &str, wid: &str, digits: usize) -> Result<String, String> {
    let out = Command::new("openssl")
        .arg("dgst")
        .arg("-sha256")
        .arg("-mac")
        .arg("HMAC")
        .arg("-macopt")
        .arg(format!("key:{secret}"))
        .arg("-binary")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .map_err(|_| "openssl not found".to_string())?;
    let mut child = out;
    if let Some(stdin) = &mut child.stdin {
        stdin
            .write_all(wid.as_bytes())
            .map_err(|e| format!("failed to write wid to openssl: {e}"))?;
    }
    let out = child
        .wait_with_output()
        .map_err(|e| format!("failed to execute openssl: {e}"))?;
    if !out.status.success() || out.stdout.len() < 4 {
        return Err("failed to compute w-otp digest".to_string());
    }
    let v = ((out.stdout[0] as u32) << 24)
        | ((out.stdout[1] as u32) << 16)
        | ((out.stdout[2] as u32) << 8)
        | (out.stdout[3] as u32);
    let mut m = 1u32;
    for _ in 0..digits {
        m = m.saturating_mul(10);
    }
    Ok(format!("{:0width$}", v % m, width = digits))
}

fn run_wotp(c: &CanonOpts) -> Result<(), String> {
    let mode = {
        let m = c.mode.trim().to_ascii_lowercase();
        if m.is_empty() { "gen".to_string() } else { m }
    };
    if mode != "gen" && mode != "verify" {
        return Err("MODE must be gen or verify for A=w-otp".to_string());
    }
    if c.key.trim().is_empty() {
        return Err("KEY=<secret_or_path> required for A=w-otp".to_string());
    }
    if c.digits < 4 || c.digits > 10 {
        return Err("DIGITS must be between 4 and 10".to_string());
    }
    let secret = resolve_wotp_secret(&c.key)?;
    let wid = if c.wid.trim().is_empty() && mode == "gen" {
        WidGen::new_with_time_unit(c.w, c.z, None, c.t)
            .map_err(|e| e.to_string())?
            .next_wid()
    } else {
        c.wid.clone()
    };
    if wid.trim().is_empty() {
        return Err("WID=<wid_string> required for A=w-otp MODE=verify".to_string());
    }
    let otp = compute_wotp(&secret, &wid, c.digits)?;
    if mode == "gen" {
        println!("{}", json!({"wid": wid, "otp": otp, "digits": c.digits}));
        return Ok(());
    }
    if c.code.trim().is_empty() {
        return Err("CODE=<otp_code> required for A=w-otp MODE=verify".to_string());
    }
    if c.max_age_sec > 0 || c.max_future_sec > 0 {
        let parsed = parse_wid_with_unit(&wid, c.w, c.z, c.t)
            .map_err(|_| "WID timestamp is invalid for time-window verification".to_string())?;
        let now_ms = chrono::Utc::now().timestamp_millis();
        let wid_ms = parsed.timestamp.timestamp_millis();
        let delta = now_ms - wid_ms;
        if delta < 0 {
            if -delta > (c.max_future_sec as i64) * 1000 {
                return Err("OTP invalid: WID timestamp is too far in the future".to_string());
            }
        } else if c.max_age_sec > 0 && delta > (c.max_age_sec as i64) * 1000 {
            return Err("OTP invalid: WID timestamp is too old".to_string());
        }
    }
    if c.code == otp {
        println!("OTP valid.");
        return Ok(());
    }
    Err("OTP invalid.".to_string())
}

fn sql_escape_single(s: &str) -> String {
    s.replace('\'', "''")
}

fn sqlite_exec(db_path: &Path, sql: &str) -> Result<String, String> {
    let out = Command::new("sqlite3")
        .arg("-cmd")
        .arg(".timeout 5000")
        .arg(db_path)
        .arg(sql)
        .output()
        .map_err(|_| "sqlite3 command not found (required for E=sql)".to_string())?;
    if !out.status.success() {
        return Err(format!(
            "sqlite3 failed: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        ));
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

fn sql_state_path(c: &CanonOpts) -> PathBuf {
    let root = workspace_root();
    resolve_data_dir(&root, &c.d).join("wid_state.sqlite")
}

fn sql_state_key(c: &CanonOpts) -> String {
    format!("wid:rust:{}:{}:{}", c.w, c.z, c.t.as_str())
}

fn sql_ensure_state(db_path: &Path, key: &str) -> Result<(), String> {
    let escaped = sql_escape_single(key);
    let sql = format!(
        "CREATE TABLE IF NOT EXISTS wid_state (k TEXT PRIMARY KEY, last_tick INTEGER NOT NULL, last_seq INTEGER NOT NULL);\
         INSERT OR IGNORE INTO wid_state(k,last_tick,last_seq) VALUES('{escaped}',0,-1);"
    );
    sqlite_exec(db_path, &sql).map(|_| ())
}

fn sql_load_state(db_path: &Path, key: &str) -> Result<(i64, i64), String> {
    let escaped = sql_escape_single(key);
    let sql = format!("SELECT last_tick || '|' || last_seq FROM wid_state WHERE k='{escaped}';");
    let raw = sqlite_exec(db_path, &sql)?;
    let (tick_s, seq_s) = raw
        .split_once('|')
        .ok_or_else(|| "invalid sql state row".to_string())?;
    let tick = tick_s
        .parse::<i64>()
        .map_err(|_| "invalid sql tick".to_string())?;
    let seq = seq_s
        .parse::<i64>()
        .map_err(|_| "invalid sql seq".to_string())?;
    Ok((tick, seq))
}

fn sql_compare_and_swap_state(
    db_path: &Path,
    key: &str,
    old_tick: i64,
    old_seq: i64,
    tick: i64,
    seq: i64,
) -> Result<bool, String> {
    let escaped = sql_escape_single(key);
    let sql = format!(
        "UPDATE wid_state SET last_tick={tick},last_seq={seq} WHERE k='{escaped}' AND last_tick={old_tick} AND last_seq={old_seq};\
         SELECT changes();"
    );
    let raw = sqlite_exec(db_path, &sql)?;
    Ok(raw.trim() == "1")
}

fn sql_allocate_next_wid(c: &CanonOpts) -> Result<String, String> {
    let db_path = sql_state_path(c);
    let key = sql_state_key(c);
    sql_ensure_state(&db_path, &key)?;
    for _ in 0..64 {
        let (last_tick, last_seq) = sql_load_state(&db_path, &key)?;
        let mut generator =
            WidGen::new_with_time_unit(c.w, c.z, None, c.t).map_err(|e| e.to_string())?;
        generator.restore_state(last_tick, last_seq);
        let id = generator.next_wid();
        let (next_tick, next_seq) = generator.state();
        if sql_compare_and_swap_state(&db_path, &key, last_tick, last_seq, next_tick, next_seq)? {
            return Ok(id);
        }
    }
    Err("sql allocation contention: retry budget exhausted".to_string())
}

fn run_canonical_sql_next(c: &CanonOpts) -> Result<(), String> {
    let root = workspace_root();
    let dd = resolve_data_dir(&root, &c.d);
    fs::create_dir_all(&dd).map_err(|e| format!("failed to create data dir: {e}"))?;
    let id = sql_allocate_next_wid(c)?;
    println!("{id}");
    Ok(())
}

fn run_canonical_sql_stream(c: &CanonOpts) -> Result<(), String> {
    let root = workspace_root();
    let dd = resolve_data_dir(&root, &c.d);
    fs::create_dir_all(&dd).map_err(|e| format!("failed to create data dir: {e}"))?;
    let mut emitted = 0usize;
    loop {
        if c.n > 0 && emitted >= c.n {
            break;
        }
        println!("{}", sql_allocate_next_wid(c)?);
        io::stdout().flush().map_err(|e| e.to_string())?;
        emitted += 1;
    }
    Ok(())
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();

    if args.is_empty() {
        print_help();
        process::exit(2);
    }

    if args[0] == "__daemon" {
        let daemon_args: Vec<String> = args[1..].to_vec();
        if let Err(err) = run_canonical(&daemon_args) {
            eprintln!("error: {err}");
            process::exit(1);
        }
        return;
    }

    if args.iter().any(|a| a.contains('=')) {
        if let Err(err) = run_canonical(&args) {
            eprintln!("error: {err}");
            process::exit(1);
        }
        return;
    }

    if args[0] == "-h" || args[0] == "--help" || args[0] == "help" {
        print_help();
        return;
    }

    if args[0] == "help-actions" {
        print_actions();
        return;
    }

    let cmd = args[0].as_str();
    let rest = &args[1..];

    let res = match cmd {
        "next" => run_next(rest),
        "stream" => run_stream(rest),
        "healthcheck" => run_healthcheck(rest),
        "validate" => run_validate(rest),
        "parse" => run_parse(rest),
        "bench" => run_bench(rest),
        "selftest" => match WidGen::new_with_time_unit(4, 0, None, TimeUnit::Sec) {
            Ok(mut g) => {
                let a = g.next_wid();
                let b = g.next_wid();
                if a >= b {
                    Err("selftest failed: non-monotonic".to_string())
                } else {
                    Ok(())
                }
            }
            Err(e) => Err(e.to_string()),
        },
        _ => Err(format!("unknown command: {}", cmd)),
    };

    if let Err(err) = res {
        eprintln!("error: {}", err);
        process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_time_unit() {
        assert_eq!(parse_time_unit("sec").unwrap(), TimeUnit::Sec);
        assert_eq!(parse_time_unit("ms").unwrap(), TimeUnit::Ms);
        assert!(parse_time_unit("bad").is_err());
    }

    #[test]
    fn test_parse_emit_time_unit() {
        let opts = parse_emit_flags(&["--time-unit".to_string(), "ms".to_string()], false).unwrap();
        assert_eq!(opts.time_unit, TimeUnit::Ms);
    }

    #[test]
    fn test_parse_validate_time_unit() {
        let opts = parse_validate_flags(&["--time-unit".to_string(), "ms".to_string()]).unwrap();
        assert_eq!(opts.time_unit, TimeUnit::Ms);
    }

    #[test]
    fn test_parse_canonical_aliases() {
        let c =
            parse_canonical(&["A=waf".to_string(), "W=4".to_string(), "Z=6".to_string()]).unwrap();
        assert_eq!(c.a, "saf-wid");
    }
}
