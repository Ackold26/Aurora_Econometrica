//! Ed25519 signature verification for content packs and frontend bundles.
//! Uses a SEPARATE key from license verification (least privilege).

use anyhow::Result;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::path::Path;

/// Content public key XOR'd with 0x55 mask (different from license key).
/// Original: [89, 38, 89, 223, 233, 234, 52, 133, 129, 211, 163, 241, 2, 219, 157, 33,
///            230, 230, 150, 180, 58, 16, 176, 198, 176, 184, 191, 106, 121, 33, 181, 126]
const CONTENT_MASKED_KEY: [u8; 32] = [
    12, 115, 12, 138, 188, 191, 97, 208, 212, 134, 246, 164, 87, 142, 200, 116,
    179, 179, 195, 225, 111, 69, 229, 147, 229, 237, 234, 63, 44, 116, 224, 43,
];
const CONTENT_KEY_MASK: u8 = 0x55;

/// Minimum accepted content pack version (rollback protection).
/// Increment this in code when releasing breaking content changes.
const MIN_CONTENT_VERSION: u32 = 1;

fn content_public_key_bytes() -> [u8; 32] {
    let mut out = [0u8; 32];
    for i in 0..32 {
        out[i] = CONTENT_MASKED_KEY[i] ^ CONTENT_KEY_MASK;
    }
    out
}

/// Verify Ed25519 signature of content manifest bytes.
pub fn verify_content_signature(data: &[u8], signature_bytes: &[u8]) -> Result<bool> {
    let public_key = VerifyingKey::from_bytes(&content_public_key_bytes())
        .map_err(|e| anyhow::anyhow!("Invalid content public key: {e}"))?;

    let sig_array: [u8; 64] = signature_bytes
        .try_into()
        .map_err(|_| anyhow::anyhow!("Content signature must be 64 bytes"))?;
    let signature = Signature::from_bytes(&sig_array);

    Ok(public_key.verify(data, &signature).is_ok())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContentManifest {
    pub format_version: u32,
    pub layer: String,
    pub version: u32,
    pub min_core_version: String,
    pub product: String,
    pub timestamp: u64,
    pub files: HashMap<String, String>,
}

/// Verify manifest signature and all file checksums.
///
/// Checks:
/// 1. manifest.json + manifest.sig both exist
/// 2. Ed25519 signature over manifest.json is valid
/// 3. manifest.version >= MIN_CONTENT_VERSION (rollback protection)
/// 4. Every listed file exists, is within manifest_dir (symlink protection), and matches SHA-256
pub fn verify_manifest(manifest_dir: &Path) -> Result<ContentManifest> {
    verify_manifest_impl(manifest_dir, &content_public_key_bytes())
}

/// Internal implementation that accepts an arbitrary public key — enables unit tests
/// to use a test keypair without needing the production private key.
fn verify_manifest_impl(manifest_dir: &Path, public_key_bytes: &[u8; 32]) -> Result<ContentManifest> {
    let manifest_path = manifest_dir.join("manifest.json");
    let sig_path = manifest_dir.join("manifest.sig");

    if !manifest_path.exists() || !sig_path.exists() {
        anyhow::bail!("Manifest or signature file missing in {:?}", manifest_dir);
    }

    let manifest_bytes = std::fs::read(&manifest_path)?;
    let sig_bytes = std::fs::read(&sig_path)?;

    let public_key = VerifyingKey::from_bytes(public_key_bytes)
        .map_err(|e| anyhow::anyhow!("Invalid content public key: {e}"))?;

    let sig_array: [u8; 64] = sig_bytes
        .as_slice()
        .try_into()
        .map_err(|_| anyhow::anyhow!("Content signature must be 64 bytes"))?;
    let signature = Signature::from_bytes(&sig_array);

    if public_key.verify(&manifest_bytes, &signature).is_err() {
        anyhow::bail!("Content manifest signature verification FAILED — possible tampering");
    }

    let manifest: ContentManifest = serde_json::from_slice(&manifest_bytes)?;

    if manifest.version < MIN_CONTENT_VERSION {
        anyhow::bail!(
            "Content version {} below minimum {}",
            manifest.version,
            MIN_CONTENT_VERSION
        );
    }

    let canonical_dir = manifest_dir.canonicalize()?;

    for (rel_path, expected_hash) in &manifest.files {
        let file_path = manifest_dir.join(rel_path);

        if !file_path.exists() {
            anyhow::bail!("File missing from content pack: {}", rel_path);
        }

        // Symlink/path-traversal protection
        let canonical = file_path.canonicalize()?;
        if !canonical.starts_with(&canonical_dir) {
            anyhow::bail!(
                "File {} resolves outside manifest directory (possible path traversal)",
                rel_path
            );
        }

        let actual_hash = format!("sha256:{}", sha256_file(&file_path)?);
        if &actual_hash != expected_hash {
            anyhow::bail!(
                "Checksum mismatch for {} — expected {}, got {}",
                rel_path,
                expected_hash,
                actual_hash
            );
        }
    }

    Ok(manifest)
}

fn sha256_file(path: &Path) -> Result<String> {
    let data = std::fs::read(path)?;
    let mut hasher = Sha256::new();
    hasher.update(&data);
    Ok(format!("{:x}", hasher.finalize()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};
    use std::fs;
    use tempfile::TempDir;

    // ── Signature primitives ──────────────────────────────────────────────────

    #[test]
    fn test_content_key_unmask() {
        let key = content_public_key_bytes();
        assert!(
            VerifyingKey::from_bytes(&key).is_ok(),
            "Unmasked content key must be a valid Ed25519 public key"
        );
    }

    #[test]
    fn test_verify_invalid_signature() {
        let data = b"test content data";
        let bad_sig = [0u8; 64];
        // Wrong signature must return false, not an error
        assert!(!verify_content_signature(data, &bad_sig).unwrap());
    }

    #[test]
    fn test_verify_wrong_sig_length() {
        let data = b"test";
        let bad_sig = [0u8; 32]; // wrong length
        assert!(verify_content_signature(data, &bad_sig).is_err());
    }

    #[test]
    fn test_verify_valid_ed25519_round_trip() {
        // Generate a test keypair and verify that sign→verify works correctly
        let signing_key = SigningKey::generate(&mut rand::thread_rng());
        let verifying_key = signing_key.verifying_key();
        let data = b"aurora content pack v1";
        let signature = signing_key.sign(data);
        assert!(verifying_key.verify(data, &signature).is_ok());
        assert!(verifying_key.verify(b"tampered data", &signature).is_err());
    }

    // ── Test helpers ──────────────────────────────────────────────────────────

    /// Write manifest.json + manifest.sig + content files using a test keypair.
    fn make_signed_pack(dir: &Path, signing_key: &SigningKey, version: u32, files: &[(&str, &[u8])]) {
        let mut file_map = serde_json::Map::new();
        for (name, data) in files {
            fs::write(dir.join(name), data).unwrap();
            let hash = format!("sha256:{:x}", Sha256::digest(data));
            file_map.insert(name.to_string(), serde_json::Value::String(hash));
        }
        let manifest = serde_json::json!({
            "format_version": 1,
            "layer": "content",
            "version": version,
            "min_core_version": "0.7.0",
            "product": "test",
            "timestamp": 1_700_000_000u64,
            "files": file_map,
        });
        let manifest_bytes = serde_json::to_vec(&manifest).unwrap();
        fs::write(dir.join("manifest.json"), &manifest_bytes).unwrap();
        let signature = signing_key.sign(&manifest_bytes);
        fs::write(dir.join("manifest.sig"), signature.to_bytes()).unwrap();
    }

    // ── verify_manifest_impl tests ────────────────────────────────────────────

    #[test]
    fn test_verify_manifest_no_manifest_file() {
        let dir = TempDir::new().unwrap();
        fs::write(dir.path().join("manifest.sig"), [0u8; 64]).unwrap();
        assert!(verify_manifest_impl(dir.path(), &[0u8; 32]).is_err());
    }

    #[test]
    fn test_verify_manifest_no_sig_file() {
        let dir = TempDir::new().unwrap();
        fs::write(dir.path().join("manifest.json"), b"{}").unwrap();
        assert!(verify_manifest_impl(dir.path(), &[0u8; 32]).is_err());
    }

    #[test]
    fn test_verify_manifest_wrong_key_rejected() {
        let dir = TempDir::new().unwrap();
        let signing_key = SigningKey::generate(&mut rand::thread_rng());
        make_signed_pack(dir.path(), &signing_key, 1, &[("cabinets.json", b"{}")]);

        // Verify with a different (wrong) key
        let wrong_key = SigningKey::generate(&mut rand::thread_rng());
        let wrong_vk = wrong_key.verifying_key().to_bytes();
        let err = verify_manifest_impl(dir.path(), &wrong_vk).unwrap_err();
        assert!(err.to_string().contains("FAILED"));
    }

    #[test]
    fn test_verify_manifest_valid() {
        let dir = TempDir::new().unwrap();
        let signing_key = SigningKey::generate(&mut rand::thread_rng());
        make_signed_pack(dir.path(), &signing_key, 1, &[
            ("cabinets.json", b"{\"cabinets\":[]}"),
            ("command-meta-data.json", b"{}"),
        ]);

        let vk = signing_key.verifying_key().to_bytes();
        let manifest = verify_manifest_impl(dir.path(), &vk).unwrap();
        assert_eq!(manifest.version, 1);
        assert_eq!(manifest.files.len(), 2);
        assert_eq!(manifest.product, "test");
    }

    #[test]
    fn test_verify_manifest_rollback_protection() {
        let dir = TempDir::new().unwrap();
        let signing_key = SigningKey::generate(&mut rand::thread_rng());
        // version 0 is below MIN_CONTENT_VERSION = 1
        make_signed_pack(dir.path(), &signing_key, 0, &[]);

        let vk = signing_key.verifying_key().to_bytes();
        let err = verify_manifest_impl(dir.path(), &vk).unwrap_err();
        assert!(err.to_string().contains("below minimum"), "err: {err}");
    }

    #[test]
    fn test_verify_manifest_tamper_file_content() {
        let dir = TempDir::new().unwrap();
        let signing_key = SigningKey::generate(&mut rand::thread_rng());
        make_signed_pack(dir.path(), &signing_key, 1, &[("cabinets.json", b"original content")]);

        // Tamper the file after signing
        fs::write(dir.path().join("cabinets.json"), b"TAMPERED CONTENT!").unwrap();

        let vk = signing_key.verifying_key().to_bytes();
        let err = verify_manifest_impl(dir.path(), &vk).unwrap_err();
        assert!(err.to_string().contains("Checksum mismatch"), "err: {err}");
    }

    #[test]
    fn test_verify_manifest_missing_listed_file() {
        let dir = TempDir::new().unwrap();
        let signing_key = SigningKey::generate(&mut rand::thread_rng());
        make_signed_pack(dir.path(), &signing_key, 1, &[("cabinets.json", b"{}")]);

        // Remove file after signing
        fs::remove_file(dir.path().join("cabinets.json")).unwrap();

        let vk = signing_key.verifying_key().to_bytes();
        let err = verify_manifest_impl(dir.path(), &vk).unwrap_err();
        assert!(err.to_string().contains("File missing"), "err: {err}");
    }
}
