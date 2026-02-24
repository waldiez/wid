//! SYNAPSE Manifest-Based Binary Files.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use thiserror::Error;

/// Fixed magic bytes that prefix every SYNAPSE manifest file.
pub const MANIFEST_MAGIC: &[u8; 4] = b"SYNM";
/// Current manifest version baked into every file.
pub const MANIFEST_VERSION: u16 = 1;
/// Maximum payload bytes that a manifest may declare.
pub const MAX_MANIFEST_SIZE: usize = 64 * 1024;
const HEADER_SIZE: usize = 10;

#[derive(Error, Debug)]
/// Errors that can occur while reading or validating manifests.
pub enum ManifestError {
    #[error("Invalid magic bytes")]
    InvalidMagic,
    #[error("Manifest too large: {0} bytes")]
    ManifestTooLarge(usize),
    #[error("Data too small for SYNAPSE file")]
    DataTooSmall,
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
/// Supported MIME-like types stored inside manifests.
pub enum DataType {
    #[default]
    #[serde(rename = "unknown")]
    Unknown,
    #[serde(rename = "text/plain")]
    Text,
    #[serde(rename = "application/json")]
    Json,
    #[serde(rename = "application/octet-stream")]
    Binary,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
/// Manifest metadata container with serialization helpers.
pub struct Manifest {
    pub id: String,
    #[serde(default = "default_version")]
    pub version: u16,
    #[serde(default)]
    pub node: String,
    #[serde(default)]
    pub data_type: String,
    #[serde(default)]
    pub data_size: usize,
    #[serde(default)]
    pub data_hash: String,
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub metadata: HashMap<String, serde_json::Value>,
}

fn default_version() -> u16 {
    MANIFEST_VERSION
}

impl Manifest {
    pub fn new(id: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            version: MANIFEST_VERSION,
            node: String::new(),
            data_type: "unknown".to_string(),
            data_size: 0,
            data_hash: String::new(),
            metadata: HashMap::new(),
        }
    }

    pub fn to_json(&self) -> Result<String, ManifestError> {
        Ok(serde_json::to_string_pretty(self)?)
    }

    pub fn from_json(data: &str) -> Result<Self, ManifestError> {
        Ok(serde_json::from_str(data)?)
    }
}

/// Combined manifest payload used for SYNAPSE file blobs.
pub struct SynapseFile {
    pub manifest: Manifest,
    pub payload: Vec<u8>,
}

impl SynapseFile {
    pub fn new(manifest: Manifest, payload: Vec<u8>) -> Self {
        Self { manifest, payload }
    }

    pub fn to_bytes(&mut self) -> Result<Vec<u8>, ManifestError> {
        self.manifest.data_size = self.payload.len();
        let hash = Sha256::digest(&self.payload);
        self.manifest.data_hash = hex::encode(hash);

        let manifest_bytes = self.manifest.to_json()?.into_bytes();
        if manifest_bytes.len() > MAX_MANIFEST_SIZE {
            return Err(ManifestError::ManifestTooLarge(manifest_bytes.len()));
        }

        let mut result =
            Vec::with_capacity(HEADER_SIZE + manifest_bytes.len() + self.payload.len());
        result.extend_from_slice(MANIFEST_MAGIC);
        result.extend_from_slice(&MANIFEST_VERSION.to_be_bytes());
        result.extend_from_slice(&(manifest_bytes.len() as u32).to_be_bytes());
        result.extend_from_slice(&manifest_bytes);
        result.extend_from_slice(&self.payload);
        Ok(result)
    }

    pub fn from_bytes(data: &[u8]) -> Result<Self, ManifestError> {
        if data.len() < HEADER_SIZE {
            return Err(ManifestError::DataTooSmall);
        }
        if &data[0..4] != MANIFEST_MAGIC {
            return Err(ManifestError::InvalidMagic);
        }
        let manifest_size = u32::from_be_bytes([data[6], data[7], data[8], data[9]]) as usize;
        if manifest_size > MAX_MANIFEST_SIZE {
            return Err(ManifestError::ManifestTooLarge(manifest_size));
        }
        let manifest_end = HEADER_SIZE + manifest_size;
        if manifest_end > data.len() {
            return Err(ManifestError::DataTooSmall);
        }
        let manifest_str = std::str::from_utf8(&data[HEADER_SIZE..manifest_end]).map_err(|e| {
            ManifestError::Io(std::io::Error::new(std::io::ErrorKind::InvalidData, e))
        })?;
        let manifest = Manifest::from_json(manifest_str)?;
        let payload = data[manifest_end..].to_vec();
        Ok(Self { manifest, payload })
    }

    pub fn save(&mut self, path: &Path, embed: bool) -> Result<(), ManifestError> {
        if embed {
            fs::write(path, self.to_bytes()?)?;
        } else {
            fs::write(path, &self.payload)?;
            let ext = path.extension().unwrap_or_default().to_string_lossy();
            let manifest_path = path.with_extension(format!("{}.manifest.json", ext));
            fs::write(manifest_path, self.manifest.to_json()?)?;
        }
        Ok(())
    }

    pub fn load(path: &Path) -> Result<Self, ManifestError> {
        let data = fs::read(path)?;
        if data.len() >= 4 && &data[0..4] == MANIFEST_MAGIC {
            return Self::from_bytes(&data);
        }
        let ext = path.extension().unwrap_or_default().to_string_lossy();
        let manifest_path = path.with_extension(format!("{}.manifest.json", ext));
        if manifest_path.exists() {
            let manifest = Manifest::from_json(&fs::read_to_string(manifest_path)?)?;
            return Ok(Self {
                manifest,
                payload: data,
            });
        }
        let hash = hex::encode(Sha256::digest(&data));
        Ok(Self {
            manifest: Manifest {
                id: path
                    .file_stem()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .to_string(),
                data_size: data.len(),
                data_hash: hash,
                ..Manifest::new("")
            },
            payload: data,
        })
    }

    pub fn verify(&self) -> bool {
        let hash = hex::encode(Sha256::digest(&self.payload));
        hash == self.manifest.data_hash
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn tmp_path(name: &str) -> PathBuf {
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "wid_manifest_{}_{}_{}",
            std::process::id(),
            ts,
            name
        ))
    }

    #[test]
    fn test_roundtrip() {
        let mut sf = SynapseFile::new(Manifest::new("test-id"), b"Hello!".to_vec());
        let bytes = sf.to_bytes().unwrap();
        let loaded = SynapseFile::from_bytes(&bytes).unwrap();
        assert_eq!(loaded.manifest.id, "test-id");
        assert!(loaded.verify());
    }

    #[test]
    fn test_manifest_json_roundtrip() {
        let mut m = Manifest::new("abc");
        m.node = "n1".to_string();
        m.metadata
            .insert("k".to_string(), serde_json::Value::String("v".to_string()));
        let json = m.to_json().unwrap();
        let parsed = Manifest::from_json(&json).unwrap();
        assert_eq!(parsed.id, "abc");
        assert_eq!(parsed.node, "n1");
        assert_eq!(parsed.version, MANIFEST_VERSION);
        assert!(parsed.metadata.contains_key("k"));
    }

    #[test]
    fn test_from_bytes_rejects_too_small_and_bad_magic() {
        assert!(matches!(
            SynapseFile::from_bytes(b"123"),
            Err(ManifestError::DataTooSmall)
        ));

        let bad = vec![b'B', b'A', b'D', b'!', 0, 1, 0, 0, 0, 0];
        assert!(matches!(
            SynapseFile::from_bytes(&bad),
            Err(ManifestError::InvalidMagic)
        ));
    }

    #[test]
    fn test_from_bytes_rejects_manifest_size_too_large() {
        let mut buf = Vec::new();
        buf.extend_from_slice(MANIFEST_MAGIC);
        buf.extend_from_slice(&MANIFEST_VERSION.to_be_bytes());
        buf.extend_from_slice(&((MAX_MANIFEST_SIZE as u32) + 1).to_be_bytes());
        assert!(matches!(
            SynapseFile::from_bytes(&buf),
            Err(ManifestError::ManifestTooLarge(_))
        ));
    }

    #[test]
    fn test_from_bytes_rejects_truncated_manifest_body() {
        let mut buf = Vec::new();
        buf.extend_from_slice(MANIFEST_MAGIC);
        buf.extend_from_slice(&MANIFEST_VERSION.to_be_bytes());
        buf.extend_from_slice(&10u32.to_be_bytes()); // claim 10-byte manifest
        buf.extend_from_slice(b"{}"); // but only 2 bytes available
        assert!(matches!(
            SynapseFile::from_bytes(&buf),
            Err(ManifestError::DataTooSmall)
        ));
    }

    #[test]
    fn test_to_bytes_rejects_oversized_manifest() {
        let mut m = Manifest::new("big");
        m.metadata.insert(
            "huge".to_string(),
            serde_json::Value::String("x".repeat(MAX_MANIFEST_SIZE + 1024)),
        );
        let mut sf = SynapseFile::new(m, b"payload".to_vec());
        assert!(matches!(
            sf.to_bytes(),
            Err(ManifestError::ManifestTooLarge(_))
        ));
    }

    #[test]
    fn test_save_load_embed() {
        let path = tmp_path("embed.syn");
        let mut sf = SynapseFile::new(Manifest::new("embed-id"), b"embed".to_vec());
        sf.save(&path, true).unwrap();

        let loaded = SynapseFile::load(&path).unwrap();
        assert_eq!(loaded.manifest.id, "embed-id");
        assert_eq!(loaded.payload, b"embed");
        assert!(loaded.verify());

        let _ = fs::remove_file(path);
    }

    #[test]
    fn test_save_load_sidecar_manifest() {
        let path = tmp_path("sidecar.bin");
        let mut sf = SynapseFile::new(Manifest::new("sidecar-id"), b"data".to_vec());
        sf.manifest.node = "node01".to_string();
        sf.save(&path, false).unwrap();

        let loaded = SynapseFile::load(&path).unwrap();
        assert_eq!(loaded.manifest.id, "sidecar-id");
        assert_eq!(loaded.manifest.node, "node01");
        assert_eq!(loaded.payload, b"data");

        let ext = path.extension().unwrap_or_default().to_string_lossy();
        let manifest_path = path.with_extension(format!("{}.manifest.json", ext));
        let _ = fs::remove_file(path);
        let _ = fs::remove_file(manifest_path);
    }

    #[test]
    fn test_load_raw_without_manifest_derives_defaults() {
        let path = tmp_path("plain.txt");
        fs::write(&path, b"plain-payload").unwrap();

        let loaded = SynapseFile::load(&path).unwrap();
        assert_eq!(loaded.payload, b"plain-payload");
        assert!(loaded.manifest.id.ends_with("_plain"));
        assert_eq!(loaded.manifest.data_size, b"plain-payload".len());
        assert!(loaded.verify());

        let _ = fs::remove_file(path);
    }

    #[test]
    fn test_verify_false_on_payload_tamper() {
        let mut sf = SynapseFile::new(Manifest::new("x"), b"orig".to_vec());
        let bytes = sf.to_bytes().unwrap();
        let mut loaded = SynapseFile::from_bytes(&bytes).unwrap();
        loaded.payload = b"tampered".to_vec();
        assert!(!loaded.verify());
    }
}
