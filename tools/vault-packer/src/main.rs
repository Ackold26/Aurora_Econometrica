use aes_gcm::{
    aead::{Aead, KeyInit, OsRng},
    Aes256Gcm, Nonce,
};
use anyhow::{Context, Result};
use base64::Engine;
use clap::{Parser, Subcommand};
use hkdf::Hkdf;
use rand::RngCore;
use sha2::Sha256;
use std::path::{Path, PathBuf};

#[derive(Parser)]
#[command(name = "vault-pack", about = "AI Agency vault packer - encrypt/decrypt skill vaults")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Pack a cabinet directory into an encrypted .vault file
    Pack {
        /// Path to the cabinet directory (containing .claude/, CLAUDE.md, etc.)
        #[arg(short, long)]
        source: String,
        /// Cabinet ID (e.g. media-analyst)
        #[arg(short, long)]
        cabinet_id: String,
        /// Machine fingerprint (output of `wmic csproduct get UUID` etc.)
        /// For dev/testing, pass any string - it just needs to match at decryption time.
        #[arg(short, long)]
        fingerprint: String,
        /// Path to license.json (salt is read from it)
        #[arg(short, long)]
        license: String,
        /// Output directory for .vault files
        #[arg(short, long, default_value = ".")]
        output_dir: String,
    },
    /// Unpack (decrypt) a .vault file to verify contents
    Unpack {
        /// Path to the .vault file
        #[arg(short, long)]
        vault: String,
        /// Machine fingerprint (must match what was used to pack)
        #[arg(short, long)]
        fingerprint: String,
        /// Path to license.json
        #[arg(short, long)]
        license: String,
        /// Output directory for extracted files
        #[arg(short, long, default_value = "./unpacked")]
        output_dir: String,
    },
    /// Pack all cabinets from a New_AI_Agency directory
    PackAll {
        /// Path to New_AI_Agency directory
        #[arg(short, long)]
        source: String,
        /// Machine fingerprint
        #[arg(short, long)]
        fingerprint: String,
        /// Path to license.json
        #[arg(short, long)]
        license: String,
        /// Output directory for .vault files
        #[arg(short, long, default_value = ".")]
        output_dir: String,
    },
}

fn derive_key(fingerprint: &str, salt: &[u8]) -> Result<[u8; 32]> {
    let hk = Hkdf::<Sha256>::new(Some(salt), fingerprint.as_bytes());
    let mut key = [0u8; 32];
    hk.expand(b"ai-agency-vault-key-v1", &mut key)
        .map_err(|e| anyhow::anyhow!("HKDF error: {e}"))?;
    Ok(key)
}

fn encrypt_aes(key: &[u8; 32], plaintext: &[u8]) -> Result<Vec<u8>> {
    let cipher = Aes256Gcm::new_from_slice(key).unwrap();
    let mut nonce_bytes = [0u8; 12];
    OsRng.fill_bytes(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);
    let ciphertext = cipher
        .encrypt(nonce, plaintext)
        .map_err(|e| anyhow::anyhow!("Encryption error: {e}"))?;
    let mut output = Vec::with_capacity(12 + ciphertext.len());
    output.extend_from_slice(&nonce_bytes);
    output.extend(ciphertext);
    Ok(output)
}

fn decrypt_aes(key: &[u8; 32], data: &[u8]) -> Result<Vec<u8>> {
    if data.len() < 12 {
        anyhow::bail!("Data too short");
    }
    let (nonce_bytes, ciphertext) = data.split_at(12);
    let cipher = Aes256Gcm::new_from_slice(key).unwrap();
    let nonce = Nonce::from_slice(nonce_bytes);
    cipher
        .decrypt(nonce, ciphertext)
        .map_err(|e| anyhow::anyhow!("Decryption failed: {e}"))
}

fn create_tar_gz(source_dir: &Path) -> Result<Vec<u8>> {
    let mut tar_data = Vec::new();
    {
        let encoder = flate2::write::GzEncoder::new(&mut tar_data, flate2::Compression::default());
        let mut tar_builder = tar::Builder::new(encoder);
        tar_builder.append_dir_all(".", source_dir)?;
        let enc = tar_builder.into_inner()?;
        enc.finish()?;
    }
    Ok(tar_data)
}

fn read_salt_from_license(license_path: &str) -> Result<Vec<u8>> {
    let data = std::fs::read_to_string(license_path)
        .context("Failed to read license file")?;
    let v: serde_json::Value = serde_json::from_str(&data)?;
    let salt_b64 = v["salt"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("No 'salt' field in license"))?;
    base64::engine::general_purpose::STANDARD
        .decode(salt_b64)
        .context("Invalid salt base64")
}

/// Map folder names to cabinet IDs.
/// Since folder names are now the same as cabinet IDs (all Latin), this is identity.
/// Legacy Cyrillic names are kept for backwards compatibility with old layouts.
fn folder_to_cabinet_id(folder: &str) -> String {
    match folder {
        // Legacy Cyrillic names (old layout)
        "Медиа-аналитик" => "media-analyst".to_string(),
        "Коммуникационный-аналитик" => "communication-analyst".to_string(),
        "Коммуникационный-стратег" => "communication-strategist".to_string(),
        "Креативный-директор" | "Креативная-группа" => "creative-director".to_string(),
        "Юрист-Контракты" => "lawyer-contracts".to_string(),
        "Юрист-NDA-и-претензии" | "Юрист-Претензии" => "lawyer-claims".to_string(),
        "Юрист-Реклама" => "lawyer-advertising".to_string(),
        // Latin names: folder == cabinet_id
        other => other.to_string(),
    }
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    match cli.command {
        Commands::Pack {
            source,
            cabinet_id,
            fingerprint,
            license,
            output_dir,
        } => {
            let salt = read_salt_from_license(&license)?;
            let key = derive_key(&fingerprint, &salt)?;
            let tar_gz = create_tar_gz(Path::new(&source))?;
            let encrypted = encrypt_aes(&key, &tar_gz)?;

            std::fs::create_dir_all(&output_dir)?;
            let vault_path = PathBuf::from(&output_dir).join(format!("{cabinet_id}.vault"));
            std::fs::write(&vault_path, &encrypted)?;

            println!("Vault created: {} ({} bytes)", vault_path.display(), encrypted.len());
        }

        Commands::Unpack {
            vault,
            fingerprint,
            license,
            output_dir,
        } => {
            let salt = read_salt_from_license(&license)?;
            let key = derive_key(&fingerprint, &salt)?;
            let encrypted = std::fs::read(&vault)?;
            let tar_gz = decrypt_aes(&key, &encrypted)?;

            let decoder = flate2::read::GzDecoder::new(std::io::Cursor::new(&tar_gz));
            let mut archive = tar::Archive::new(decoder);
            std::fs::create_dir_all(&output_dir)?;
            archive.unpack(&output_dir)?;

            println!("Vault unpacked to: {output_dir}");
        }

        Commands::PackAll {
            source,
            fingerprint,
            license,
            output_dir,
        } => {
            let salt = read_salt_from_license(&license)?;
            let key = derive_key(&fingerprint, &salt)?;

            std::fs::create_dir_all(&output_dir)?;

            for entry in std::fs::read_dir(&source)? {
                let entry = entry?;
                if !entry.file_type()?.is_dir() {
                    continue;
                }
                let folder_name = entry.file_name().to_string_lossy().to_string();
                let cabinet_id = folder_to_cabinet_id(&folder_name);

                let tar_gz = create_tar_gz(&entry.path())?;
                let encrypted = encrypt_aes(&key, &tar_gz)?;

                let vault_path = PathBuf::from(&output_dir).join(format!("{cabinet_id}.vault"));
                std::fs::write(&vault_path, &encrypted)?;

                println!(
                    "  {} -> {} ({} bytes)",
                    folder_name,
                    vault_path.display(),
                    encrypted.len()
                );
            }
            println!("All vaults created in: {output_dir}");
        }
    }

    Ok(())
}
