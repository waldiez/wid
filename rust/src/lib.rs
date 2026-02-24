//! synapse-wid: WID (Waldiez/SYNAPSE Identifier) generation and manifest utilities.
//!
//! WID is a time-ordered, human-readable, collision-resistant identifier format
//! designed for distributed IoT and agent systems.
//!
//! # Format
//!
//! ```text
//! WID ::= TIMESTAMP "." SEQ "Z" [ "-" PAD ]
//! HLC-WID ::= TIMESTAMP "." LC "Z" "-" NODE [ "-" PAD ]
//! ```
//!
//! # Example
//!
//! ```
//! use wid::WidGen;
//!
//! let mut wid_gen = WidGen::new(4, 6, None).expect("valid default generator params");
//! let wid = wid_gen.next_wid(); // or .next() to get Optional<String>
//! println!("{}", wid);  // e.g., "20260212T091530.0000Z-a3f91c"   // use {:?} if used .next()
//! ```

mod async_api;
mod hlc;
mod manifest;
mod wid;

pub use async_api::{async_hlc_wid_stream, async_next_hlc_wid, async_next_wid, async_wid_stream};
pub use hlc::{
    HLCState, HLCWidGen, ParsedHlcWid, parse_hlc_wid, parse_hlc_wid_with_unit, validate_hlc_wid,
    validate_hlc_wid_with_unit,
};
pub use manifest::{DataType, MANIFEST_MAGIC, MANIFEST_VERSION, Manifest, SynapseFile};
pub use wid::{
    ParsedWid, TimeUnit, WidError, WidGen, parse_wid, parse_wid_with_unit, validate_wid,
    validate_wid_with_unit,
};
