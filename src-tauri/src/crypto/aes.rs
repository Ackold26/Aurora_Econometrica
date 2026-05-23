use aes_gcm::{
    aead::{Aead, KeyInit, OsRng},
    Aes256Gcm, Nonce,
};
use anyhow::{Context, Result};
use rand::RngCore;

use crate::errors::{coded, coded_err, ErrorCode};

const NONCE_SIZE: usize = 12;

/// Encrypt data with AES-256-GCM. Returns nonce || ciphertext.
pub fn encrypt(key: &[u8; 32], plaintext: &[u8]) -> Result<Vec<u8>> {
    let cipher = Aes256Gcm::new_from_slice(key)
        .map_err(|e| coded_err(ErrorCode::VT002, &format!("AES key init error: {e}")))?;

    let mut nonce_bytes = [0u8; NONCE_SIZE];
    OsRng.fill_bytes(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);

    let ciphertext = cipher
        .encrypt(nonce, plaintext)
        .map_err(|e| coded_err(ErrorCode::VT002, &format!("AES encryption error: {e}")))?;

    let mut output = Vec::with_capacity(NONCE_SIZE + ciphertext.len());
    output.extend_from_slice(&nonce_bytes);
    output.extend_from_slice(&ciphertext);
    Ok(output)
}

/// Decrypt data encrypted with AES-256-GCM. Input: nonce || ciphertext.
pub fn decrypt(key: &[u8; 32], data: &[u8]) -> Result<Vec<u8>> {
    if data.len() < NONCE_SIZE {
        anyhow::bail!("{}", coded(ErrorCode::VT005, "Encrypted data too short"));
    }

    let (nonce_bytes, ciphertext) = data.split_at(NONCE_SIZE);
    let cipher = Aes256Gcm::new_from_slice(key)
        .map_err(|e| coded_err(ErrorCode::VT002, &format!("AES key init error: {e}")))?;
    let nonce = Nonce::from_slice(nonce_bytes);

    cipher
        .decrypt(nonce, ciphertext)
        .map_err(|e| coded_err(ErrorCode::VT002, &format!("AES decryption failed (wrong key or corrupted data): {e}")))
        .context(coded(ErrorCode::VT002, "Vault decryption failed - possibly wrong machine or corrupted vault"))
}
