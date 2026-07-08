//! HLC-WID generation and validation.
//!
//! Format: `YYYYMMDDTHHMMSS[mmm].<lcW>Z-<node>[-<padZ>]`

use chrono::{DateTime, Utc};
use rand::random_range;
use regex::Regex;
use std::collections::HashMap;
use std::sync::{LazyLock, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::wid::{TimeUnit, WidError, parse_timestamp};

/// Parsed HLC-WID components.
#[derive(Debug, Clone, PartialEq)]
pub struct ParsedHlcWid {
    /// The original HLC-WID string.
    pub raw: String,
    /// The embedded UTC timestamp.
    pub timestamp: DateTime<Utc>,
    /// i64, not u32: the spec allows W up to 18, and an all-nines W=10
    /// counter (9999999999) already exceeds u32::MAX.
    pub logical_counter: i64,
    /// Node tag identifying the minting writer.
    pub node: String,
    /// Random hex pad (`None` when Z=0).
    pub padding: Option<String>,
}

// [0-9], never \d: \d is Unicode-aware in this regex engine and the captured
// fields are byte-sliced in parse_ts — multi-byte digits would panic there.
// See the matching comment in wid.rs.
static HLC_PATTERN_W4_Z0_SEC: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^([0-9]{8})T([0-9]{6})\.([0-9]{4})Z-([A-Za-z0-9_]+)$").unwrap());

fn build_pattern(w: usize, z: usize, time_unit: TimeUnit) -> Regex {
    let lc_part = format!(r"([0-9]{{{w}}})");
    let time_digits = match time_unit {
        TimeUnit::Sec => 6,
        TimeUnit::Ms => 9,
    };
    let pad_part = if z > 0 {
        format!(r"(?:-([0-9a-f]{{{z}}}))?$")
    } else {
        r"$".to_string()
    };
    let pattern =
        format!(r"^([0-9]{{8}})T([0-9]{{{time_digits}}})\.{lc_part}Z-([A-Za-z0-9_]+){pad_part}");
    Regex::new(&pattern).unwrap()
}

// Timestamp parsing is shared with the plain-WID parser (crate::wid::
// parse_timestamp); this module used to carry an identical private copy.

/// Compiled-pattern cache for non-default shapes; see the matching cache in
/// wid.rs for the rationale (Regex clones share the compiled program).
static HLC_PATTERN_CACHE: crate::wid::PatternCache = LazyLock::new(|| Mutex::new(HashMap::new()));

fn cached_pattern(w: usize, z: usize, time_unit: TimeUnit) -> Regex {
    let mut cache = HLC_PATTERN_CACHE
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    cache
        .entry((w, z, time_unit))
        .or_insert_with(|| build_pattern(w, z, time_unit))
        .clone()
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
    if w == 0 || w > crate::wid::MAX_W {
        return Err(WidError::InvalidW);
    }
    if z > crate::wid::MAX_Z {
        return Err(WidError::InvalidZ);
    }

    let pattern = if w == 4 && z == 0 && time_unit == TimeUnit::Sec {
        HLC_PATTERN_W4_Z0_SEC.clone()
    } else {
        cached_pattern(w, z, time_unit)
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

    let timestamp =
        parse_timestamp(time_unit, date_str, time_str).ok_or(WidError::InvalidTimestamp)?;
    let logical_counter: i64 = lc_str
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
    /// Physical time tick (seconds or milliseconds per the generator's unit).
    pub pt: i64,
    /// Logical counter within the physical tick.
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
        // W > MAX_W would overflow the i64 logical counter (10^19 > i64::MAX).
        if w == 0 || w > crate::wid::MAX_W {
            return Err(WidError::InvalidW);
        }
        if z > crate::wid::MAX_Z {
            return Err(WidError::InvalidZ);
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
        // A pre-1970 system clock yields Err; treat it as tick 0 rather
        // than panicking (the HLC merge logic takes over from there).
        let dur = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default();
        match time_unit {
            TimeUnit::Sec => dur.as_secs() as i64,
            TimeUnit::Ms => dur.as_millis() as i64,
        }
    }

    fn ts_for_tick(&mut self, tick: i64) -> &str {
        // Saturate instead of unwrap-panicking: a corrupted resume state or
        // hostile remote clock could otherwise push the tick out of range.
        let tick = crate::wid::clamp_tick(tick, self.time_unit);
        if tick != self.cached_tick {
            self.cached_tick = tick;
            self.cached_ts = crate::wid::format_tick(tick, self.time_unit);
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
            const HEX: &[u8; 16] = b"0123456789abcdef";
            let pad: String = (0..self.z)
                .map(|_| HEX[random_range(0..16)] as char)
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
        // Year 0000 is outside the spec range 0001-9999.
        assert!(!validate_hlc_wid("00000101T000000.0000Z-node01", 4, 0));
        assert!(!validate_hlc_wid(
            "20260212T091530.0000Z-node01-ABCDEF",
            4,
            6
        ));
    }

    #[test]
    fn test_unicode_digits_rejected_without_panic() {
        // Same regression as wid.rs: Unicode digits must be a clean reject,
        // not a byte-boundary panic in parse_ts.
        assert!(!validate_hlc_wid("२०२६०२१२T०९१५३०.००००Z-node01", 4, 0));
        assert!(matches!(
            parse_hlc_wid("٢٠٢٦٠٢١٢T٠٩١٥٣٠.٠٠٠٠Z-node01", 4, 0),
            Err(WidError::InvalidFormat(_))
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
