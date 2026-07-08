//! Cryptographic CLI actions: Ed25519 sign/verify and WID-bound HMAC-SHA256 OTP
//! (w-otp). The domain-separation message format is shared across all six
//! implementations (spec/CRYPTO_SPEC.md).

use std::fs;
use std::path::Path;

use base64::Engine as _;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use ed25519_dalek::pkcs8::{DecodePrivateKey, DecodePublicKey};
use ed25519_dalek::{Signature, Signer, SigningKey, VerifyingKey};
use hmac::{Hmac, KeyInit, Mac};
use serde_json::json;
use sha2::Sha256;
use subtle::ConstantTimeEq;
use wid::WidGen;

use super::args::CanonOpts;
use super::error::{CliError, fail, usage};

type HmacSha256 = Hmac<Sha256>;

/// Build the canonical sign/verify message entirely in memory:
/// `"wid-sig-v1:" || len(WID) || ":" || WID || DATA`.
///
/// The domain-separation prefix and the explicit WID byte-length frame the
/// WID/DATA boundary so no bytes can shift between them (a plain `WID || DATA`
/// concatenation is ambiguous). No temporary files are created.
pub(crate) fn build_sign_verify_message(c: &CanonOpts) -> Result<Vec<u8>, CliError> {
    if c.wid.trim().is_empty() {
        return Err(usage("WID=<wid_string> required"));
    }
    let wid = c.wid.as_bytes();
    let mut msg = format!("wid-sig-v1:{}:", wid.len()).into_bytes();
    msg.extend_from_slice(wid);
    if !c.data.trim().is_empty() {
        let data =
            fs::read(&c.data).map_err(|_| fail(format!("data file not found: {}", c.data)))?;
        msg.extend_from_slice(&data);
    }
    Ok(msg)
}

fn load_signing_key(path: &str) -> Result<SigningKey, String> {
    let pem =
        fs::read_to_string(path).map_err(|_| format!("private key file not found: {path}"))?;
    SigningKey::from_pkcs8_pem(&pem)
        .map_err(|_| "sign failed (ensure Ed25519 private key PEM)".to_string())
}

fn load_verifying_key(path: &str) -> Result<VerifyingKey, String> {
    let pem = fs::read_to_string(path).map_err(|_| format!("public key file not found: {path}"))?;
    VerifyingKey::from_public_key_pem(&pem)
        .map_err(|_| "invalid public key (ensure Ed25519 public key PEM)".to_string())
}

pub(crate) fn run_sign(c: &CanonOpts) -> Result<(), CliError> {
    if c.key.trim().is_empty() {
        return Err(usage("KEY=<private_key_path> required for A=sign"));
    }
    if !Path::new(&c.key).exists() {
        return Err(fail(format!("private key file not found: {}", c.key)));
    }
    let msg = build_sign_verify_message(c)?;
    let key = load_signing_key(&c.key).map_err(fail)?;
    let sig: Signature = key.sign(&msg);
    let encoded = URL_SAFE_NO_PAD.encode(sig.to_bytes());
    if c.out.trim().is_empty() {
        println!("{encoded}");
    } else {
        fs::write(&c.out, encoded.as_bytes())
            .map_err(|e| fail(format!("failed to write OUT file: {e}")))?;
    }
    Ok(())
}

pub(crate) fn run_verify(c: &CanonOpts) -> Result<(), CliError> {
    if c.key.trim().is_empty() {
        return Err(usage("KEY=<public_key_path> required for A=verify"));
    }
    if c.sig.trim().is_empty() {
        return Err(usage("SIG=<signature_string> required for A=verify"));
    }
    if !Path::new(&c.key).exists() {
        return Err(fail(format!("public key file not found: {}", c.key)));
    }
    let msg = build_sign_verify_message(c)?;
    let key = load_verifying_key(&c.key).map_err(fail)?;
    // Accept base64url with or without padding.
    let sig_bytes = URL_SAFE_NO_PAD
        .decode(c.sig.trim().trim_end_matches('='))
        .map_err(|_| fail("invalid signature encoding"))?;
    let sig = Signature::from_slice(&sig_bytes).map_err(|_| fail("invalid signature encoding"))?;
    match key.verify_strict(&msg, &sig) {
        Ok(()) => {
            println!("Signature valid.");
            Ok(())
        }
        Err(_) => Err(fail("Signature invalid.")),
    }
}

/// Resolve `KEY=` to the secret: file contents if a file with that exact
/// name exists, else the literal value. Emptiness is checked by the caller
/// (an empty result is a usage error, a read failure an operational one).
fn resolve_wotp_secret(raw: &str) -> Result<String, String> {
    let trimmed = raw.trim();
    if Path::new(trimmed).is_file() {
        let s =
            fs::read_to_string(trimmed).map_err(|e| format!("failed to read secret file: {e}"))?;
        return Ok(s.trim().to_string());
    }
    Ok(trimmed.to_string())
}

fn compute_wotp(secret: &str, wid: &str, digits: usize) -> Result<String, String> {
    let mut mac = HmacSha256::new_from_slice(secret.as_bytes())
        .map_err(|_| "failed to initialize HMAC".to_string())?;
    mac.update(wid.as_bytes());
    let digest = mac.finalize().into_bytes();
    if digest.len() < 4 {
        return Err("failed to compute w-otp digest".to_string());
    }
    let v = u64::from(u32::from_be_bytes([
        digest[0], digest[1], digest[2], digest[3],
    ]));
    // CRYPTO_SPEC: otp = value mod 10^DIGITS. The modulus must be 64-bit:
    // DIGITS may be 10 and 10^10 exceeds u32::MAX (saturating at u32::MAX
    // silently produced a different code than the other implementations).
    let mut m = 1u64;
    for _ in 0..digits {
        m *= 10;
    }
    Ok(format!("{:0width$}", v % m, width = digits))
}

/// Extract epoch-milliseconds from the leading timestamp of a WID, for the
/// w-otp time-window (freshness) check only. This is deliberately lenient and
/// independent of `W`/`Z` and of whether the WID is plain or HLC: the timestamp
/// prefix is always `YYYYMMDDThhmmss` (seconds) or `YYYYMMDDThhmmssSSS`
/// (milliseconds). Using the strict WID parser here made `verify` reject WIDs
/// that `gen` had just accepted, and disagreed with the other language
/// implementations (which all use this same lenient extraction).
fn wotp_wid_tick_ms(wid: &str) -> Result<i64, String> {
    let err = || "WID timestamp is invalid for time-window verification".to_string();
    let ts = wid.split('.').next().unwrap_or("");
    let (date, time) = ts.split_once('T').ok_or_else(err)?;
    if date.len() != 8 || !(time.len() == 6 || time.len() == 9) {
        return Err(err());
    }
    if !date.bytes().all(|b| b.is_ascii_digit()) || !time.bytes().all(|b| b.is_ascii_digit()) {
        return Err(err());
    }
    let num = |s: &str| s.parse::<u32>().map_err(|_| err());
    let year: i32 = date[0..4].parse().map_err(|_| err())?;
    let month = num(&date[4..6])?;
    let day = num(&date[6..8])?;
    let hour = num(&time[0..2])?;
    let minute = num(&time[2..4])?;
    let second = num(&time[4..6])?;
    let millis: i64 = if time.len() == 9 {
        time[6..9].parse().map_err(|_| err())?
    } else {
        0
    };
    use chrono::TimeZone;
    let dt = chrono::Utc
        .with_ymd_and_hms(year, month, day, hour, minute, second)
        .single()
        .ok_or_else(err)?;
    Ok(dt.timestamp_millis() + millis)
}

pub(crate) fn run_wotp(c: &CanonOpts) -> Result<(), CliError> {
    let mode = {
        let m = c.mode.trim().to_ascii_lowercase();
        if m.is_empty() { "gen".to_string() } else { m }
    };
    if mode != "gen" && mode != "verify" {
        return Err(usage("MODE must be gen or verify for A=w-otp"));
    }
    if c.key.trim().is_empty() {
        return Err(usage("KEY=<secret_or_path> required for A=w-otp"));
    }
    if c.digits < 4 || c.digits > 10 {
        return Err(usage("DIGITS must be between 4 and 10"));
    }
    let secret = resolve_wotp_secret(&c.key).map_err(fail)?;
    // An empty secret *file* must be rejected like an empty inline secret
    // (the Python/TS/sh/C implementations already do).
    if secret.is_empty() {
        return Err(usage("w-otp secret cannot be empty"));
    }
    let wid = if c.wid.trim().is_empty() && mode == "gen" {
        WidGen::new_with_time_unit(c.w, c.z, c.t)
            .map_err(|e| usage(e.to_string()))?
            .next_wid()
    } else {
        c.wid.clone()
    };
    if wid.trim().is_empty() {
        return Err(usage("WID=<wid_string> required for A=w-otp MODE=verify"));
    }
    let otp = compute_wotp(&secret, &wid, c.digits).map_err(fail)?;
    if mode == "gen" {
        println!("{}", json!({"wid": wid, "otp": otp, "digits": c.digits}));
        return Ok(());
    }
    if c.code.trim().is_empty() {
        return Err(usage("CODE=<otp_code> required for A=w-otp MODE=verify"));
    }
    if c.max_age_sec > 0 || c.max_future_sec > 0 {
        let wid_ms = wotp_wid_tick_ms(&wid).map_err(fail)?;
        let now_ms = chrono::Utc::now().timestamp_millis();
        let delta = now_ms - wid_ms;
        if delta < 0 {
            if -delta > (c.max_future_sec as i64) * 1000 {
                return Err(fail("OTP invalid: WID timestamp is too far in the future"));
            }
        } else if c.max_age_sec > 0 && delta > (c.max_age_sec as i64) * 1000 {
            return Err(fail("OTP invalid: WID timestamp is too old"));
        }
    }
    if bool::from(c.code.as_bytes().ct_eq(otp.as_bytes())) {
        println!("OTP valid.");
        return Ok(());
    }
    Err(fail("OTP invalid."))
}
