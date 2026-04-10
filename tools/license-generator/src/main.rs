use base64::Engine;
use clap::{Parser, Subcommand};
use ed25519_dalek::{Signer, SigningKey};
use rand::rngs::OsRng;
use serde::{Deserialize, Serialize};


#[derive(Parser)]
#[command(name = "license-gen", about = "AI Agency license generator")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Generate a new Ed25519 keypair
    Keygen {
        /// Output path for the keypair JSON
        #[arg(short, long, default_value = "keypair.json")]
        output: String,
    },
    /// Generate a license for a specific machine
    Generate {
        /// Path to the keypair JSON
        #[arg(short, long)]
        keypair: String,
        /// Company name
        #[arg(long)]
        issued_to: String,
        /// Machine fingerprint hash (first 12 chars shown in GUI Settings)
        #[arg(long)]
        machine_hash: String,
        /// Comma-separated cabinet IDs
        #[arg(long)]
        cabinets: String,
        /// Expiry date (YYYY-MM-DD)
        #[arg(long, default_value = "2027-12-31")]
        expires: String,
        /// Output path for the license JSON
        #[arg(short, long, default_value = "license.json")]
        output: String,
    },
    /// Show the public key bytes (for embedding in the binary)
    ShowPubkey {
        /// Path to the keypair JSON
        #[arg(short, long)]
        keypair: String,
    },
}

#[derive(Serialize, Deserialize)]
struct KeypairFile {
    secret_key: String, // base64
    public_key: String, // base64
}

#[derive(Serialize, Deserialize)]
struct License {
    license_id: String,
    issued_to: String,
    expires_at: String,
    machine_fingerprint_hash: String,
    cabinets: Vec<String>,
    salt: String,
    signature: String,
}

fn main() {
    let cli = Cli::parse();

    match cli.command {
        Commands::Keygen { output } => {
            let signing_key = SigningKey::generate(&mut OsRng);
            let verifying_key = signing_key.verifying_key();

            let kf = KeypairFile {
                secret_key: base64::engine::general_purpose::STANDARD.encode(signing_key.to_bytes()),
                public_key: base64::engine::general_purpose::STANDARD.encode(verifying_key.to_bytes()),
            };

            let json = serde_json::to_string_pretty(&kf).unwrap();
            std::fs::write(&output, &json).unwrap();
            println!("Keypair saved to: {output}");
            println!("Public key (hex): {}", hex::encode(verifying_key.to_bytes()));
            println!(
                "Public key (Rust array): {:?}",
                verifying_key.to_bytes()
            );
        }

        Commands::Generate {
            keypair,
            issued_to,
            machine_hash,
            cabinets,
            expires,
            output,
        } => {
            // Load keypair
            let kf: KeypairFile =
                serde_json::from_str(&std::fs::read_to_string(&keypair).unwrap()).unwrap();
            let secret_bytes = base64::engine::general_purpose::STANDARD
                .decode(&kf.secret_key)
                .unwrap();
            let signing_key = SigningKey::from_bytes(&secret_bytes.try_into().unwrap());

            // Generate salt
            let mut salt_bytes = [0u8; 32];
            rand::RngCore::fill_bytes(&mut OsRng, &mut salt_bytes);
            let salt = base64::engine::general_purpose::STANDARD.encode(salt_bytes);

            // Resolve full machine hash if only prefix given
            let full_hash = if machine_hash.len() < 64 {
                // Assume it's a prefix — store as-is (the app will compare prefixes)
                eprintln!(
                    "Warning: received partial hash ({} chars). For production, use full SHA-256 hash.",
                    machine_hash.len()
                );
                machine_hash
            } else {
                machine_hash
            };

            let cabinet_list: Vec<String> = cabinets.split(',').map(|s| s.trim().to_string()).collect();

            let license_id = uuid::Uuid::new_v4().to_string();

            // Build canonical JSON for signing
            let canonical = format!(
                r#"{{"cabinets":{},"expires_at":"{}","issued_to":"{}","license_id":"{}","machine_fingerprint_hash":"{}","salt":"{}"}}"#,
                serde_json::to_string(&cabinet_list).unwrap(),
                expires,
                issued_to,
                license_id,
                full_hash,
                salt,
            );

            let signature = signing_key.sign(canonical.as_bytes());
            let sig_b64 = base64::engine::general_purpose::STANDARD.encode(signature.to_bytes());

            let license = License {
                license_id,
                issued_to,
                expires_at: expires,
                machine_fingerprint_hash: full_hash,
                cabinets: cabinet_list,
                salt,
                signature: sig_b64,
            };

            let json = serde_json::to_string_pretty(&license).unwrap();
            std::fs::write(&output, &json).unwrap();
            println!("License saved to: {output}");
        }

        Commands::ShowPubkey { keypair } => {
            let kf: KeypairFile =
                serde_json::from_str(&std::fs::read_to_string(&keypair).unwrap()).unwrap();
            let pub_bytes = base64::engine::general_purpose::STANDARD
                .decode(&kf.public_key)
                .unwrap();
            println!("Hex: {}", hex::encode(&pub_bytes));
            println!("Rust bytes: {:?}", pub_bytes.as_slice());
        }
    }
}
