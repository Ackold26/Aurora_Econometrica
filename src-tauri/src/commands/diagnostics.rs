//! Diagnostic report generator for Aurora AI IT support.
//!
//! Collects system info, license status, vault state, logs into a single .txt file.
//! Each section is independently error-safe — a failure in one section does not affect others.
//! SECURITY: No secrets, full fingerprints, tokens, or encryption keys in output.

use std::path::Path;
use std::sync::OnceLock;
use std::time::Instant;

/// App start time — set once on first diagnostic call or app init.
static APP_START: OnceLock<Instant> = OnceLock::new();

/// Call at app startup to record start time.
pub fn mark_app_start() {
    let _ = APP_START.set(Instant::now());
}

/// Collect a full diagnostic report as plain text.
pub fn collect_report(
    app_config_dir: &Path,
    app_data_dir: &Path,
    app_local_data_dir: &Path,
) -> String {
    // Ensure start time is set (fallback if mark_app_start wasn't called)
    let _ = APP_START.set(Instant::now());

    let now = chrono::Local::now().format("%Y-%m-%d %H:%M:%S").to_string();

    let mut report = format!(
        "\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\n\
         \x20 Aurora AI Diagnostics Report\n\
         \x20 Generated: {now}\n\
         \u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\n"
    );

    // Collect log first for Errors Summary
    let log_content = find_and_read_log(app_config_dir);

    report.push_str(&section("Errors Summary", || section_errors_summary(&log_content)));
    report.push_str(&section("Application", || section_app()));
    report.push_str(&section("System", || section_system()));
    report.push_str(&section("Machine ID", || section_machine_id()));
    report.push_str(&section("License", || section_license(app_config_dir)));
    report.push_str(&section("Online Auth", || section_auth(app_config_dir)));
    report.push_str(&section("Vaults", || section_vaults(app_data_dir)));
    report.push_str(&section("Content Packs", || section_content_packs(app_local_data_dir)));
    report.push_str(&section("Claude CLI", || section_claude_cli()));
    let product = crate::commands::online_auth::detect_product();
    if !matches!(product, "legal" | "docmaster") {
        report.push_str(&section("Python / PPTX", || section_python()));
    }
    report.push_str(&section("App Log (last 200 lines)", || section_app_log_from(&log_content)));
    report.push_str(&section("Audit Log (last 20 entries)", || section_audit_log()));

    report
}

// ── Helpers ────────────────────────────────────────────────

fn section(name: &str, f: impl FnOnce() -> String) -> String {
    let content = std::panic::catch_unwind(std::panic::AssertUnwindSafe(f))
        .unwrap_or_else(|_| "[PANIC] Section failed".into());
    format!("\n\u{2500}\u{2500} {} \u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\n{}\n", name, content)
}

fn cmd_output(cmd: &str, args: &[&str]) -> String {
    std::process::Command::new(cmd)
        .args(args)
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_else(|e| format!("(error: {e})"))
}

/// Find log file across multiple possible locations.
fn find_and_read_log(app_config_dir: &Path) -> Option<(std::path::PathBuf, String)> {
    // Candidate directories for log files
    let mut candidates: Vec<std::path::PathBuf> = vec![
        app_config_dir.join("logs"),
    ];
    // Also try %APPDATA%/<identifier>/logs/ and %LOCALAPPDATA%/<identifier>/logs/
    if let Some(id_folder) = app_config_dir.file_name() {
        if let Ok(appdata) = std::env::var("APPDATA") {
            candidates.push(std::path::PathBuf::from(&appdata).join(id_folder).join("logs"));
        }
        if let Ok(local) = std::env::var("LOCALAPPDATA") {
            candidates.push(std::path::PathBuf::from(&local).join(id_folder).join("logs"));
        }
    }
    // Also try the Tauri log location directly
    if let Ok(local) = std::env::var("LOCALAPPDATA") {
        candidates.push(std::path::PathBuf::from(&local).join("com.aurora.econometrica").join("logs"));
    }

    for dir in &candidates {
        if !dir.exists() { continue; }
        if let Ok(entries) = std::fs::read_dir(dir) {
            let log_file = entries
                .flatten()
                .filter(|e| e.path().extension().is_some_and(|ext| ext == "log"))
                .max_by_key(|e| e.metadata().ok().and_then(|m| m.modified().ok()))
                .map(|e| e.path());
            if let Some(path) = log_file {
                let size = std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0);
                if size > 10_000_000 {
                    return Some((path, format!("(log file too large: {} bytes, truncated)", size)));
                }
                if let Ok(content) = std::fs::read_to_string(&path) {
                    return Some((path, content));
                }
            }
        }
    }
    None
}

// ── Sections ───────────────────────────────────────────────

/// Errors Summary — grep ERROR/WARN/PANIC from log, shown at top for IT managers.
fn section_errors_summary(log: &Option<(std::path::PathBuf, String)>) -> String {
    let Some((_, content)) = log else {
        return "(no log file found — cannot extract errors)".into();
    };
    let error_lines: Vec<&str> = content.lines()
        .filter(|l| {
            let upper = l.to_uppercase();
            upper.contains("[ERROR]") || upper.contains("[WARN]") || upper.contains("PANIC")
        })
        .collect();

    if error_lines.is_empty() {
        return "No errors or warnings found in log.".into();
    }

    // Deduplicate by message (keep last occurrence)
    let mut seen = std::collections::HashMap::<String, &str>::new();
    for line in &error_lines {
        // Extract message part after timestamp+module
        let msg_part = line.splitn(4, ']').last().unwrap_or(line).trim();
        seen.insert(msg_part.to_string(), line);
    }
    let mut unique: Vec<&&str> = seen.values().collect();
    unique.sort();

    let total = error_lines.len();
    let unique_count = unique.len();
    let mut result = format!("Total: {} errors/warnings ({} unique)\n\n", total, unique_count);
    // Show last 20 unique
    for line in unique.iter().rev().take(20) {
        result.push_str(line);
        result.push('\n');
    }
    result
}

fn section_app() -> String {
    let name = env!("CARGO_PKG_NAME");
    let version = env!("CARGO_PKG_VERSION");
    let product = crate::commands::online_auth::detect_product();
    let uptime = APP_START.get()
        .map(|s| {
            let secs = s.elapsed().as_secs();
            if secs < 60 { format!("{}s", secs) }
            else if secs < 3600 { format!("{}m {}s", secs / 60, secs % 60) }
            else { format!("{}h {}m", secs / 3600, (secs % 3600) / 60) }
        })
        .unwrap_or_else(|| "(unknown)".into());
    format!("Name:           {name}\nVersion:        {version}\nProduct:        {product}\nUptime:         {uptime}")
}

fn section_system() -> String {
    let os = std::env::consts::OS;
    let arch = std::env::consts::ARCH;
    let winver = cmd_output("cmd", &["/C", "ver"]);
    let hostname = std::env::var("COMPUTERNAME").unwrap_or_else(|_| "(unknown)".into());

    // Disk free space — use fsutil for reliable output
    let disk_free = std::env::var("APPDATA")
        .ok()
        .and_then(|p| p.chars().next())
        .map(|drive| {
            let out = cmd_output("fsutil", &["volume", "diskfree", &format!("{drive}:")]);
            // Parse "Total free bytes" line
            out.lines()
                .find(|l| l.contains("free bytes") && !l.contains("caller"))
                .and_then(|l| l.split(':').last())
                .map(|v| {
                    let bytes: u64 = v.trim().replace([',', ' ', '.'], "").parse().unwrap_or(0);
                    format!("{:.1} GB", bytes as f64 / 1_073_741_824.0)
                })
                .unwrap_or_else(|| "(parse error)".into())
        })
        .unwrap_or_else(|| "(unknown)".into());

    // WebView2 version
    let wv2 = cmd_output("reg", &[
        "query",
        r"HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        "/v", "pv",
    ]);
    let wv2_ver = wv2.lines()
        .find(|l| l.contains("pv"))
        .and_then(|l| l.split_whitespace().last())
        .unwrap_or("(not found)");

    format!(
        "OS:             {os} {arch}\n\
         Windows:        {winver}\n\
         Hostname:       {hostname}\n\
         WebView2:       {wv2_ver}\n\
         Disk Free:      {disk_free}"
    )
}

fn section_machine_id() -> String {
    match crate::crypto::fingerprint::get_machine_fingerprint() {
        Ok(fp) => {
            let truncated = &fp[..fp.len().min(12)];
            // Also show license-bound hash for comparison
            let hash = crate::crypto::fingerprint::hash_fingerprint(&fp);
            let hash_short = &hash[..hash.len().min(12)];
            format!("ID:             {truncated} (truncated)\nLicense Hash:   {hash_short}... (for support matching)")
        }
        Err(e) => format!("[ERROR] {e}"),
    }
}

fn section_license(config_dir: &Path) -> String {
    match crate::commands::license::License::load(config_dir) {
        Ok(lic) => match lic.validate() {
            Ok(status) => format!(
                "Status:         {}\n\
                 Issued To:      {}\n\
                 Expires:        {}\n\
                 Days Left:      {}\n\
                 Cabinets:       {}\n\
                 Machine Match:  {}",
                if status.valid { "valid" } else { "INVALID" },
                status.issued_to,
                status.expires_at,
                status.days_remaining,
                status.cabinets.join(", "),
                if status.error.is_none() { "yes" } else { "NO — license bound to different machine" }
            ),
            Err(e) => format!("[ERROR] Validation: {e}"),
        },
        Err(e) => format!("[ERROR] Load: {e}"),
    }
}

fn section_auth(config_dir: &Path) -> String {
    let cache_path = config_dir.join("session_cache.json");
    if !cache_path.exists() {
        return "Cache:          not found (first run or cleared)".into();
    }
    match std::fs::read_to_string(&cache_path) {
        Ok(data) => match serde_json::from_str::<serde_json::Value>(&data) {
            Ok(json) => {
                let status = json["response"]["status"].as_str().unwrap_or("?");
                let expires = json["response"]["expires_at"].as_str().unwrap_or("?");
                let cached_at = json["cached_at"].as_u64().unwrap_or(0);
                let age_hours = if cached_at > 0 {
                    let now = std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .map(|d| d.as_secs())
                        .unwrap_or(0);
                    (now.saturating_sub(cached_at)) / 3600
                } else { 0 };
                format!(
                    "Cache:          exists (age: {age_hours}h)\n\
                     Last Status:    {status}\n\
                     Server Expiry:  {expires}"
                )
            }
            Err(e) => format!("Cache:          exists but invalid JSON ({e})"),
        },
        Err(e) => format!("[ERROR] Read: {e}"),
    }
}

fn section_vaults(data_dir: &Path) -> String {
    let vaults_dir = crate::commands::vault::vaults_dir(data_dir);
    if !vaults_dir.exists() {
        return "Directory:      not found".into();
    }

    // Determine expected vaults for this product
    let product = crate::commands::online_auth::detect_product();
    let expected: Vec<String> = crate::commands::cabinet::filter_by_product(
        product,
        crate::commands::cabinet::get_cabinet_definitions(),
    ).iter().map(|c| crate::commands::vault::vault_filename_pub(&c.id)).collect();

    let mut lines = vec![format!("Directory:      {}", vaults_dir.display())];
    match std::fs::read_dir(&vaults_dir) {
        Ok(entries) => {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                let meta = entry.metadata().ok();
                let size = meta.as_ref().map(|m| m.len()).unwrap_or(0);
                let modified = meta
                    .and_then(|m| m.modified().ok())
                    .map(|t| chrono::DateTime::<chrono::Local>::from(t).format("%Y-%m-%d %H:%M").to_string())
                    .unwrap_or_else(|| "?".into());
                let tag = if expected.contains(&name) { "[expected]" } else { "[stale]" };
                lines.push(format!("  {name:<30} {size:>8} bytes    {modified}  {tag}"));
            }
            if lines.len() == 1 { lines.push("  (empty)".into()); }
        }
        Err(e) => lines.push(format!("[ERROR] {e}")),
    }
    lines.join("\n")
}

fn section_content_packs(local_data_dir: &Path) -> String {
    let verified = crate::commands::content_pack::verify_content_packs(local_data_dir)
        .map(|v| if v { "true" } else { "false (no manifest)" })
        .unwrap_or("FAILED");
    let dir = crate::commands::content_pack::content_packs_dir(local_data_dir);
    let file_count = std::fs::read_dir(&dir)
        .map(|e| e.count())
        .unwrap_or(0);
    format!("Verified:       {verified}\nDirectory:      {}\nFiles:          {file_count}", dir.display())
}

fn section_claude_cli() -> String {
    let candidates = [
        std::env::var("USERPROFILE").map(|p| format!("{p}\\.local\\bin\\claude.exe")).unwrap_or_default(),
        std::env::var("APPDATA").map(|p| format!("{p}\\Claude\\claude.exe")).unwrap_or_default(),
    ];
    for path in &candidates {
        if !path.is_empty() && std::path::Path::new(path).exists() {
            return format!("Found:          yes\nPath:           {path}");
        }
    }
    let which = cmd_output("where", &["claude"]);
    if !which.is_empty() && !which.contains("Could not find") {
        return format!("Found:          yes (PATH)\nPath:           {}", which.lines().next().unwrap_or("?"));
    }
    "Found:          no\nPath:           (not found in common locations or PATH)".into()
}

fn section_python() -> String {
    let status = crate::commands::pptx_processor::check_dependencies();
    let mut lines = Vec::new();
    if status.python_available {
        lines.push(format!("Python:         {}", status.python_version));
        if status.missing_packages.is_empty() {
            lines.push("Packages:       all OK".into());
        } else {
            lines.push(format!("Missing:        {}", status.missing_packages.join(", ")));
        }
    } else {
        lines.push("Python:         NOT FOUND".into());
    }
    lines.join("\n")
}

fn section_app_log_from(log: &Option<(std::path::PathBuf, String)>) -> String {
    let Some((path, content)) = log else {
        return "(no log file found in any known location)".into();
    };
    let size = content.len();
    let lines: Vec<&str> = content.lines().collect();
    let start = lines.len().saturating_sub(200);
    format!("File: {} ({} bytes, {} total lines)\n\n{}",
        path.display(), size, lines.len(),
        lines[start..].join("\n"))
}

fn section_audit_log() -> String {
    let audit_path = std::env::var("LOCALAPPDATA")
        .map(|p| std::path::PathBuf::from(p).join("AIAgency").join("audit.log"))
        .unwrap_or_default();
    if !audit_path.exists() {
        return "(audit.log not found)".into();
    }
    match std::fs::read_to_string(&audit_path) {
        Ok(content) => {
            let lines: Vec<&str> = content.lines().collect();
            let start = lines.len().saturating_sub(20);
            lines[start..].join("\n")
        }
        Err(e) => format!("[ERROR] {e}"),
    }
}
