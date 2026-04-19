//! Econometrica sidecar lifecycle management — start, health check, auto-respawn, stop.
//!
//! Features:
//! - Cold start in Tauri setup() (unchanged)
//! - Proactive watchdog (tokio task) — respawns on freeze/crash every 15s
//! - Reactive recovery via `ensure_alive()` — called by post_json on connect errors
//! - Zombie detection: TCP accepts but HTTP fails → force-kill + respawn
//! - Exponential backoff + banned cooldown (5 min) — prevents spin on broken env
//! - Force restart API for UI "Перезапустить модуль" button
//!
//! Production: launches bundled econometrica-sidecar.exe from resource_dir.
//! Dev: launches `python -B server.py` from sidecar/econometrica/ source directory.
//!
//! CRITICAL: Always use Stdio::null() — piped() without reading causes deadlock.

use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use log::{error, info, warn};
use tauri::{AppHandle, Manager};
use tokio::sync::Mutex as AsyncMutex;
use wait_timeout::ChildExt;

const CHILD_WAIT_TIMEOUT: Duration = Duration::from_secs(3);

const SIDECAR_PORT: u16 = 7430;
const MAX_CONSECUTIVE_FAILS: u32 = 5;
const BANNED_COOLDOWN_SECS: u64 = 300; // 5 min after max fails
const WATCHDOG_INTERVAL_SECS: u64 = 15;
const WATCHDOG_FAIL_THRESHOLD: u32 = 3; // 3 × 15s = 45s before respawn
const WATCHDOG_STARTUP_DELAY_SECS: u64 = 30; // grace period after cold start
const HEALTH_TIMEOUT_SECS: u64 = 1;

static SIDECAR_PROCESS: OnceLock<Mutex<Option<Child>>> = OnceLock::new();
static APP_HANDLE: OnceLock<AppHandle> = OnceLock::new();
static RESPAWN_LOCK: OnceLock<AsyncMutex<()>> = OnceLock::new();
static HEALTH_CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
static CONSECUTIVE_FAILS: AtomicU32 = AtomicU32::new(0);
static BANNED_UNTIL: AtomicU64 = AtomicU64::new(0); // unix secs

// ── Internal state helpers ───────────────────────────────────────────────────

fn process_lock() -> &'static Mutex<Option<Child>> {
    SIDECAR_PROCESS.get_or_init(|| Mutex::new(None))
}

fn respawn_lock() -> &'static AsyncMutex<()> {
    RESPAWN_LOCK.get_or_init(|| AsyncMutex::new(()))
}

fn health_client() -> &'static reqwest::Client {
    HEALTH_CLIENT.get_or_init(|| {
        reqwest::Client::builder()
            .timeout(Duration::from_secs(HEALTH_TIMEOUT_SECS))
            .build()
            .unwrap_or_default()
    })
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn store_child(child: Child) {
    if let Ok(mut lock) = process_lock().lock() {
        *lock = Some(child);
    }
}

fn take_child() -> Option<Child> {
    process_lock().lock().ok().and_then(|mut l| l.take())
}

// ── Health probes ────────────────────────────────────────────────────────────

/// TCP probe — fast but insufficient: uvicorn may accept TCP while deadlocked.
fn tcp_responsive() -> bool {
    use std::net::TcpStream;
    TcpStream::connect_timeout(
        &format!("127.0.0.1:{SIDECAR_PORT}")
            .parse()
            .unwrap_or_else(|_| "127.0.0.1:7430".parse().unwrap()),
        Duration::from_millis(500),
    )
    .is_ok()
}

/// HTTP health check — detects deadlocked sidecar that accepts TCP but can't process.
async fn is_healthy() -> bool {
    matches!(
        health_client()
            .get(format!("http://127.0.0.1:{SIDECAR_PORT}/health"))
            .send()
            .await,
        Ok(r) if r.status().is_success()
    )
}

// ── Port cleanup (zombie kill) ───────────────────────────────────────────────

/// Проверить что процесс с PID — наш sidecar (python или econometrica-sidecar.exe).
/// Предохраняет от случайного kill'а чужой службы, занявшей порт 7430.
#[cfg(windows)]
fn is_our_sidecar_process(pid: u32) -> bool {
    use std::os::windows::process::CommandExt;
    let out = Command::new("tasklist")
        .args(["/FI", &format!("PID eq {pid}"), "/FO", "CSV", "/NH"])
        .creation_flags(0x08000000)
        .output();
    let Ok(out) = out else { return false };
    let s = String::from_utf8_lossy(&out.stdout).to_lowercase();
    s.contains("python") || s.contains("econometrica-sidecar")
}

/// Kill zombie sidecar on port 7430. Убивает ТОЛЬКО процессы чьё имя совпадает
/// с python/econometrica-sidecar — чужие процессы (например, dev-сервер) не трогает.
#[cfg(windows)]
fn kill_on_port() {
    use std::os::windows::process::CommandExt;
    let output = Command::new("cmd")
        .args([
            "/C",
            &format!("netstat -ano -p tcp | findstr :{SIDECAR_PORT}"),
        ])
        .creation_flags(0x08000000)
        .output();
    let Ok(output) = output else { return };

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut pids = std::collections::HashSet::new();
    for line in stdout.lines() {
        if let Some(pid_str) = line.split_whitespace().last() {
            if let Ok(pid) = pid_str.parse::<u32>() {
                if pid != 0 {
                    pids.insert(pid);
                }
            }
        }
    }
    for pid in pids {
        if !is_our_sidecar_process(pid) {
            warn!(
                "Port {SIDECAR_PORT} owned by PID={pid} (not python/econometrica-sidecar) — skipping kill"
            );
            continue;
        }
        info!("Killing zombie sidecar PID={pid} on port {SIDECAR_PORT}");
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .creation_flags(0x08000000)
            .output();
    }
}

#[cfg(not(windows))]
fn kill_on_port() {
    // Best-effort: kill stored child. Unix alternative: lsof -ti :7430 | xargs kill -9.
    if let Some(mut child) = take_child() {
        let _ = child.kill();
        let _ = child.wait_timeout(CHILD_WAIT_TIMEOUT);
    }
}

// ── Spawn paths ──────────────────────────────────────────────────────────────

fn spawn_bundled_exe(app_handle: &AppHandle) -> Result<Child, String> {
    // Try both paths: direct and _up_/ (Tauri replaces ../ with _up_/ in bundle)
    let resolve = |p: &str| {
        app_handle
            .path()
            .resolve(p, tauri::path::BaseDirectory::Resource)
            .ok()
    };
    let exe_path = [
        "sidecar/econometrica/econometrica-sidecar.exe",
        "_up_/sidecar/econometrica/econometrica-sidecar.exe",
    ]
    .iter()
    .filter_map(|p| resolve(p))
    .find(|p| p.exists())
    .ok_or_else(|| "Bundled sidecar not found in sidecar/ or _up_/sidecar/".to_string())?;

    let mut cmd = Command::new(&exe_path);
    cmd.stdout(Stdio::null()).stderr(Stdio::null());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }

    cmd.spawn()
        .map_err(|e| format!("Failed to spawn bundled sidecar: {e}"))
}

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
        cmd.creation_flags(0x08000000);
    }

    cmd.spawn()
        .map_err(|e| format!("Failed to spawn python sidecar: {e}"))
}

/// Production → bundled exe; dev → python server.py. Shared by start + respawn.
fn spawn_sidecar_proc(app_handle: &AppHandle) -> Result<Child, String> {
    if !cfg!(debug_assertions) {
        match spawn_bundled_exe(app_handle) {
            Ok(c) => return Ok(c),
            Err(e) => warn!("Bundled sidecar failed, falling back to python: {e}"),
        }
    }
    spawn_python_dev()
}

// ── Public API ───────────────────────────────────────────────────────────────

/// Cold start — call once from setup(). Stores app handle for later respawns.
/// Skips startup if sidecar already responding (orphan from previous crash).
pub fn start_sidecar(app_handle: &AppHandle) {
    // Store handle globally so ensure_alive() can respawn without explicit param
    let _ = APP_HANDLE.set(app_handle.clone());

    if tcp_responsive() {
        info!("Econometrica sidecar already running on :{SIDECAR_PORT} — reusing");
        return;
    }

    match spawn_sidecar_proc(app_handle) {
        Ok(child) => {
            info!("Econometrica sidecar started (PID={})", child.id());
            store_child(child);
        }
        Err(e) => {
            warn!("Failed to start econometrica sidecar: {e}. Compute features will be unavailable.");
        }
    }
}

/// Wait for sidecar to be healthy. Returns true if ready within timeout.
/// Uses exponential backoff: fast initial checks, slower later. Total max ~23s.
pub async fn wait_for_sidecar_ready() -> bool {
    let delays_ms = [300, 500, 1000, 1000, 2000, 2000, 3000, 3000, 5000, 5000];
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
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
                tokio::time::sleep(Duration::from_millis(delay_ms)).await;
            }
        }
    }

    error!("Econometrica sidecar did not become healthy within timeout");
    false
}

/// Ensure sidecar is alive; respawn if not. Idempotent, thread-safe, bounded retries.
///
/// Called from:
/// - `post_json()` in econometrica.rs on connect errors (reactive recovery)
/// - `spawn_watchdog()` tick on repeated health failures (proactive)
///
/// Returns true iff sidecar is healthy at return time.
pub async fn ensure_alive() -> bool {
    // Fast path — already healthy
    if is_healthy().await {
        CONSECUTIVE_FAILS.store(0, Ordering::Relaxed);
        return true;
    }

    // Respect banned cooldown (avoid thrash on broken Python env)
    let banned_until = BANNED_UNTIL.load(Ordering::Relaxed);
    let now = now_secs();
    if banned_until > now {
        warn!(
            "Sidecar respawn banned for {}s (broken env suspected — use manual restart)",
            banned_until - now
        );
        return false;
    }

    let Some(app_handle) = APP_HANDLE.get() else {
        error!("Cannot respawn sidecar: APP_HANDLE not initialized");
        return false;
    };

    // Serialize respawn — only one thread spawns at a time
    let _guard = respawn_lock().lock().await;

    // Double-check after acquiring lock — another thread may have revived it
    if is_healthy().await {
        CONSECUTIVE_FAILS.store(0, Ordering::Relaxed);
        return true;
    }

    let fails = CONSECUTIVE_FAILS.fetch_add(1, Ordering::Relaxed) + 1;
    info!("Sidecar unhealthy — respawn attempt #{fails}");

    // Exponential backoff between retries (skip on first attempt)
    if fails > 1 {
        let backoff_secs = 2_u64.pow((fails - 1).min(4)); // 2, 4, 8, 16, 16
        tokio::time::sleep(Duration::from_secs(backoff_secs)).await;
    }

    // Zombie detection: TCP open but HTTP dead → uvicorn deadlocked, force-kill
    if tcp_responsive() {
        warn!("Sidecar TCP accepts but HTTP unresponsive — killing deadlocked process");
        kill_on_port();
        tokio::time::sleep(Duration::from_secs(1)).await;
    }

    // Reap prev Child handle (dead anyway, avoid zombie)
    if let Some(mut child) = take_child() {
        let _ = child.kill();
        let _ = child.wait_timeout(CHILD_WAIT_TIMEOUT);
    }

    match spawn_sidecar_proc(app_handle) {
        Ok(child) => {
            info!("Sidecar respawned (PID={}) — waiting for health", child.id());
            store_child(child);
        }
        Err(e) => {
            error!("Respawn spawn failed: {e}");
            maybe_ban(fails);
            return false;
        }
    }

    let healthy = wait_for_sidecar_ready().await;
    if healthy {
        CONSECUTIVE_FAILS.store(0, Ordering::Relaxed);
        info!("Sidecar respawn successful");
    } else {
        error!("Sidecar respawned but did not reach healthy state");
        maybe_ban(fails);
    }
    healthy
}

fn maybe_ban(fails: u32) {
    if fails >= MAX_CONSECUTIVE_FAILS {
        let until = now_secs() + BANNED_COOLDOWN_SECS;
        BANNED_UNTIL.store(until, Ordering::Relaxed);
        error!(
            "Sidecar failed {fails}× — banning auto-respawn for {BANNED_COOLDOWN_SECS}s. \
             Check Python env / MCMC logs. Use manual restart to clear."
        );
    }
}

/// Force restart — bypass banned cooldown, reset counters, kill + spawn fresh.
/// Surfaced via Tauri command `econ_sidecar_restart` for UI "Перезапустить модуль" button.
pub async fn force_restart() -> Result<(), String> {
    CONSECUTIVE_FAILS.store(0, Ordering::Relaxed);
    BANNED_UNTIL.store(0, Ordering::Relaxed);

    let _guard = respawn_lock().lock().await;

    if tcp_responsive() {
        kill_on_port();
        tokio::time::sleep(Duration::from_secs(1)).await;
    }
    if let Some(mut child) = take_child() {
        let _ = child.kill();
        let _ = child.wait_timeout(CHILD_WAIT_TIMEOUT);
    }

    let app_handle = APP_HANDLE
        .get()
        .ok_or_else(|| "APP_HANDLE not initialized".to_string())?;
    let child = spawn_sidecar_proc(app_handle)?;
    info!("Sidecar force-restarted (PID={})", child.id());
    store_child(child);

    if wait_for_sidecar_ready().await {
        Ok(())
    } else {
        Err("Sidecar did not become healthy within timeout".to_string())
    }
}

/// Background watchdog — proactively respawns sidecar on freeze/crash.
/// Call once from setup() after start_sidecar(). Runs for app lifetime.
///
/// Uses `tauri::async_runtime::spawn` (not `tokio::spawn`) — setup() runs before
/// tokio runtime is attached to main thread, direct tokio::spawn would panic with
/// "no reactor running". async_runtime::spawn routes to Tauri's managed runtime.
pub fn spawn_watchdog() {
    tauri::async_runtime::spawn(async move {
        // Grace period before monitoring (cold start may take ~15s for MCMC JIT warmup)
        tokio::time::sleep(Duration::from_secs(WATCHDOG_STARTUP_DELAY_SECS)).await;

        let mut consecutive_fails = 0u32;
        loop {
            tokio::time::sleep(Duration::from_secs(WATCHDOG_INTERVAL_SECS)).await;

            if is_healthy().await {
                if consecutive_fails > 0 {
                    info!("Watchdog: sidecar recovered");
                }
                consecutive_fails = 0;
                continue;
            }

            consecutive_fails += 1;
            warn!(
                "Watchdog: sidecar unhealthy ({consecutive_fails}/{WATCHDOG_FAIL_THRESHOLD})"
            );

            if consecutive_fails >= WATCHDOG_FAIL_THRESHOLD {
                info!("Watchdog triggering respawn");
                let _ = ensure_alive().await;
                consecutive_fails = 0; // reset regardless — ensure_alive() handles its own retries
            }
        }
    });
}

/// Stop sidecar — call from window close handler. Idempotent.
pub fn stop_sidecar() {
    let Some(mut child) = take_child() else {
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
