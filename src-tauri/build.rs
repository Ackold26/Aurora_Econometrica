fn main() {
    tauri_build::build();
    // Embed build timestamp (Unix seconds) - used for system clock sanity check
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    println!("cargo:rustc-env=BUILD_TIMESTAMP={secs}");
    println!("cargo:rerun-if-changed=build.rs");
}
