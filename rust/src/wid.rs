//! WID (Waldiez/SYNAPSE Identifier) generation and validation.
//!
//! Format: `YYYYMMDDTHHMMSS[mmm].<seqW>Z[-<padZ>]`
//!
//! The generator implements `Iterator<Item = String>`.
//! Use `next_wid()` for the explicit domain API.

use chrono::{DateTime, TimeZone, Timelike, Utc};
use once_cell::sync::Lazy;
use rand::random_range;
use regex::Regex;
use std::time::{SystemTime, UNIX_EPOCH};
use thiserror::Error;

/// Errors that can occur during WID operations.
#[derive(Error, Debug)]
pub enum WidError {
    #[error("Invalid W parameter: must be > 0")]
    InvalidW,
    #[error("Invalid Z parameter: must be >= 0")]
    InvalidZ,
    #[error("Scope is not supported for plain WID")]
    InvalidScope,
    #[error("Invalid node format")]
    InvalidNode,
    #[error("Invalid remote clock values")]
    InvalidRemoteClock,
    #[error("Invalid WID format: {0}")]
    InvalidFormat(String),
    #[error("Invalid timestamp in WID")]
    InvalidTimestamp,
}

/// Timestamp precision mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TimeUnit {
    Sec,
    Ms,
}

impl TimeUnit {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Sec => "sec",
            Self::Ms => "ms",
        }
    }

    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "sec" => Some(Self::Sec),
            "ms" => Some(Self::Ms),
            _ => None,
        }
    }
}

/// Parsed WID components.
#[derive(Debug, Clone, PartialEq)]
pub struct ParsedWid {
    pub raw: String,
    pub timestamp: DateTime<Utc>,
    pub sequence: u32,
    pub padding: Option<String>,
}

impl ParsedWid {
    /// Get Unix timestamp in seconds.
    pub fn timestamp_sec(&self) -> i64 {
        self.timestamp.timestamp()
    }
}

static WID_PATTERN_W4_Z6_SEC: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^(\d{8})T(\d{6})\.(\d{4})Z(?:-([0-9a-f]{6}))?$").unwrap());

fn build_pattern(w: usize, z: usize, time_unit: TimeUnit) -> Regex {
    let seq_part = format!(r"(\d{{{}}})", w);
    let time_digits = match time_unit {
        TimeUnit::Sec => 6,
        TimeUnit::Ms => 9,
    };
    let pad_part = if z > 0 {
        format!(r"(?:-([0-9a-f]{{{}}}))?$", z)
    } else {
        r"$".to_string()
    };

    let pattern = format!(
        r"^(\d{{8}})T(\d{{{}}})\.{}Z{}",
        time_digits, seq_part, pad_part
    );
    Regex::new(&pattern).unwrap()
}

fn parse_timestamp(time_unit: TimeUnit, date_str: &str, time_str: &str) -> Option<DateTime<Utc>> {
    let year: i32 = date_str[0..4].parse().ok()?;
    let month: u32 = date_str[4..6].parse().ok()?;
    let day: u32 = date_str[6..8].parse().ok()?;

    match time_unit {
        TimeUnit::Sec => {
            let hour: u32 = time_str[0..2].parse().ok()?;
            let minute: u32 = time_str[2..4].parse().ok()?;
            let second: u32 = time_str[4..6].parse().ok()?;
            Utc.with_ymd_and_hms(year, month, day, hour, minute, second)
                .single()
        }
        TimeUnit::Ms => {
            let hour: u32 = time_str[0..2].parse().ok()?;
            let minute: u32 = time_str[2..4].parse().ok()?;
            let second: u32 = time_str[4..6].parse().ok()?;
            let millis: u32 = time_str[6..9].parse().ok()?;
            Utc.with_ymd_and_hms(year, month, day, hour, minute, second)
                .single()?
                .with_nanosecond(millis * 1_000_000)
        }
    }
}

/// Validate a WID string for a specific time unit.
pub fn validate_wid_with_unit(wid: &str, w: usize, z: usize, time_unit: TimeUnit) -> bool {
    parse_wid_with_unit(wid, w, z, time_unit).is_ok()
}

/// Validate a WID string in `sec` mode.
pub fn validate_wid(wid: &str, w: usize, z: usize) -> bool {
    validate_wid_with_unit(wid, w, z, TimeUnit::Sec)
}

/// Parse a WID string into its components for a specific time unit.
pub fn parse_wid_with_unit(
    wid: &str,
    w: usize,
    z: usize,
    time_unit: TimeUnit,
) -> Result<ParsedWid, WidError> {
    if w == 0 {
        return Err(WidError::InvalidW);
    }

    let pattern = if w == 4 && z == 6 && time_unit == TimeUnit::Sec {
        &*WID_PATTERN_W4_Z6_SEC
    } else {
        &build_pattern(w, z, time_unit)
    };

    let caps = pattern
        .captures(wid)
        .ok_or_else(|| WidError::InvalidFormat(wid.to_string()))?;

    let date_str = &caps[1];
    let time_str = &caps[2];
    let seq_str = &caps[3];
    let padding = if z > 0 {
        caps.get(4).map(|m| m.as_str().to_string())
    } else {
        None
    };

    let timestamp =
        parse_timestamp(time_unit, date_str, time_str).ok_or(WidError::InvalidTimestamp)?;

    let sequence: u32 = seq_str
        .parse()
        .map_err(|_| WidError::InvalidFormat(wid.to_string()))?;

    Ok(ParsedWid {
        raw: wid.to_string(),
        timestamp,
        sequence,
        padding,
    })
}

/// Parse a WID string into its components in `sec` mode.
pub fn parse_wid(wid: &str, w: usize, z: usize) -> Result<ParsedWid, WidError> {
    parse_wid_with_unit(wid, w, z, TimeUnit::Sec)
}

/// WID generator with monotonic sequence and collision-resistant padding.
pub struct WidGen {
    w: usize,
    z: usize,
    time_unit: TimeUnit,
    max_seq: i64,
    last_tick: i64,
    last_seq: i64,
    cached_tick: i64,
    cached_ts: String,
}

impl WidGen {
    /// Create a new WID generator in `sec` mode.
    pub fn new(w: usize, z: usize, scope: Option<String>) -> Result<Self, WidError> {
        Self::new_with_time_unit(w, z, scope, TimeUnit::Sec)
    }

    /// Create a new WID generator with a chosen time unit.
    pub fn new_with_time_unit(
        w: usize,
        z: usize,
        scope: Option<String>,
        time_unit: TimeUnit,
    ) -> Result<Self, WidError> {
        if w == 0 {
            return Err(WidError::InvalidW);
        }

        if scope.is_some() {
            return Err(WidError::InvalidScope);
        }

        let max_seq = 10_i64.pow(w as u32) - 1;

        Ok(Self {
            w,
            z,
            time_unit,
            max_seq,
            last_tick: 0,
            last_seq: -1,
            cached_tick: -1,
            cached_ts: String::new(),
        })
    }

    /// Create a generator with default parameters (W=4, Z=6, `sec`).
    pub fn default_params() -> Self {
        Self::new(4, 6, None).expect("default parameters should always be valid")
    }

    fn ts_for_tick(&mut self, tick: i64) -> &str {
        if tick != self.cached_tick {
            self.cached_tick = tick;
            self.cached_ts = match self.time_unit {
                TimeUnit::Sec => {
                    let dt = Utc.timestamp_opt(tick, 0).unwrap();
                    dt.format("%Y%m%dT%H%M%S").to_string()
                }
                TimeUnit::Ms => {
                    let sec = tick / 1000;
                    let ms = (tick % 1000) as u32;
                    let dt = Utc.timestamp_opt(sec, ms * 1_000_000).unwrap();
                    dt.format("%Y%m%dT%H%M%S%3f").to_string()
                }
            };
        }
        &self.cached_ts
    }

    fn current_tick(time_unit: TimeUnit) -> i64 {
        let dur = SystemTime::now().duration_since(UNIX_EPOCH).unwrap();
        match time_unit {
            TimeUnit::Sec => dur.as_secs() as i64,
            TimeUnit::Ms => dur.as_millis() as i64,
        }
    }

    /// Generate the next WID (domain API).
    pub fn next_wid(&mut self) -> String {
        let now_tick = Self::current_tick(self.time_unit);
        let mut tick = if now_tick > self.last_tick {
            now_tick
        } else {
            self.last_tick
        };

        let mut seq = if tick == self.last_tick {
            self.last_seq + 1
        } else {
            0
        };

        if seq > self.max_seq {
            tick += 1;
            seq = 0;
        }

        self.last_tick = tick;
        self.last_seq = seq;

        let ts = self.ts_for_tick(tick).to_string();
        let seq_str = format!("{:0width$}", seq, width = self.w);

        let mut wid = format!("{}.{}Z", ts, seq_str);

        if self.z > 0 {
            let pad: String = (0..self.z)
                .map(|_| {
                    let idx = random_range(0..16);
                    "0123456789abcdef".chars().nth(idx).unwrap()
                })
                .collect();
            wid.push('-');
            wid.push_str(&pad);
        }

        wid
    }

    /// Generate n WIDs.
    pub fn next_n(&mut self, n: usize) -> Vec<String> {
        self.take(n).collect()
    }

    /// Restore generator state.
    pub fn restore_state(&mut self, last_tick: i64, last_seq: i64) {
        self.last_tick = last_tick;
        self.last_seq = last_seq;
    }

    /// Get current state.
    pub fn state(&self) -> (i64, i64) {
        (self.last_tick, self.last_seq)
    }

    /// Active time unit.
    pub fn time_unit(&self) -> TimeUnit {
        self.time_unit
    }
}

impl Iterator for WidGen {
    type Item = String;

    #[inline]
    fn next(&mut self) -> Option<Self::Item> {
        Some(self.next_wid())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validate_valid_wids() {
        assert!(validate_wid("20260212T091530.0000Z", 4, 0));
        assert!(validate_wid("20260212T091530.0042Z", 4, 0));
        assert!(validate_wid("20260212T091530.0042Z-a3f91c", 4, 6));
        assert!(validate_wid_with_unit(
            "20260212T091530123.0042Z-a3f91c",
            4,
            6,
            TimeUnit::Ms
        ));
    }

    #[test]
    fn test_validate_invalid_wids() {
        assert!(!validate_wid("waldiez", 4, 6));
        assert!(!validate_wid("20260212T091530.0000", 4, 0));
        assert!(!validate_wid("20261312T091530.0000Z", 4, 0));
        assert!(!validate_wid("20260212T091530.0000Z", 0, 0));
        assert!(!validate_wid("20260212T091530.0000Z-ABCDEF", 4, 6));
        assert!(!validate_wid("20260212T091530.0000Z-node01", 4, 0));
        assert!(!validate_wid_with_unit(
            "20260212T09153012.0000Z",
            4,
            0,
            TimeUnit::Ms
        ));
    }

    #[test]
    fn test_new_rejects_invalid_params() {
        assert!(matches!(WidGen::new(0, 0, None), Err(WidError::InvalidW)));
        assert!(matches!(
            WidGen::new(4, 0, Some("invalid scope".to_string())),
            Err(WidError::InvalidScope)
        ));
    }

    #[test]
    fn test_generator_monotonic() {
        let mut generator = WidGen::new(4, 0, None).expect("valid constructor args");
        let wid1 = generator.next_wid();
        let wid2 = generator.next_wid();
        assert!(wid1 < wid2);
    }

    #[test]
    fn test_iterator_take() {
        let generator = WidGen::new(4, 6, None).unwrap();
        let v: Vec<String> = generator.take(5).collect();
        assert_eq!(v.len(), 5);
    }

    #[test]
    fn test_parse_valid_wids() {
        let p = parse_wid("20260212T091530.0042Z", 4, 0).unwrap();
        assert_eq!(p.sequence, 42);
        assert_eq!(p.padding, None);

        let p2 = parse_wid("20260212T091530.0042Z-a3f91c", 4, 6).unwrap();
        assert_eq!(p2.sequence, 42);
        assert_eq!(p2.padding.as_deref(), Some("a3f91c"));
        assert_eq!(p2.timestamp_sec(), p2.timestamp.timestamp());

        let p3 =
            parse_wid_with_unit("20260212T091530123.0042Z-a3f91c", 4, 6, TimeUnit::Ms).unwrap();
        assert_eq!(p3.sequence, 42);
        assert_eq!(p3.timestamp.timestamp_subsec_millis(), 123);
    }

    #[test]
    fn test_parse_invalid_cases() {
        assert!(matches!(
            parse_wid("waldiez", 4, 6),
            Err(WidError::InvalidFormat(_))
        ));
        assert!(matches!(
            parse_wid("20260212T091530.0000Z-ABCDEF", 4, 6),
            Err(WidError::InvalidFormat(_))
        ));
        assert!(matches!(
            parse_wid("20260212T091530.0000Z-node01", 4, 0),
            Err(WidError::InvalidFormat(_))
        ));
        assert!(matches!(
            parse_wid("20260232T091530.0000Z", 4, 0),
            Err(WidError::InvalidTimestamp)
        ));
        assert!(matches!(
            parse_wid("20260212T091530.0000Z", 0, 0),
            Err(WidError::InvalidW)
        ));
    }

    #[test]
    fn test_state_restore_and_next_n() {
        let mut g1 = WidGen::new(4, 0, None).unwrap();
        let _ = g1.next_wid();
        let _ = g1.next_wid();
        let (last_tick, last_seq) = g1.state();

        let mut g2 = WidGen::new(4, 0, None).unwrap();
        g2.restore_state(last_tick, last_seq);
        let w = g2.next_wid();
        let p = parse_wid(&w, 4, 0).unwrap();
        assert_eq!(p.sequence as i64, last_seq + 1);

        let v = g2.next_n(3);
        assert_eq!(v.len(), 3);
    }

    #[test]
    fn test_default_params_and_scope_rejected() {
        let mut g = WidGen::default_params();
        let w = g.next_wid();
        assert!(validate_wid(&w, 4, 6));
        assert!(matches!(
            WidGen::new(4, 6, Some("acme".to_string())),
            Err(WidError::InvalidScope)
        ));
    }

    #[test]
    fn test_ms_generator_shape() {
        let mut g = WidGen::new_with_time_unit(4, 0, None, TimeUnit::Ms).unwrap();
        let w = g.next_wid();
        assert!(validate_wid_with_unit(&w, 4, 0, TimeUnit::Ms));
    }
}
