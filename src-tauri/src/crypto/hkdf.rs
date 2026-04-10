use anyhow::Result;
use hkdf::Hkdf;
use sha2::Sha256;

use crate::errors::{coded_err, ErrorCode};

/// Derive a 32-byte AES key from machine fingerprint + license salt using HKDF-SHA256.
pub fn derive_key(fingerprint: &str, salt: &[u8]) -> Result<[u8; 32]> {
    let hk = Hkdf::<Sha256>::new(Some(salt), fingerprint.as_bytes());
    let mut key = [0u8; 32];
    hk.expand(b"ai-agency-vault-key-v1", &mut key)
        .map_err(|e| coded_err(ErrorCode::VT002, &format!("HKDF expansion error: {e}")))?;
    Ok(key)
}
