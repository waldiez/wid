//! Async convenience API built on top of sync generators.

use crate::{HLCWidGen, TimeUnit, WidError, WidGen};

/// Get one WID in async contexts.
pub async fn async_next_wid(w: usize, z: usize, time_unit: TimeUnit) -> Result<String, WidError> {
    let mut generator = WidGen::new_with_time_unit(w, z, None, time_unit)?;
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

/// Generate a finite async stream of WIDs as a vector.
pub async fn async_wid_stream(
    count: usize,
    w: usize,
    z: usize,
    time_unit: TimeUnit,
) -> Result<Vec<String>, WidError> {
    let mut generator = WidGen::new_with_time_unit(w, z, None, time_unit)?;
    Ok((0..count).map(|_| generator.next_wid()).collect())
}

/// Generate a finite async stream of HLC-WIDs as a vector.
pub async fn async_hlc_wid_stream(
    node: &str,
    count: usize,
    w: usize,
    z: usize,
    time_unit: TimeUnit,
) -> Result<Vec<String>, WidError> {
    let mut generator = HLCWidGen::new_with_time_unit(node.to_string(), w, z, time_unit)?;
    Ok((0..count).map(|_| generator.next_hlc_wid()).collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{validate_hlc_wid_with_unit, validate_wid_with_unit};
    use futures::executor::block_on;

    #[test]
    fn async_next_wid_ms_is_valid() {
        let wid = block_on(async_next_wid(4, 0, TimeUnit::Ms)).unwrap();
        assert!(validate_wid_with_unit(&wid, 4, 0, TimeUnit::Ms));
    }

    #[test]
    fn async_next_hlc_ms_is_valid() {
        let wid = block_on(async_next_hlc_wid("node01", 4, 0, TimeUnit::Ms)).unwrap();
        assert!(validate_hlc_wid_with_unit(&wid, 4, 0, TimeUnit::Ms));
    }

    #[test]
    fn async_wid_stream_count_matches() {
        let values = block_on(async_wid_stream(3, 4, 0, TimeUnit::Sec)).unwrap();
        assert_eq!(values.len(), 3);
        assert!(values[0] < values[1]);
        assert!(values[1] < values[2]);
    }

    #[test]
    fn async_hlc_stream_count_matches() {
        let values = block_on(async_hlc_wid_stream("node01", 2, 4, 0, TimeUnit::Sec)).unwrap();
        assert_eq!(values.len(), 2);
        assert!(values.iter().all(|v| v.contains("-node01")));
    }
}
