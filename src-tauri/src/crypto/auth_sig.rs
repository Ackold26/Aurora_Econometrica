//! Ed25519 signature verification for the /auth license response (SEC-1).
//! Uses a SEPARATE key from update and content verification (least privilege):
//! a compromise of the update key does not forge license grants, and vice versa.
//!
//! Original auth pubkey hex:
//!   19221d249015fbbd1ee123a2356c80ef2d00031411d2e8d91b06c84b721a17b7
//!
//! Threat: an unsigned /auth response lets a forged server / MITM / cache-forge return
//! {status:"ok", cabinets:[all]} and unlock the product without a license. The server signs
//! the "ok" response; the client verifies with the embedded public key. Without the private
//! key an attacker cannot fabricate a valid response on the wire OR in session_cache.json.
//!
//! 🔴 Граница защиты, названная честно (INV-50; уточнено находкой внешнего аудита 2026-08-03).
//! Утверждение выше верно РОВНО НАСТОЛЬКО, насколько подпись проверяется на КАЖДОМ пути, где
//! ответу начинают доверять, — включая чтение `session_cache.json` (см. `read_fresh_cache`).
//! Сверх этого защита НЕ покрывает:
//!   - поля вне подписываемого набора: адреса и контрольные суммы доставки лежат в том же файле,
//!     и законно подписанный ответ можно дополнить своими (поэтому из кэша они не берутся вовсе);
//!   - ответ БЕЗ подписи: он законен (так отвечает сервер локальной редакции), поэтому в мягком
//!     режиме принимается — срок доверия ему сокращён, но подделка без подписи проходит;
//!   - окно отзыва: метка времени кэша вне подписи, а локальные часы принадлежат пользователю.
//! Пока `AUTH_SIG_ENFORCEMENT = Soft`, честная формулировка — «сокращает срок жизни подделки и
//! отсекает подделку с неверной подписью», а не «подделка невозможна».
//!
//! Payload format (UTF-8, fields joined by '\n') — deterministic string, NOT JSON
//! (JSON serialisation drifts between Deno and Rust):
//!   AUTHSIG-v1\n{status}\n{fingerprint_hash}\n{product}\n{cabinets_sorted}\n{content_version}\n{expires_at}
//! where:
//!   - only the status=="ok" response is signed,
//!   - cabinets_sorted = lexicographically sorted ASCII slugs joined by ',',
//!   - content_version / expires_at absent => empty string,
//!   - product is the RAW product the client sent (not the server-migrated licenseProduct),
//!   - fingerprint_hash binds the grant to this machine (anti-replay to another machine).

use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use base64::{Engine, engine::general_purpose::STANDARD};

/// Auth public key XOR'd with 0x3C mask (raise-the-bar obfuscation, not crypto).
/// Original pubkey hex: 19221d249015fbbd1ee123a2356c80ef2d00031411d2e8d91b06c84b721a17b7
const AUTH_MASKED_KEY: [u8; 32] = [
     37,  30,  33,  24, 172,  41, 199, 129,  34, 221,  31, 158,   9,  80, 188, 211,
     17,  60,  63,  40,  45, 238, 212, 229,  39,  58, 244, 119,  78,  38,  43, 139,
];
const AUTH_KEY_MASK: u8 = 0x3C;

fn auth_public_key_bytes() -> [u8; 32] {
    let mut out = [0u8; 32];
    for i in 0..32 {
        out[i] = AUTH_MASKED_KEY[i] ^ AUTH_KEY_MASK;
    }
    out
}

/// Enforcement mode for auth-signature verification.
///
/// `Soft` (initial rollout): verification runs and is logged/metered, but access is NOT
/// blocked — a missing/invalid signature still passes, so a server that does not yet sign
/// (or a payload-serialisation drift) cannot take all licenses down at once. Once telemetry
/// confirms the server signs stably for every product, flip to `Hard` in a separate release.
///
/// `Hard`: a missing or invalid signature on the "ok" path is a hard refusal.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Enforcement {
    Soft,
    Hard,
}

/// Current enforcement mode. First release ships `Soft`; switch to `Hard` in a later release.
pub const AUTH_SIG_ENFORCEMENT: Enforcement = Enforcement::Soft;

/// Build the canonical payload bytes for /auth response signature verification.
///
/// Format (UTF-8, newline-separated):
/// ```text
/// AUTHSIG-v1
/// {status}
/// {fingerprint_hash}
/// {product}
/// {cabinets_sorted}
/// {content_version}
/// {expires_at}
/// ```
/// `cabinets` are sorted lexicographically and joined by ','. `content_version` / `expires_at`
/// of `None` become an empty string. Only string values are concatenated — no reformatting.
pub fn build_auth_payload(
    status: &str,
    fingerprint_hash: &str,
    product: &str,
    cabinets: &[String],
    content_version: Option<&str>,
    expires_at: Option<&str>,
) -> Vec<u8> {
    let mut cabs: Vec<&str> = cabinets.iter().map(|s| s.as_str()).collect();
    cabs.sort_unstable();
    let cabinets_sorted = cabs.join(",");
    let payload = [
        "AUTHSIG-v1",
        status,
        fingerprint_hash,
        product,
        &cabinets_sorted,
        content_version.unwrap_or(""),
        expires_at.unwrap_or(""),
    ]
    .join("\n");
    payload.into_bytes()
}

/// Verify an /auth response Ed25519 signature (base64-encoded).
///
/// Returns `false` on any error — invalid base64, wrong length, bad signature — without
/// panicking. An empty `sig_b64` returns `false` (empty is not a valid signature); the caller
/// distinguishes "absent" from "invalid" (see the Soft/Hard enforcement branch in check_auth).
pub fn verify_auth_signature(payload: &[u8], sig_b64: &str) -> bool {
    let sig_bytes = match STANDARD.decode(sig_b64) {
        Ok(b) => b,
        Err(_) => return false,
    };
    if sig_bytes.len() != 64 {
        return false;
    }
    verify_auth_signature_impl(payload, &sig_bytes, &auth_public_key_bytes())
}

/// Internal implementation accepting arbitrary public key bytes — enables unit tests
/// to use a test keypair without needing the production private key.
pub(crate) fn verify_auth_signature_impl(
    payload: &[u8],
    sig_bytes: &[u8],
    pubkey_bytes: &[u8; 32],
) -> bool {
    let Ok(pubkey) = VerifyingKey::from_bytes(pubkey_bytes) else {
        return false;
    };
    let Ok(sig_array) = <[u8; 64]>::try_from(sig_bytes) else {
        return false;
    };
    let signature = Signature::from_bytes(&sig_array);
    pubkey.verify(payload, &signature).is_ok()
}

// ── Tests ─────────────────────────────────────────────────────────────────────

/// 🔴 Зонд на ЖИВОМ ответе сервера этой машины: сходится ли наша канонизация с серверной.
/// Решающий для CPD-40 — без него включение политики «подпись есть и не сходится → не кэшировать»
/// могло бы отнять офлайн у всех честных клиентов разом при малейшем расхождении формата.
///
/// Помечен `#[ignore]`: читает `%APPDATA%` конкретной машины и в общем прогоне бесполезен.
/// Запуск: `cargo test -- --ignored live_auth_signature_probe --nocapture`.
#[cfg(test)]
mod live_probe {
    use super::{build_auth_payload, verify_auth_signature};

    #[test]
    #[ignore = "зонд на живом кэше конкретной машины"]
    fn live_auth_signature_probe() {
        let base = std::path::PathBuf::from(std::env::var("APPDATA").expect("APPDATA"));
        let candidates = [
            "com.aurora.econometrica.thin",
            "com.aurora.econometrica",
            "com.aurora.econometrica.local",
        ];
        let mut checked = 0;
        for dir in candidates {
            let path = base.join(dir).join("session_cache.json");
            let Ok(raw) = std::fs::read_to_string(&path) else { continue };
            let v: serde_json::Value = serde_json::from_str(&raw).expect("разбор кэша");
            let r = &v["response"];
            let status = r["status"].as_str().unwrap_or("");
            let sig = r["signature"].as_str().unwrap_or("");
            if sig.is_empty() {
                println!("{dir}: подписи в ответе нет — проверять нечего");
                continue;
            }
            let cabinets: Vec<String> = r["cabinets"]
                .as_array()
                .map(|a| a.iter().filter_map(|c| c.as_str().map(String::from)).collect())
                .unwrap_or_default();
            let cv = r["content_version"].as_str();
            let exp = r["expires_at"].as_str();

            let fp = crate::crypto::fingerprint::get_machine_fingerprint().expect("отпечаток");
            let fp_hash = crate::crypto::fingerprint::hash_fingerprint(&fp);

            for product in [
                "econometrica",
                "econometrica-thin",
                "aurora-econometrica-gui",
                "econometrica-local",
                "agency",
            ] {
                let payload = build_auth_payload(status, &fp_hash, product, &cabinets, cv, exp);
                let ok = verify_auth_signature(&payload, sig);
                println!(
                    "{dir} · product={product}: {}",
                    if ok { "🔴 ПОДПИСЬ СОШЛАСЬ" } else { "не сошлась" }
                );
                checked += 1;
            }
        }
        assert!(checked > 0, "живых подписанных ответов на машине не найдено — зонд не состоялся");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::engine::general_purpose::STANDARD as B64;
    use ed25519_dalek::{Signer, SigningKey};

    fn test_keypair() -> SigningKey {
        SigningKey::generate(&mut rand::thread_rng())
    }

    fn sample_cabinets() -> Vec<String> {
        // deliberately UNSORTED input — proves build_auth_payload sorts
        vec![
            "copywriter".to_string(),
            "art-director".to_string(),
            "creative-director".to_string(),
        ]
    }

    /// Production key must unmask to a valid Ed25519 verifying key.
    #[test]
    fn auth_key_unmask_is_valid() {
        assert!(
            VerifyingKey::from_bytes(&auth_public_key_bytes()).is_ok(),
            "Unmasked auth key must be a valid Ed25519 public key"
        );
    }

    /// Valid signature produced by test key verifies correctly.
    #[test]
    fn valid_signature_accepted() {
        let sk = test_keypair();
        let vk = sk.verifying_key().to_bytes();
        let payload = build_auth_payload(
            "ok",
            "a6a64d59ca6d5ab8dccfe9556fa82c81ae90ab01051b0d44c8726ba9f533f5f0",
            "creative-hub",
            &sample_cabinets(),
            Some("2026.07"),
            Some("2027-01-01T00:00:00Z"),
        );
        let sig_bytes = sk.sign(&payload).to_bytes();
        assert!(
            verify_auth_signature_impl(&payload, &sig_bytes, &vk),
            "Valid signature must be accepted"
        );
    }

    /// Tampering cabinets (adding one) invalidates the signature.
    #[test]
    fn tampered_cabinets_rejected() {
        let sk = test_keypair();
        let vk = sk.verifying_key().to_bytes();
        let original = build_auth_payload(
            "ok", "FP", "creative-hub", &sample_cabinets(), Some("2026.07"), Some("2027-01-01T00:00:00Z"),
        );
        let sig_bytes = sk.sign(&original).to_bytes();

        let mut more = sample_cabinets();
        more.push("strategist".to_string()); // extra cabinet the server never granted
        let tampered = build_auth_payload(
            "ok", "FP", "creative-hub", &more, Some("2026.07"), Some("2027-01-01T00:00:00Z"),
        );
        assert!(
            !verify_auth_signature_impl(&tampered, &sig_bytes, &vk),
            "Tampered cabinets must be rejected"
        );
    }

    /// Empty signature string returns false (unsigned/absent path).
    #[test]
    fn empty_signature_returns_false() {
        let payload = build_auth_payload("ok", "FP", "p", &[], None, None);
        assert!(
            !verify_auth_signature(&payload, ""),
            "Empty signature must return false"
        );
    }

    /// Invalid base64 returns false without panicking.
    #[test]
    fn invalid_base64_returns_false_no_panic() {
        let payload = build_auth_payload("ok", "FP", "p", &[], None, None);
        assert!(
            !verify_auth_signature(&payload, "not!valid#base64==="),
            "Invalid base64 must return false, not panic"
        );
    }

    /// Correct length but all-zero bytes: invalid signature, not a panic.
    #[test]
    fn zero_bytes_signature_returns_false() {
        let payload = build_auth_payload("ok", "FP", "p", &sample_cabinets(), None, None);
        let zero_b64 = B64.encode([0u8; 64]);
        assert!(
            !verify_auth_signature(&payload, &zero_b64),
            "All-zero signature must be rejected"
        );
    }

    /// build_auth_payload produces the expected newline-joined format and sorts cabinets.
    ///
    /// 🔴 Фикстура из ТРЁХ элементов намеренно: на паре `["b", "a"]` разворот даёт ровно тот же
    /// результат, что сортировка, и подмена `sort_unstable` на `reverse` проходила зелёной —
    /// сторож был слеп ровно к той оси, которую стережёт (поймано мутацией при переносе модуля).
    #[test]
    fn payload_format_matches_protocol() {
        let cabs = vec!["b".to_string(), "c".to_string(), "a".to_string()];
        let p = build_auth_payload("ok", "FP", "creative-hub", &cabs, Some("cv"), Some("exp"));
        let s = std::str::from_utf8(&p).unwrap();
        assert_eq!(
            s,
            "AUTHSIG-v1\nok\nFP\ncreative-hub\na,b,c\ncv\nexp"
        );
    }

    /// None content_version / expires_at and empty cabinets become empty strings.
    #[test]
    fn payload_none_fields_are_empty() {
        let p = build_auth_payload("ok", "FP", "p", &[], None, None);
        let s = std::str::from_utf8(&p).unwrap();
        assert_eq!(s, "AUTHSIG-v1\nok\nFP\np\n\n\n");
    }

    /// Golden cross-language test Python↔Rust on the PRODUCTION key.
    ///
    /// payload + signature generated by the working Python signer (tools/sign_auth_response.py)
    /// with the production key rosst_auth_private.key. Proves:
    ///   (1) build_auth_payload is byte-identical to the Python/Deno canonical string,
    ///   (2) the embedded production pubkey verifies a real signature,
    ///   (3) anti-replay: a signature bound to machine A's fingerprint fails for machine B,
    ///   (4) anti-cross-product: a signature for product X fails for product Y.
    #[test]
    fn sec1_golden_python_signature_production_key() {
        let fp = "a6a64d59ca6d5ab8dccfe9556fa82c81ae90ab01051b0d44c8726ba9f533f5f0";
        let cabinets = sample_cabinets();
        let payload = build_auth_payload(
            "ok", fp, "creative-hub", &cabinets, Some("2026.07"), Some("2027-01-01T00:00:00Z"),
        );
        // (1) byte-equivalence with the Python/Deno canonical payload:
        let expected_hex = "415554485349472d76310a6f6b0a613661363464353963613664356162386463636665393535366661383263383161653930616230313035316230643434633837323662613966353333663566300a63726561746976652d6875620a6172742d6469726563746f722c636f70797772697465722c63726561746976652d6469726563746f720a323032362e30370a323032372d30312d30315430303a30303a30305a";
        assert_eq!(hex::encode(&payload), expected_hex, "canonical payload diverged from Python signer");
        // (2) real Python signature with the production key must pass the embedded pubkey:
        let golden_sig_b64 = "oMZyBuqb18ho44YYrtNfbHuweN8F+ArGvuEaUlWew67UjUAqHXuVHNGirYU6xGfnQ8y37KugpcwRmVPLW0HIDA==";
        assert!(verify_auth_signature(&payload, golden_sig_b64), "production pubkey failed to verify real Python signature");
        // (3) anti-replay — same everything but a different machine fingerprint:
        let fp_b = "b".repeat(64);
        let payload_other_machine = build_auth_payload(
            "ok", &fp_b, "creative-hub", &cabinets, Some("2026.07"), Some("2027-01-01T00:00:00Z"),
        );
        assert!(!verify_auth_signature(&payload_other_machine, golden_sig_b64), "replay to another machine must be rejected");
        // (4) anti-cross-product — signature for creative-hub must not pass for legal:
        let payload_other_product = build_auth_payload(
            "ok", fp, "legal", &cabinets, Some("2026.07"), Some("2027-01-01T00:00:00Z"),
        );
        assert!(!verify_auth_signature(&payload_other_product, golden_sig_b64), "cross-product replay must be rejected");
    }
}
