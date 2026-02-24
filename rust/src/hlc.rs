//! HLC-WID generation and validation.
//!
//! Format: `YYYYMMDDTHHMMSS[mmm].<lcW>Z-<node>[-<padZ>]`

use chrono::{DateTime, TimeZone, Timelike, Utc};
use once_cell::sync::Lazy;
use rand::random_range;
use regex::Regex;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::wid::{TimeUnit, WidError};

/// Parsed HLC-WID components.
#[derive(Debug, Clone, PartialEq)]
pub struct ParsedHlcWid {
    pub raw: String,
    pub timestamp: DateTime<Utc>,
    pub logical_counter: u32,
    pub node: String,
    pub padding: Option<String>,
}

static HLC_PATTERN_W4_Z0_SEC: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^(\d{8})T(\d{6})\.(\d{4})Z-([A-Za-z0-9_]+)$").unwrap());

fn build_pattern(w: usize, z: usize, time_unit: TimeUnit) -> Regex {
    let lc_part = format!(r"(\d{{{}}})", w);
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
        r"^(\d{{8}})T(\d{{{}}})\.{}Z-([A-Za-z0-9_]+){}",
        time_digits, lc_part, pad_part
    );
    Regex::new(&pattern).unwrap()
}

fn parse_ts(time_unit: TimeUnit, date_str: &str, time_str: &str) -> Option<DateTime<Utc>> {
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

fn is_valid_node(node: &str) -> bool {
    !node.is_empty() && node.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

/// Validate a HLC-WID string for a specific time unit.
pub fn validate_hlc_wid_with_unit(wid: &str, w: usize, z: usize, time_unit: TimeUnit) -> bool {
    parse_hlc_wid_with_unit(wid, w, z, time_unit).is_ok()
}

/// Validate a HLC-WID string in `sec` mode.
pub fn validate_hlc_wid(wid: &str, w: usize, z: usize) -> bool {
    validate_hlc_wid_with_unit(wid, w, z, TimeUnit::Sec)
}

/// Parse an HLC-WID string into its components for a specific time unit.
pub fn parse_hlc_wid_with_unit(
    wid: &str,
    w: usize,
    z: usize,
    time_unit: TimeUnit,
) -> Result<ParsedHlcWid, WidError> {
    if w == 0 {
        return Err(WidError::InvalidW);
    }

    let pattern = if w == 4 && z == 0 && time_unit == TimeUnit::Sec {
        &*HLC_PATTERN_W4_Z0_SEC
    } else {
        &build_pattern(w, z, time_unit)
    };

    let caps = pattern
        .captures(wid)
        .ok_or_else(|| WidError::InvalidFormat(wid.to_string()))?;

    let date_str = &caps[1];
    let time_str = &caps[2];
    let lc_str = &caps[3];
    let node = caps[4].to_string();
    let padding = if z > 0 {
        caps.get(5).map(|m| m.as_str().to_string())
    } else {
        None
    };

    if !is_valid_node(&node) {
        return Err(WidError::InvalidNode);
    }

    let timestamp = parse_ts(time_unit, date_str, time_str).ok_or(WidError::InvalidTimestamp)?;
    let logical_counter: u32 = lc_str
        .parse()
        .map_err(|_| WidError::InvalidFormat(wid.to_string()))?;

    Ok(ParsedHlcWid {
        raw: wid.to_string(),
        timestamp,
        logical_counter,
        node,
        padding,
    })
}

/// Parse an HLC-WID string in `sec` mode.
pub fn parse_hlc_wid(wid: &str, w: usize, z: usize) -> Result<ParsedHlcWid, WidError> {
    parse_hlc_wid_with_unit(wid, w, z, TimeUnit::Sec)
}

/// HLC generator state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HLCState {
    pub pt: i64,
    pub lc: i64,
}

/// HLC-WID generator.
pub struct HLCWidGen {
    w: usize,
    z: usize,
    time_unit: TimeUnit,
    node: String,
    max_lc: i64,
    pt: i64,
    lc: i64,
    cached_tick: i64,
    cached_ts: String,
}

impl HLCWidGen {
    /// Create a new HLC-WID generator in `sec` mode.
    pub fn new(node: String, w: usize, z: usize) -> Result<Self, WidError> {
        Self::new_with_time_unit(node, w, z, TimeUnit::Sec)
    }

    /// Create a new HLC-WID generator with a chosen time unit.
    pub fn new_with_time_unit(
        node: String,
        w: usize,
        z: usize,
        time_unit: TimeUnit,
    ) -> Result<Self, WidError> {
        if w == 0 {
            return Err(WidError::InvalidW);
        }
        if !is_valid_node(&node) {
            return Err(WidError::InvalidNode);
        }

        Ok(Self {
            w,
            z,
            time_unit,
            node,
            max_lc: 10_i64.pow(w as u32) - 1,
            pt: 0,
            lc: 0,
            cached_tick: -1,
            cached_ts: String::new(),
        })
    }

    fn current_tick(time_unit: TimeUnit) -> i64 {
        let dur = SystemTime::now().duration_since(UNIX_EPOCH).unwrap();
        match time_unit {
            TimeUnit::Sec => dur.as_secs() as i64,
            TimeUnit::Ms => dur.as_millis() as i64,
        }
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

    fn rollover_if_needed(&mut self) {
        if self.lc > self.max_lc {
            self.pt += 1;
            self.lc = 0;
        }
    }

    /// Merge remote HLC state.
    pub fn observe(&mut self, remote_pt: i64, remote_lc: i64) -> Result<(), WidError> {
        if remote_pt < 0 || remote_lc < 0 {
            return Err(WidError::InvalidRemoteClock);
        }

        let now = Self::current_tick(self.time_unit);
        let new_pt = now.max(self.pt).max(remote_pt);

        if new_pt == self.pt && new_pt == remote_pt {
            self.lc = self.lc.max(remote_lc) + 1;
        } else if new_pt == self.pt {
            self.lc += 1;
        } else if new_pt == remote_pt {
            self.lc = remote_lc + 1;
        } else {
            self.lc = 0;
        }

        self.pt = new_pt;
        self.rollover_if_needed();
        Ok(())
    }

    /// Generate the next HLC-WID.
    pub fn next_hlc_wid(&mut self) -> String {
        let now = Self::current_tick(self.time_unit);
        if now > self.pt {
            self.pt = now;
            self.lc = 0;
        } else {
            self.lc += 1;
        }
        self.rollover_if_needed();

        let ts = self.ts_for_tick(self.pt).to_string();
        let lc_str = format!("{:0width$}", self.lc, width = self.w);
        let mut wid = format!("{}.{}Z-{}", ts, lc_str, self.node);

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

    /// Generate n HLC-WIDs.
    pub fn next_n(&mut self, n: usize) -> Vec<String> {
        self.take(n).collect()
    }

    /// Get current state.
    pub fn state(&self) -> HLCState {
        HLCState {
            pt: self.pt,
            lc: self.lc,
        }
    }

    /// Restore state.
    pub fn restore_state(&mut self, pt: i64, lc: i64) -> Result<(), WidError> {
        if pt < 0 || lc < 0 {
            return Err(WidError::InvalidRemoteClock);
        }
        self.pt = pt;
        self.lc = lc;
        Ok(())
    }

    /// Active time unit.
    pub fn time_unit(&self) -> TimeUnit {
        self.time_unit
    }
}

impl Iterator for HLCWidGen {
    type Item = String;

    fn next(&mut self) -> Option<Self::Item> {
        Some(self.next_hlc_wid())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validate_hlc_valid() {
        assert!(validate_hlc_wid("20260212T091530.0000Z-node01", 4, 0));
        assert!(validate_hlc_wid(
            "20260212T091530.0042Z-node01-a3f91c",
            4,
            6
        ));
        assert!(validate_hlc_wid_with_unit(
            "20260212T091530123.0042Z-node01-a3f91c",
            4,
            6,
            TimeUnit::Ms
        ));
    }

    #[test]
    fn test_validate_hlc_invalid() {
        assert!(!validate_hlc_wid("20260212T091530.0000Z", 4, 0));
        assert!(!validate_hlc_wid("20260212T091530.0000Z-node-01", 4, 0));
        assert!(!validate_hlc_wid(
            "20260212T091530.0000Z-node01-ABCDEF",
            4,
            6
        ));
    }

    #[test]
    fn test_parse_hlc() {
        let p = parse_hlc_wid("20260212T091530.0042Z-node01-a3f91c", 4, 6).unwrap();
        assert_eq!(p.node, "node01");
        assert_eq!(p.logical_counter, 42);
        assert_eq!(p.padding.as_deref(), Some("a3f91c"));

        let p2 =
            parse_hlc_wid_with_unit("20260212T091530123.0042Z-node01-a3f91c", 4, 6, TimeUnit::Ms)
                .unwrap();
        assert_eq!(p2.timestamp.timestamp_subsec_millis(), 123);
    }

    #[test]
    fn test_hlc_monotonic() {
        let mut g = HLCWidGen::new("node01".to_string(), 4, 0).unwrap();
        let a = g.next_hlc_wid();
        let b = g.next_hlc_wid();
        assert!(a < b);
    }

    #[test]
    fn test_hlc_observe() {
        let mut g = HLCWidGen::new("node01".to_string(), 4, 0).unwrap();
        g.observe(10, 5).unwrap();
        let s = g.state();
        assert!(s.pt >= 10);
    }

    #[test]
    fn test_new_rejects_invalid_node_and_w() {
        assert!(matches!(
            HLCWidGen::new("bad-node".to_string(), 4, 0),
            Err(WidError::InvalidNode)
        ));
        assert!(matches!(
            HLCWidGen::new("node01".to_string(), 0, 0),
            Err(WidError::InvalidW)
        ));
    }

    #[test]
    fn test_observe_invalid_remote_clock() {
        let mut g = HLCWidGen::new("node01".to_string(), 4, 0).unwrap();
        assert!(matches!(
            g.observe(-1, 0),
            Err(WidError::InvalidRemoteClock)
        ));
        assert!(matches!(
            g.observe(0, -1),
            Err(WidError::InvalidRemoteClock)
        ));
    }

    #[test]
    fn test_restore_state_invalid() {
        let mut g = HLCWidGen::new("node01".to_string(), 4, 0).unwrap();
        assert!(matches!(
            g.restore_state(-1, 0),
            Err(WidError::InvalidRemoteClock)
        ));
        assert!(matches!(
            g.restore_state(0, -1),
            Err(WidError::InvalidRemoteClock)
        ));
    }

    #[test]
    fn test_next_with_padding_and_next_n() {
        let mut g = HLCWidGen::new("node01".to_string(), 4, 6).unwrap();
        let one = g.next_hlc_wid();
        assert!(one.contains("-node01-"));
        let many = g.next_n(3);
        assert_eq!(many.len(), 3);
        assert!(many[0] < many[1]);
    }

    #[test]
    fn test_parse_hlc_invalid_timestamp() {
        assert!(matches!(
            parse_hlc_wid("20261312T091530.0000Z-node01", 4, 0),
            Err(WidError::InvalidTimestamp)
        ));
    }

    #[test]
    fn test_non_default_w_z_pattern_paths() {
        assert!(validate_hlc_wid("20260212T091530.00042Z-node01-ab", 5, 2));
        let p = parse_hlc_wid("20260212T091530.00042Z-node01-ab", 5, 2).unwrap();
        assert_eq!(p.logical_counter, 42);
        assert_eq!(p.padding.as_deref(), Some("ab"));
    }

    #[test]
    fn test_ms_generator_shape() {
        let mut g =
            HLCWidGen::new_with_time_unit("node01".to_string(), 4, 0, TimeUnit::Ms).unwrap();
        let id = g.next_hlc_wid();
        assert!(validate_hlc_wid_with_unit(&id, 4, 0, TimeUnit::Ms));
    }
}
