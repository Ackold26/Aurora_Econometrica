//! Econometrica sidecar lifecycle management — start, health check, stop.
//!
//! Production: launches bundled econometrica-sidecar.exe from resource_dir.
//! Dev: launches `python -B server.py` from sidecar/econometrica/ source directory.
//!
//! CRITICAL: Always use Stdio::null() — piped() without reading causes deadlock.

use std::process::{Child, Command, Stdio};
use std::sync::{Mutex, OnceLock};

use log::{error, info, warn};
use tauri::Manager;

const SIDECAR_PORT: u16 = 7430;
static SIDECAR_PROCESS: OnceLock<Mutex<Option<Child>>> = OnceLock::new();

// ── Helpers ──────────────────────────────────────────────────────────────────

fn process_lock() -> &'static Mutex<Option<Child>> {
    SIDECAR_PROCESS.get_or_init(|| Mutex::new(None))
}

fn store_child(child: Child) {
    if let Ok(mut lock) = process_lock().lock() {
        *lock = Some(child);
    }
}

/// Check if sidecar is already responding (orphaned process from previous crash).
/// Uses TCP connect only — avoids reqwest::blocking dependency.
fn is_already_running() -> bool {
    use std::net::TcpStream;
    TcpStream::connect_timeout(
        &format!("127.0.0.1:{SIDECAR_PORT}")
            .parse()
            .unwrap_or_else(|_| "127.0.0.1:7430".parse().unwrap()),
        std::time::Duration::from_secs(1),
    )
    .is_ok()
}

// ── Production path (bundled exe) ────────────────────────────────────────────

fn spawn_bundled_exe(app_handle: &tauri::AppHandle) -> Result<Child, String> {
    let exe_path = app_handle
        .path()
        .resolve(
            "sidecar/econometrica/econometrica-sidecar.exe",
            tauri::path::BaseDirectory::Resource,
        )
        .map_err(|e| format!("Resource path error: {e}"))?;

    if !exe_path.exists() {
        return Err(format!(
            "Bundled sidecar not found at: {}",
            exe_path.display()
        ));
    }

    let mut cmd = Command::new(&exe_path);
    cmd.stdout(Stdio::null()).stderr(Stdio::null());

    // Prevent console window on Windows
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }

    cmd.spawn()
        .map_err(|e| format!("Failed to spawn bundled sidecar: {e}"))
}

// ── Dev path (python server.py) ───────────────────────────────────────────────

fn spawn_python_dev() -> Result<Child, String> {
    let manifest_dir = std::env::var("CARGO_MANIFEST_DIR").unwrap_or_else(|_| ".".to_string());
    let sidecar_dir = std::path::Path::new(&manifest_dir)
        .parent()
        .unwrap_or(std::path::Path::new("."))
        .join("sidecar")
        .join("econometrica");

    if !sidecar_dir.join("server.py").exists() {
        return Err(format!(
            "server.py not found at: {}",
            sidecar_dir.display()
        ));
    }

    #[cfg(windows)]
    let python = "python";
    #[cfg(not(windows))]
    let python = "python3";

    let mut cmd = Command::new(python);
    cmd.args(["-B", "server.py"])
        .current_dir(&sidecar_dir)
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }

    cmd.spawn()
        .map_err(|e| format!("Failed to spawn python sidecar: {e}"))
}

// ── Public API ────────────────────────────────────────────────────────────────

/// Start the sidecar. Call from Tauri setup() callback.
/// Skips startup if sidecar is already responding (orphaned from previous crash).
pub fn start_sidecar(app_handle: &tauri::AppHandle) {
    // Reuse orphaned process from previous crash
    if is_already_running() {
        info!("Econometrica sidecar already running on :{SIDECAR_PORT} — reusing");
        return;
    }

    // Production: bundled exe
    if !cfg!(debug_assertions) {
        match spawn_bundled_exe(app_handle) {
            Ok(child) => {
                info!(
                    "Econometrica sidecar started from bundled exe (PID={})",
                    child.id()
                );
                store_child(child);
                return;
            }
            Err(e) => warn!("Bundled sidecar failed, falling back to dev: {e}"),
        }
    }

    // Dev fallback: python server.py
    match spawn_python_dev() {
        Ok(child) => {
            info!(
                "Econometrica sidecar started via python (PID={})",
                child.id()
            );
            store_child(child);
        }
        Err(e) => {
            warn!("Failed to start econometrica sidecar: {e}. Compute features will be unavailable.");
        }
    }
}

/// Wait for sidecar to be healthy. Returns true if ready within timeout.
/// Uses exponential backoff: fast initial checks, slower later.
/// Total wait: ~23 seconds max (10 attempts).
pub async fn wait_for_sidecar_ready() -> bool {
    let delays_ms = [300, 500, 1000, 1000, 2000, 2000, 3000, 3000, 5000, 5000];
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build()
        .unwrap_or_default();

    for (attempt, &delay_ms) in delays_ms.iter().enumerate() {
        match client
            .get(format!("http://127.0.0.1:{SIDECAR_PORT}/health"))
            .send()
            .await
        {
            Ok(resp) if resp.status().is_success() => {
                info!(
                    "Econometrica sidecar healthy after {} attempt(s)",
                    attempt + 1
                );
                return true;
            }
            _ => {
                if attempt == 0 {
                    info!("Waiting for econometrica sidecar to start...");
                }
                tokio::time::sleep(std::time::Duration::from_millis(delay_ms)).await;
            }
        }
    }

    error!("Econometrica sidecar did not become healthy within timeout. Compute features unavailable.");
    false
}

/// Stop the sidecar. Call from window close handler.
pub fn stop_sidecar() {
    let Ok(mut lock) = process_lock().lock() else {
        return;
    };
    let Some(mut child) = lock.take() else {
        return;
    };

    let pid = child.id();

    // On Windows: kill entire process tree to catch uvicorn workers
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .creation_flags(0x08000000)
            .output();
    }

    let _ = child.kill();
    let _ = child.wait();
    info!("Econometrica sidecar stopped (was PID={pid})");
}
