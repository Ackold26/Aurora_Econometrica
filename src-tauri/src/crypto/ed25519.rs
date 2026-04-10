use anyhow::Result;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};

use crate::errors::{coded_err, ErrorCode};

/// Ed25519 public key XOR'd with mask to avoid plaintext in binary.
/// Original: [107, 117, 227, 176, 209, 81, 172, 175, 75, 122, 86, 18, 25, 248, 116, 202, 245, 64, 171, 148, 143, 9, 223, 199, 99, 58, 27, 251, 191, 84, 219, 56]
const MASKED_KEY: [u8; 32] = [
    62, 32, 182, 229, 132, 4, 249, 250, 30, 47, 3, 71, 76, 173, 33, 159,
    160, 21, 254, 193, 218, 92, 138, 146, 54, 111, 78, 174, 234, 1, 142, 109,
];
const KEY_MASK: u8 = 0x55;

fn public_key_bytes() -> [u8; 32] {
    let mut out = [0u8; 32];
    for i in 0..32 {
        out[i] = MASKED_KEY[i] ^ KEY_MASK;
    }
    out
}

/// Verify an Ed25519 signature over data.
pub fn verify_signature(data: &[u8], signature_bytes: &[u8]) -> Result<bool> {
    let public_key = VerifyingKey::from_bytes(&public_key_bytes())
        .map_err(|e| coded_err(ErrorCode::LI007, &format!("Invalid public key: {e}")))?;

    let sig_array: [u8; 64] = signature_bytes
        .try_into()
        .map_err(|_| coded_err(ErrorCode::LI007, "Signature must be 64 bytes"))?;
    let signature = Signature::from_bytes(&sig_array);

    Ok(public_key.verify(data, &signature).is_ok())
}

/// Verify with a provided public key (for testing / key rotation).
pub fn verify_with_key(
    public_key_bytes: &[u8; 32],
    data: &[u8],
    signature_bytes: &[u8],
) -> Result<bool> {
    let public_key = VerifyingKey::from_bytes(public_key_bytes)
        .map_err(|e| coded_err(ErrorCode::LI007, &format!("Invalid public key: {e}")))?;

    let sig_array: [u8; 64] = signature_bytes
        .try_into()
        .map_err(|_| coded_err(ErrorCode::LI007, "Signature must be 64 bytes"))?;
    let signature = Signature::from_bytes(&sig_array);

    Ok(public_key.verify(data, &signature).is_ok())
}
