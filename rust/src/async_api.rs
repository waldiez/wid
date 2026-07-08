//! Async API built on top of sync generators.
//!
//! Single-shot helpers ([`async_next_wid`], [`async_next_hlc_wid`]) return a
//! `Future` that can be awaited in any async runtime.
//!
//! Stream helpers ([`async_wid_stream`], [`async_hlc_wid_stream`]) return a
//! [`futures::stream::Stream`] that yields WIDs with an optional configurable
//! interval between emissions (backed by `tokio::time::Sleep`).

use std::pin::Pin;
use std::task::{Context, Poll};

use futures::stream::Stream;

use crate::{HLCWidGen, TimeUnit, WidError, WidGen};

// ── Single-shot helpers ────────────────────────────────────────────────

/// Get one WID in async contexts.
pub async fn async_next_wid(w: usize, z: usize, time_unit: TimeUnit) -> Result<String, WidError> {
    let mut generator = WidGen::new_with_time_unit(w, z, time_unit)?;
    Ok(generator.next_wid())
}

/// Get one HLC-WID in async contexts.
pub async fn async_next_hlc_wid(
    node: &str,
    w: usize,
    z: usize,
    time_unit: TimeUnit,
) -> Result<String, WidError> {
    let mut generator = HLCWidGen::new_with_time_unit(node.to_string(), w, z, time_unit)?;
    Ok(generator.next_hlc_wid())
}

// ── WID async stream ────────────────────────────────────────────────────

/// Configuration for [`AsyncWidStream`].
///
/// This is a convenience builder; use [`async_wid_stream`] directly for
/// the simplest case.
#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct AsyncWidStreamConfig {
    /// Number of WIDs to emit (0 = unbounded).
    pub count: usize,
    /// Width of the sequence segment (default 4).
    pub w: usize,
    /// Padding length (default 6).
    pub z: usize,
    /// Time unit precision, either `Sec` or `Ms`.
    pub time_unit: TimeUnit,
    /// Delay between emissions in milliseconds (0 = back-to-back).
    pub interval_ms: u64,
}

impl Default for AsyncWidStreamConfig {
    fn default() -> Self {
        Self {
            count: 0,
            w: 4,
            z: 6,
            time_unit: TimeUnit::Sec,
            interval_ms: 0,
        }
    }
}

/// An async stream of WIDs, implementing [`Stream<Item = String>`].
///
/// Create via [`async_wid_stream`].
pub struct AsyncWidStream {
    generator: WidGen,
    remaining: usize,
    interval_ms: u64,
    sleep: Option<Pin<Box<tokio::time::Sleep>>>,
    next_due: Option<std::time::Instant>,
}

impl Stream for AsyncWidStream {
    type Item = String;

    fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        // Check if bounded stream is exhausted.
        if self.remaining == 0 {
            return Poll::Ready(None);
        }

        // If a sleep is pending, poll it.
        if let Some(ref mut sleep) = self.sleep {
            match sleep.as_mut().poll(cx) {
                Poll::Pending => return Poll::Pending,
                Poll::Ready(()) => {
                    self.sleep = None;
                }
            }
        }

        let id = self.generator.next_wid();

        // Track remaining for bounded streams.
        if self.remaining != usize::MAX {
            self.remaining -= 1;
        }

        // Schedule the next interval sleep if configured.
        if self.interval_ms > 0 && self.remaining > 0 {
            let due = self.next_due.unwrap_or_else(std::time::Instant::now);
            let next = due + std::time::Duration::from_millis(self.interval_ms);
            self.next_due = Some(next);
            self.sleep = Some(Box::pin(tokio::time::sleep_until(next.into())));
        }

        Poll::Ready(Some(id))
    }
}

/// Create an async WID stream.
///
/// # Example
///
/// ```no_run
/// # use wid::{async_wid_stream, TimeUnit};
/// # use futures::StreamExt;
/// #
/// # async fn example() -> Result<(), wid::WidError> {
/// let mut stream = async_wid_stream(10, 4, 6, TimeUnit::Sec, 0)?;
/// while let Some(id) = stream.next().await {
///     println!("{id}");
/// }
/// # Ok(())
/// # }
/// ```
pub fn async_wid_stream(
    count: usize,
    w: usize,
    z: usize,
    time_unit: TimeUnit,
    interval_ms: u64,
) -> Result<AsyncWidStream, WidError> {
    let generator = WidGen::new_with_time_unit(w, z, time_unit)?;
    let remaining = if count == 0 { usize::MAX } else { count };
    Ok(AsyncWidStream {
        generator,
        remaining,
        interval_ms,
        sleep: None,
        next_due: None,
    })
}

// ── HLC async stream ────────────────────────────────────────────────────

/// Configuration for [`AsyncHlcWidStream`].
#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct AsyncHlcWidStreamConfig {
    /// Node identifier.
    pub node: String,
    /// Number of HLC-WIDs to emit (0 = unbounded).
    pub count: usize,
    /// Width of the logical counter (default 4).
    pub w: usize,
    /// Padding length (default 6).
    pub z: usize,
    /// Time unit precision, either `Sec` or `Ms`.
    pub time_unit: TimeUnit,
    /// Delay between emissions in milliseconds (0 = back-to-back).
    pub interval_ms: u64,
}

/// An async stream of HLC-WIDs, implementing [`Stream<Item = String>`].
///
/// Create via [`async_hlc_wid_stream`].
pub struct AsyncHlcWidStream {
    generator: HLCWidGen,
    remaining: usize,
    interval_ms: u64,
    sleep: Option<Pin<Box<tokio::time::Sleep>>>,
    next_due: Option<std::time::Instant>,
}

impl Stream for AsyncHlcWidStream {
    type Item = String;

    fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        if self.remaining == 0 {
            return Poll::Ready(None);
        }

        if let Some(ref mut sleep) = self.sleep {
            match sleep.as_mut().poll(cx) {
                Poll::Pending => return Poll::Pending,
                Poll::Ready(()) => {
                    self.sleep = None;
                }
            }
        }

        let id = self.generator.next_hlc_wid();

        if self.remaining != usize::MAX {
            self.remaining -= 1;
        }

        if self.interval_ms > 0 && self.remaining > 0 {
            let due = self.next_due.unwrap_or_else(std::time::Instant::now);
            let next = due + std::time::Duration::from_millis(self.interval_ms);
            self.next_due = Some(next);
            self.sleep = Some(Box::pin(tokio::time::sleep_until(next.into())));
        }

        Poll::Ready(Some(id))
    }
}

/// Create an async HLC-WID stream.
pub fn async_hlc_wid_stream(
    node: &str,
    count: usize,
    w: usize,
    z: usize,
    time_unit: TimeUnit,
    interval_ms: u64,
) -> Result<AsyncHlcWidStream, WidError> {
    let generator = HLCWidGen::new_with_time_unit(node.to_string(), w, z, time_unit)?;
    let remaining = if count == 0 { usize::MAX } else { count };
    Ok(AsyncHlcWidStream {
        generator,
        remaining,
        interval_ms,
        sleep: None,
        next_due: None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{validate_hlc_wid_with_unit, validate_wid_with_unit};
    use futures::StreamExt;
    use futures::executor::block_on;

    #[test]
    fn async_next_wid_sec_is_valid() {
        let wid = block_on(async_next_wid(4, 0, TimeUnit::Sec)).unwrap();
        assert!(validate_wid_with_unit(&wid, 4, 0, TimeUnit::Sec));
    }

    #[test]
    fn async_next_wid_ms_is_valid() {
        let wid = block_on(async_next_wid(4, 0, TimeUnit::Ms)).unwrap();
        assert!(validate_wid_with_unit(&wid, 4, 0, TimeUnit::Ms));
    }

    #[test]
    fn async_next_hlc_sec_is_valid() {
        let wid = block_on(async_next_hlc_wid("node01", 4, 0, TimeUnit::Sec)).unwrap();
        assert!(validate_hlc_wid_with_unit(&wid, 4, 0, TimeUnit::Sec));
    }

    #[test]
    fn async_next_hlc_ms_is_valid() {
        let wid = block_on(async_next_hlc_wid("node01", 4, 0, TimeUnit::Ms)).unwrap();
        assert!(validate_hlc_wid_with_unit(&wid, 4, 0, TimeUnit::Ms));
    }

    #[test]
    fn async_wid_stream_count_matches() {
        let stream = async_wid_stream(3, 4, 0, TimeUnit::Sec, 0).unwrap();
        let values: Vec<String> = block_on(stream.collect());
        assert_eq!(values.len(), 3);
        assert!(values[0] < values[1]);
        assert!(values[1] < values[2]);
    }

    #[test]
    fn async_wid_stream_unbounded_take() {
        let stream = async_wid_stream(0, 4, 0, TimeUnit::Sec, 0).unwrap();
        let values: Vec<String> = block_on(stream.take(5).collect());
        assert_eq!(values.len(), 5);
        assert!(
            values
                .iter()
                .all(|v| validate_wid_with_unit(v, 4, 0, TimeUnit::Sec))
        );
    }

    #[test]
    fn async_hlc_stream_count_matches() {
        let stream = async_hlc_wid_stream("node01", 2, 4, 0, TimeUnit::Sec, 0).unwrap();
        let values: Vec<String> = block_on(stream.collect());
        assert_eq!(values.len(), 2);
        assert!(values.iter().all(|v| v.contains("-node01")));
    }

    #[test]
    fn async_hlc_stream_unbounded_take() {
        let stream = async_hlc_wid_stream("node01", 0, 4, 6, TimeUnit::Sec, 0).unwrap();
        let values: Vec<String> = block_on(stream.take(3).collect());
        assert_eq!(values.len(), 3);
    }

    #[test]
    fn async_wid_stream_invalid_params() {
        assert!(async_wid_stream(1, 0, 0, TimeUnit::Sec, 0).is_err());
        assert!(async_wid_stream(1, 4, 65, TimeUnit::Sec, 0).is_err());
    }

    #[test]
    fn async_hlc_stream_invalid_params() {
        assert!(async_hlc_wid_stream("bad-node", 1, 4, 0, TimeUnit::Sec, 0).is_err());
        assert!(async_hlc_wid_stream("node01", 1, 0, 0, TimeUnit::Sec, 0).is_err());
    }
}
