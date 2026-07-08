//! Core CLI commands: next, stream, healthcheck, validate, parse, bench, selftest.

use std::io::{self, Write};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::json;
use wid::{
    HLCWidGen, TimeUnit, WidGen, parse_hlc_wid_with_unit, parse_wid_with_unit,
    validate_hlc_wid_with_unit, validate_wid_with_unit,
};

use super::args::{self, check_shape_bounds};
use super::error::{CliError, fail, usage};

pub(crate) fn run_next(args: &[String]) -> Result<(), CliError> {
    let opts = args::parse_emit_flags(args, false).map_err(usage)?;

    if opts.kind == "wid" {
        let mut generator = WidGen::new_with_time_unit(opts.w, opts.z, opts.time_unit)
            .map_err(|e| usage(e.to_string()))?;
        println!("{}", generator.next_wid());
    } else {
        let mut generator =
            HLCWidGen::new_with_time_unit(opts.node, opts.w, opts.z, opts.time_unit)
                .map_err(|e| usage(e.to_string()))?;
        println!("{}", generator.next_hlc_wid());
    }

    Ok(())
}

/// Emit the stream. `interval_secs` is the canonical `L=` cadence: 0 (the
/// stream default, and always the flag-mode value) means emit back-to-back;
/// an explicit `L=n` sleeps n seconds between emissions in every
/// implementation.
pub(crate) fn run_stream(args: &[String], interval_secs: u64) -> Result<(), CliError> {
    let opts = args::parse_emit_flags(args, true).map_err(usage)?;
    let mut emitted = 0usize;

    let emit_one = |line: String| -> Result<(), CliError> {
        println!("{line}");
        io::stdout().flush().map_err(|e| fail(e.to_string()))
    };

    if opts.kind == "wid" {
        let mut generator = WidGen::new_with_time_unit(opts.w, opts.z, opts.time_unit)
            .map_err(|e| usage(e.to_string()))?;
        loop {
            if opts.count > 0 && emitted >= opts.count {
                break;
            }
            emit_one(generator.next_wid())?;
            emitted += 1;
            if interval_secs > 0 && (opts.count == 0 || emitted < opts.count) {
                thread::sleep(Duration::from_secs(interval_secs));
            }
        }
    } else {
        let mut generator =
            HLCWidGen::new_with_time_unit(opts.node, opts.w, opts.z, opts.time_unit)
                .map_err(|e| usage(e.to_string()))?;
        loop {
            if opts.count > 0 && emitted >= opts.count {
                break;
            }
            emit_one(generator.next_hlc_wid())?;
            emitted += 1;
            if interval_secs > 0 && (opts.count == 0 || emitted < opts.count) {
                thread::sleep(Duration::from_secs(interval_secs));
            }
        }
    }

    Ok(())
}

pub(crate) fn run_healthcheck(args: &[String]) -> Result<(), CliError> {
    let mut json_mode = false;
    let mut tail: Vec<String> = Vec::new();
    for arg in args {
        if arg == "--json" {
            json_mode = true;
        } else {
            tail.push(arg.clone());
        }
    }

    let opts = args::parse_emit_flags(&tail, false).map_err(usage)?;

    let (sample, ok) = if opts.kind == "wid" {
        let mut generator = WidGen::new_with_time_unit(opts.w, opts.z, opts.time_unit)
            .map_err(|e| usage(e.to_string()))?;
        let sample = generator.next_wid();
        let ok = validate_wid_with_unit(&sample, opts.w, opts.z, opts.time_unit);
        (sample, ok)
    } else {
        let mut generator =
            HLCWidGen::new_with_time_unit(opts.node.clone(), opts.w, opts.z, opts.time_unit)
                .map_err(|e| usage(e.to_string()))?;
        let sample = generator.next_hlc_wid();
        let ok = validate_hlc_wid_with_unit(&sample, opts.w, opts.z, opts.time_unit);
        (sample, ok)
    };

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
            serde_json::to_string(&payload).map_err(|e| fail(e.to_string()))?
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
        Err(fail("healthcheck failed"))
    }
}

pub(crate) fn run_validate(args: &[String]) -> Result<(), CliError> {
    if args.is_empty() {
        return Err(usage("validate requires an id"));
    }

    let id = args[0].clone();
    let opts = args::parse_validate_flags(&args[1..]).map_err(usage)?;
    check_shape_bounds(opts.w, opts.z)?;

    let ok = if opts.kind == "wid" {
        validate_wid_with_unit(&id, opts.w, opts.z, opts.time_unit)
    } else {
        validate_hlc_wid_with_unit(&id, opts.w, opts.z, opts.time_unit)
    };

    println!("{}", if ok { "true" } else { "false" });
    if ok { Ok(()) } else { Err(fail("invalid wid")) }
}

pub(crate) fn run_parse(args: &[String]) -> Result<(), CliError> {
    if args.is_empty() {
        return Err(usage("parse requires an id"));
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

    let opts = args::parse_validate_flags(&tail).map_err(usage)?;
    check_shape_bounds(opts.w, opts.z)?;

    if opts.kind == "wid" {
        let parsed = parse_wid_with_unit(&id, opts.w, opts.z, opts.time_unit)
            .map_err(|e| fail(e.to_string()))?;
        if json_out {
            let payload = json!({
                "raw": parsed.raw,
                "timestamp": parsed.timestamp.to_rfc3339(),
                "sequence": parsed.sequence,
                "padding": parsed.padding,
            });
            println!(
                "{}",
                serde_json::to_string(&payload).map_err(|e| fail(e.to_string()))?
            );
        } else {
            println!("raw={}", parsed.raw);
            println!("timestamp={}", parsed.timestamp.to_rfc3339());
            println!("sequence={}", parsed.sequence);
            println!("padding={}", parsed.padding.unwrap_or_default());
        }
    } else {
        let parsed = parse_hlc_wid_with_unit(&id, opts.w, opts.z, opts.time_unit)
            .map_err(|e| fail(e.to_string()))?;
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
                serde_json::to_string(&payload).map_err(|e| fail(e.to_string()))?
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

pub(crate) fn run_bench(args: &[String]) -> Result<(), CliError> {
    let mut opts = args::parse_emit_flags(args, true).map_err(usage)?;
    if opts.count == 0 {
        opts.count = 100_000;
    }

    let start = Instant::now();

    if opts.kind == "wid" {
        let mut generator = WidGen::new_with_time_unit(opts.w, opts.z, opts.time_unit)
            .map_err(|e| usage(e.to_string()))?;
        for _ in 0..opts.count {
            let _ = generator.next_wid();
        }
    } else {
        let mut generator =
            HLCWidGen::new_with_time_unit(opts.node.clone(), opts.w, opts.z, opts.time_unit)
                .map_err(|e| usage(e.to_string()))?;
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
        serde_json::to_string(&payload).map_err(|e| fail(e.to_string()))?
    );
    Ok(())
}

pub(crate) fn run_selftest() -> Result<(), CliError> {
    let mut wg =
        WidGen::new_with_time_unit(4, 0, TimeUnit::Sec).map_err(|e| fail(e.to_string()))?;
    let a = wg.next_wid();
    let b = wg.next_wid();
    let valid = a < b
        && validate_wid_with_unit(&a, 4, 0, TimeUnit::Sec)
        && validate_hlc_wid_with_unit(
            &HLCWidGen::new_with_time_unit("node01".to_string(), 4, 0, TimeUnit::Sec)
                .map_err(|e| fail(e.to_string()))?
                .next_hlc_wid(),
            4,
            0,
            TimeUnit::Sec,
        )
        && !validate_wid_with_unit("20260212T091530.0000Z-node01", 4, 0, TimeUnit::Sec)
        && !validate_hlc_wid_with_unit("20260212T091530.0000Z", 4, 0, TimeUnit::Sec)
        && validate_wid_with_unit("20260212T091530123.0000Z", 4, 0, TimeUnit::Ms)
        && validate_hlc_wid_with_unit("20260212T091530123.0000Z-node01", 4, 0, TimeUnit::Ms);
    if valid {
        Ok(())
    } else {
        Err(fail("selftest failed"))
    }
}
