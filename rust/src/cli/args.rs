//! CLI argument parsing: flag-mode and canonical KEY=VALUE surface.
//!
//! The flag/validate/emit parsers are shared across `next`, `stream`,
//! `healthcheck`, `validate`, `parse`, and `bench` so the accepted flags,
//! defaults, and error strings stay identical across every subcommand.

use std::env;

use wid::{MAX_W, MAX_Z, TimeUnit};

use super::error::{CliError, usage};

/// Out-of-range W/Z is a usage error (exit 2) in every implementation —
/// checked up front so validate/parse report it as such instead of
/// misreporting the id itself as invalid (exit 1).
pub(crate) fn check_shape_bounds(w: usize, z: usize) -> Result<(), CliError> {
    if w == 0 || w > MAX_W {
        return Err(usage("W must be between 1 and 18"));
    }
    if z > MAX_Z {
        return Err(usage("Z must be between 0 and 64"));
    }
    Ok(())
}

#[derive(Debug, Clone)]
pub(crate) struct ValidateOpts {
    pub kind: String,
    pub w: usize,
    pub z: usize,
    pub time_unit: TimeUnit,
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
pub(crate) struct EmitOpts {
    pub kind: String,
    pub node: String,
    pub w: usize,
    pub z: usize,
    pub time_unit: TimeUnit,
    pub count: usize,
}

#[derive(Debug, Clone)]
pub(crate) struct CanonOpts {
    pub a: String,
    pub w: usize,
    pub l: usize,
    /// True only when the user passed a real `L=<n>` (not omitted, not the
    /// `L=#` placeholder). `A=stream` treats an unset L as 0 (no sleep);
    /// the 3600 default applies to the service loops only.
    pub l_explicit: bool,
    pub d: String,
    pub i: String,
    pub e: String,
    pub z: usize,
    pub t: TimeUnit,
    pub r: String,
    pub m: bool,
    pub n: usize,
    pub wid: String,
    pub key: String,
    pub sig: String,
    pub data: String,
    pub out: String,
    pub mode: String,
    pub code: String,
    pub digits: usize,
    pub max_age_sec: u64,
    pub max_future_sec: u64,
}

pub(crate) fn default_node() -> String {
    env::var("NODE").unwrap_or_else(|_| "rust".to_string())
}

pub(crate) fn parse_time_unit(s: &str) -> Result<TimeUnit, String> {
    TimeUnit::parse(s).ok_or_else(|| "time-unit must be sec or ms".to_string())
}

pub(crate) fn is_transport(s: &str) -> bool {
    matches!(s, "mqtt" | "ws" | "redis" | "null" | "stdout" | "auto")
}

pub(crate) fn is_local_service_transport(s: &str) -> bool {
    matches!(s, "mqtt" | "ws" | "redis" | "null" | "stdout")
}

fn flag_value<'a>(args: &'a [String], i: usize, name: &str) -> Result<&'a str, String> {
    args.get(i + 1)
        .map(String::as_str)
        .ok_or_else(|| format!("missing value for {name}"))
}

fn flag_usize(args: &[String], i: usize, name: &str) -> Result<usize, String> {
    flag_value(args, i, name)?
        .parse::<usize>()
        .map_err(|_| format!("invalid integer for {name}"))
}

/// Single parser for the `--flag` surface. `validate`/`parse` reuse it with
/// `--node`/`--count` disallowed; the accepted flags, defaults, and error
/// strings stay identical across every subcommand by construction.
pub(crate) fn parse_surface_flags(
    args: &[String],
    allow_node: bool,
    allow_count: bool,
) -> Result<EmitOpts, String> {
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
            "--kind" => opts.kind = flag_value(args, i, "--kind")?.to_string(),
            "--node" if allow_node => opts.node = flag_value(args, i, "--node")?.to_string(),
            "--W" => opts.w = flag_usize(args, i, "--W")?,
            "--Z" => opts.z = flag_usize(args, i, "--Z")?,
            "--time-unit" | "--T" => {
                opts.time_unit = parse_time_unit(flag_value(args, i, "--time-unit")?)?;
            }
            "--count" if allow_count => opts.count = flag_usize(args, i, "--count")?,
            _ => return Err(format!("unknown flag: {}", args[i])),
        }
        i += 2;
    }

    match opts.kind.as_str() {
        "wid" | "hlc" => Ok(opts),
        _ => Err("--kind must be one of: wid, hlc".to_string()),
    }
}

pub(crate) fn parse_validate_flags(args: &[String]) -> Result<ValidateOpts, String> {
    let opts = parse_surface_flags(args, false, false)?;
    Ok(ValidateOpts {
        kind: opts.kind,
        w: opts.w,
        z: opts.z,
        time_unit: opts.time_unit,
    })
}

pub(crate) fn parse_emit_flags(args: &[String], allow_count: bool) -> Result<EmitOpts, String> {
    parse_surface_flags(args, true, allow_count)
}

pub(crate) fn parse_canonical(args: &[String]) -> Result<CanonOpts, String> {
    let mut o = CanonOpts {
        a: "next".to_string(),
        w: 4,
        l: 3600,
        l_explicit: false,
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
            "L" => {
                o.l = v.parse().map_err(|_| "invalid L".to_string())?;
                o.l_explicit = v0 != "#";
            }
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
                o.max_future_sec = v
                    .parse()
                    .map_err(|_| "invalid MAX_FUTURE_SEC".to_string())?
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

    // Reject out-of-range W/Z here (usage error, exit 2) instead of letting
    // the generator constructor report it as an operational failure.
    if o.w == 0 || o.w > MAX_W {
        return Err("W must be between 1 and 18".to_string());
    }
    if o.z > MAX_Z {
        return Err("Z must be between 0 and 64".to_string());
    }
    if !is_transport(&o.r) {
        return Err("invalid R transport".to_string());
    }

    Ok(o)
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
