use anyhow::{Context, Result};
use log::{debug, error, info, warn};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

use crate::crypto;

/// Active session - decrypted vault in a temp directory.
pub struct Session {
    pub cabinet_id: String,
    pub work_dir: PathBuf,
    pub temp_dir: PathBuf,
    pub user_workspace: PathBuf,
    pub first_message_sent: bool,
    /// Claude CLI session ID for resuming conversations via --resume.
    pub claude_session_id: Option<String>,
}

/// Manages active sessions per cabinet.
pub struct SessionManager {
    sessions: Mutex<HashMap<String, Session>>,
    sessions_root: PathBuf,
}

impl SessionManager {
    pub fn new() -> Result<Self> {
        let local_app_data = std::env::var("LOCALAPPDATA")
            .unwrap_or_else(|_| "C:\\Users\\Default\\AppData\\Local".to_string());
        let sessions_root = PathBuf::from(&local_app_data)
            .join("AIAgency")
            .join("sessions");
        std::fs::create_dir_all(&sessions_root)
            .context("Failed to create sessions directory")?;

        // Restrict directory access to current user only (prevent other users from reading decrypted vaults)
        if let Ok(username) = std::env::var("USERNAME") {
            let domain = std::env::var("USERDOMAIN")
                .or_else(|_| std::env::var("COMPUTERNAME"))
                .unwrap_or_default();
            let qualified = if domain.is_empty() {
                username.clone()
            } else {
                format!("{domain}\\{username}")
            };
            let mut icacls_cmd = std::process::Command::new("icacls");
            icacls_cmd.args([
                sessions_root.to_str().unwrap_or_default(),
                "/inheritance:r",
                "/grant:r",
                &format!("{qualified}:(OI)(CI)F"),
            ]);
            #[cfg(windows)]
            icacls_cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
            match icacls_cmd
                .output()
            {
                Ok(output) if !output.status.success() => {
                    warn!("icacls failed to restrict session directory: {}", String::from_utf8_lossy(&output.stderr));
                }
                Err(e) => warn!("Failed to run icacls: {e}"),
                _ => {}
            }
        }

        Ok(Self {
            sessions: Mutex::new(HashMap::new()),
            sessions_root,
        })
    }

    /// Open a cabinet session: decrypt vault → temp dir, set up workspace.
    pub fn open_session(
        &self,
        cabinet_id: &str,
        vault_data: &[u8],
        encryption_key: &[u8; 32],
        user_workspace: &Path,
    ) -> Result<PathBuf> {
        let mut sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());

        if let Some(existing) = sessions.get(cabinet_id) {
            debug!("Session already open for {cabinet_id}, reusing work_dir");
            return Ok(existing.work_dir.clone());
        }

        info!("Opening new session for cabinet: {cabinet_id}");

        // Decrypt vault (AES-256-GCM)
        let tar_gz_data = crypto::aes::decrypt(encryption_key, vault_data)
            .with_context(|| format!(
                "Failed to decrypt vault for cabinet '{cabinet_id}'. \
                 Vault files must be re-packed for this machine. \
                 Please contact your administrator with your machine fingerprint."
            ))?;
        debug!("Vault decrypted: {} bytes → {} bytes tar.gz", vault_data.len(), tar_gz_data.len());

        // Create temp directory for decrypted skills
        let uid = &uuid::Uuid::new_v4().to_string()[..8];
        let temp_dir = self.sessions_root.join(format!("{cabinet_id}_{uid}"));
        std::fs::create_dir_all(&temp_dir)?;

        // Extract tar.gz with path validation (prevent path traversal & symlink attacks)
        let decoder = flate2::read::GzDecoder::new(std::io::Cursor::new(&tar_gz_data));
        let mut archive = tar::Archive::new(decoder);
        for entry in archive.entries().context("Failed to read vault archive entries")? {
            let mut entry = entry.context("Failed to read vault archive entry")?;

            // Validate path before extraction
            let entry_path = entry.path().context("Invalid path in vault archive")?.to_path_buf();
            let entry_str = entry_path.to_string_lossy().to_string();

            // Skip the root "." directory entry
            if entry_str == "." || entry_str == "./" {
                continue;
            }

            // Reject absolute paths and traversal
            if entry_str.contains("..") || entry_path.is_absolute() {
                anyhow::bail!("Unsafe path in vault archive: {entry_str}");
            }

            // Reject symlinks and hardlinks
            let kind = entry.header().entry_type();
            if kind.is_symlink() || kind.is_hard_link() {
                anyhow::bail!("Symlink/hardlink not allowed in vault archive: {entry_str}");
            }

            entry.unpack_in(&temp_dir)
                .with_context(|| format!("Failed to extract vault entry: {entry_str}"))?;
        }

        // Create work directory and copy ALL vault contents into it
        let work_dir = temp_dir.join("workspace");
        std::fs::create_dir_all(&work_dir)?;

        // Copy everything from extracted vault to workspace
        // (scripts/, .claude/, CLAUDE.md, references/, nda_examples/, etc.)
        for entry in std::fs::read_dir(&temp_dir)? {
            let entry = entry?;
            let name = entry.file_name();
            let name_str = name.to_string_lossy();
            // Skip the workspace dir itself
            if name_str == "workspace" {
                continue;
            }
            let dst = work_dir.join(&name);
            if entry.file_type()?.is_dir() {
                copy_dir_recursive(&entry.path(), &dst)?;
            } else {
                std::fs::copy(entry.path(), &dst)?;
            }
        }

        // Ensure inbox/exports exist in user workspace (Desktop)
        let inbox = user_workspace.join("inbox");
        let exports = user_workspace.join("exports");
        std::fs::create_dir_all(&inbox)?;
        std::fs::create_dir_all(&exports)?;

        // Create real inbox/exports directories in workspace (no junctions - broken with Cyrillic paths)
        std::fs::create_dir_all(work_dir.join("inbox"))?;
        std::fs::create_dir_all(work_dir.join("exports"))?;

        // Append file access restrictions to CLAUDE.md
        let claude_md = work_dir.join("CLAUDE.md");
        if claude_md.exists() {
            let restriction = "\n\n## Ограничения доступа к файлам\n\
                Работай ТОЛЬКО с файлами в текущей рабочей директории (inbox/ и exports/).\n\
                НЕ обращайся к файлам за пределами рабочей директории.\n\
                НЕ используй абсолютные пути, переменные окружения (USERPROFILE, APPDATA) или пути вида Desktop/AIAgency/ для доступа к другим папкам.\n";
            let _ = std::fs::OpenOptions::new()
                .append(true)
                .open(&claude_md)
                .and_then(|mut f| {
                    use std::io::Write;
                    f.write_all(restriction.as_bytes())
                });
        }

        // Initial sync: copy existing inbox files into workspace
        sync_dir_to(&inbox, &work_dir.join("inbox"))?;

        let session = Session {
            cabinet_id: cabinet_id.to_string(),
            work_dir: work_dir.clone(),
            temp_dir,
            user_workspace: user_workspace.to_path_buf(),
            first_message_sent: false,
            claude_session_id: None,
        };
        sessions.insert(cabinet_id.to_string(), session);
        info!("Session ready for {cabinet_id}: work_dir={}", work_dir.display());

        Ok(work_dir)
    }

    /// Get the work directory for an active session.
    pub fn get_work_dir(&self, cabinet_id: &str) -> Option<PathBuf> {
        let sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());
        sessions.get(cabinet_id).map(|s| s.work_dir.clone())
    }

    /// Sync Desktop inbox → workspace/inbox before running Claude.
    pub fn sync_inbox(&self, cabinet_id: &str) -> Result<()> {
        let sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(session) = sessions.get(cabinet_id) {
            let src = session.user_workspace.join("inbox");
            let dst = session.work_dir.join("inbox");
            drop(sessions);
            debug!("Syncing inbox: {} → {}", src.display(), dst.display());
            sync_dir_to(&src, &dst)?;
        }
        Ok(())
    }

    /// Sync workspace/exports → Desktop exports after Claude finishes.
    /// Also syncs output dirs used by vault skills (pretensions/, nda/, contracts/, reports/).
    pub fn sync_exports(&self, cabinet_id: &str) -> Result<()> {
        let sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(session) = sessions.get(cabinet_id) {
            let work_dir = session.work_dir.clone();
            let dst = session.user_workspace.join("exports");
            drop(sessions);

            // Sync from exports/ and all vault-specific output directories
            sync_dir_to(&work_dir.join("exports"), &dst)?;
            for dir_name in &["pretensions", "nda", "contracts", "reports"] {
                let src = work_dir.join(dir_name);
                if src.exists() {
                    sync_dir_to(&src, &dst)?;
                }
            }
        }
        Ok(())
    }

    /// Auto-route exported artifacts to target cabinets' inboxes based on filename patterns.
    /// This enables cross-cabinet file flow outside of pipeline mode.
    pub fn auto_route_artifacts(&self, source_cabinet_id: &str) -> Result<()> {
        let sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());
        let source_ws = match sessions.get(source_cabinet_id) {
            Some(s) => s.user_workspace.clone(),
            None => return Ok(()),
        };
        drop(sessions);

        let exports_dir = source_ws.join("exports");
        if !exports_dir.exists() {
            return Ok(());
        }

        // Routing table: filename pattern → target cabinet IDs
        let routes: &[(&str, &[&str])] = &[
            // Strategy & analysis outputs
            ("media-analysis",       &["communication-analyst", "communication-strategist"]),
            ("communication-audit",  &["communication-strategist", "creative-director"]),
            ("brand-platform",       &["creative-director", "copywriter", "art-director"]),
            ("messaging-framework",  &["copywriter", "art-director", "creative-director"]),
            ("creative-brief",       &["creative-director", "copywriter", "art-director"]),
            // Creative outputs
            ("copy-",               &["focus-groups", "art-director", "lawyer-advertising"]),
            ("text-",               &["focus-groups", "lawyer-advertising"]),
            ("visual-",             &["focus-groups", "lawyer-advertising"]),
            ("ad-variant",          &["focus-groups", "lawyer-advertising"]),
            ("brand-visual",        &["art-director", "creative-director"]),
            // Review outputs
            ("focus-group",         &["copywriter", "creative-director", "art-director"]),
            ("test-result",         &["copywriter", "creative-director"]),
            // Legal outputs
            ("legal-review",        &["copywriter", "creative-director"]),
            ("compliance-check",    &["copywriter", "art-director"]),
            // Documents
            ("contract",            &["lawyer-contracts"]),
            ("nda",                 &["lawyer-claims"]),
            ("media-plan",          &["media-analyst", "econometrist"]),
            ("budget",              &["econometrist"]),
        ];

        let user_profile = std::env::var("USERPROFILE")
            .unwrap_or_else(|_| "C:\\Users\\Default".to_string());
        let base = std::path::PathBuf::from(&user_profile)
            .join("Desktop")
            .join("AIAgency");

        if let Ok(entries) = std::fs::read_dir(&exports_dir) {
            for entry in entries.flatten() {
                if !entry.file_type().is_ok_and(|ft| ft.is_file()) {
                    continue;
                }
                let name = entry.file_name().to_string_lossy().to_lowercase();

                for (pattern, targets) in routes {
                    if name.contains(pattern) {
                        for target_id in *targets {
                            if *target_id == source_cabinet_id {
                                continue;
                            }
                            let target_inbox = base.join(target_id).join("inbox");
                            let _ = std::fs::create_dir_all(&target_inbox);
                            match std::fs::copy(entry.path(), target_inbox.join(entry.file_name())) {
                                Ok(_) => info!("Auto-routed {} → {target_id}", entry.file_name().to_string_lossy()),
                                Err(e) => warn!("Auto-route failed: {} → {target_id}: {e}", entry.file_name().to_string_lossy()),
                            }
                        }
                        break; // first match only
                    }
                }
            }
        }

        Ok(())
    }

    /// Check if this is a continuation (2nd+ message). Marks first_message_sent on first call.
    pub fn should_continue(&self, cabinet_id: &str) -> bool {
        let mut sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(session) = sessions.get_mut(cabinet_id) {
            if session.first_message_sent {
                return true;
            }
            session.first_message_sent = true;
        }
        false
    }

    /// Store Claude CLI session ID for resuming conversations.
    pub fn set_claude_session_id(&self, cabinet_id: &str, session_id: String) {
        let mut sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(session) = sessions.get_mut(cabinet_id) {
            debug!("Storing Claude session_id for {cabinet_id}: {session_id}");
            session.claude_session_id = Some(session_id);
        }
    }

    /// Get stored Claude CLI session ID for --resume.
    pub fn get_claude_session_id(&self, cabinet_id: &str) -> Option<String> {
        let sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());
        sessions.get(cabinet_id).and_then(|s| s.claude_session_id.clone())
    }

    pub fn clear_claude_session_id(&self, cabinet_id: &str) {
        let mut sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(session) = sessions.get_mut(cabinet_id) {
            debug!("Clearing Claude session_id for {cabinet_id}");
            session.claude_session_id = None;
        }
    }

    /// [DEV ONLY] Open a session directly from a source directory (no vault decryption).
    #[cfg(debug_assertions)]
    pub fn open_dev_session(
        &self,
        cabinet_id: &str,
        source_dir: &Path,
        user_workspace: &Path,
    ) -> Result<PathBuf> {
        let mut sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());

        if let Some(existing) = sessions.get(cabinet_id) {
            // Re-sync cabinet files from source on every open (hot-reload friendly)
            let work = &existing.work_dir;
            if let Err(e) = copy_dir_recursive(source_dir, work) {
                warn!("[DEV] Failed to re-sync cabinet files: {e}");
            } else {
                debug!("[DEV] Re-synced prompts from {}", source_dir.display());
            }
            return Ok(work.clone());
        }

        let session_uid = uuid::Uuid::new_v4().to_string();
        let uid = &session_uid[..8];
        let temp_dir = self.sessions_root.join(format!("dev_{}_{}", cabinet_id, uid));
        let work_dir = temp_dir.join("workspace");
        std::fs::create_dir_all(&work_dir)?;

        // Copy cabinet files directly (no decryption)
        copy_dir_recursive(source_dir, &work_dir)
            .with_context(|| format!("Failed to copy dev cabinet from {}", source_dir.display()))?;

        let inbox = user_workspace.join("inbox");
        let exports = user_workspace.join("exports");
        std::fs::create_dir_all(&inbox)?;
        std::fs::create_dir_all(&exports)?;
        std::fs::create_dir_all(work_dir.join("inbox"))?;
        std::fs::create_dir_all(work_dir.join("exports"))?;
        sync_dir_to(&inbox, &work_dir.join("inbox"))?;

        info!("[DEV] Session ready for {cabinet_id}: {}", work_dir.display());

        let session = Session {
            cabinet_id: cabinet_id.to_string(),
            work_dir: work_dir.clone(),
            temp_dir,
            user_workspace: user_workspace.to_path_buf(),
            first_message_sent: false,
            claude_session_id: None,
        };
        sessions.insert(cabinet_id.to_string(), session);

        Ok(work_dir)
    }

    /// Close a session and securely delete decrypted files.
    pub fn close_session(&self, cabinet_id: &str) -> Result<()> {
        let mut sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(session) = sessions.remove(cabinet_id) {
            info!("Closing session for {cabinet_id}, cleaning up: {}", session.temp_dir.display());
            clear_inbox(&session.user_workspace);
            secure_delete_dir(&session.temp_dir).map_err(|e| {
                warn!("Secure delete failed for {}: {e}", session.temp_dir.display());
                e
            })?;
        }
        Ok(())
    }

    /// Close all sessions (on app exit).
    pub fn close_all(&self) -> Result<()> {
        let mut sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());
        let cabinet_ids: Vec<String> = sessions.keys().cloned().collect();
        info!("Closing all sessions ({})", cabinet_ids.len());
        for id in cabinet_ids {
            if let Some(session) = sessions.remove(&id) {
                clear_inbox(&session.user_workspace);
                if let Err(e) = secure_delete_dir(&session.temp_dir) {
                    error!("Secure delete failed for session {id}: {e}");
                }
            }
        }
        Ok(())
    }
}

/// Remove all files from inbox in user workspace.
fn clear_inbox(workspace: &Path) {
    let inbox = workspace.join("inbox");
    if let Ok(entries) = std::fs::read_dir(&inbox) {
        for entry in entries.flatten() {
            if entry.file_type().is_ok_and(|ft| ft.is_file()) {
                let _ = std::fs::remove_file(entry.path());
            }
        }
    }
}

/// Mirror-sync files from src to dst (one level, no recursion).
/// Copies new/updated files AND removes files in dst not present in src.
fn sync_dir_to(src: &Path, dst: &Path) -> Result<()> {
    if !src.exists() {
        return Ok(());
    }
    std::fs::create_dir_all(dst)?;

    // Collect source filenames
    let src_names: std::collections::HashSet<std::ffi::OsString> = std::fs::read_dir(src)?
        .flatten()
        .filter(|e| e.file_type().is_ok_and(|ft| ft.is_file()))
        .map(|e| e.file_name())
        .collect();

    // Remove files in dst that are NOT in src (deleted by user)
    if let Ok(dst_entries) = std::fs::read_dir(dst) {
        for entry in dst_entries.flatten() {
            if entry.file_type().is_ok_and(|ft| ft.is_file()) && !src_names.contains(&entry.file_name()) {
                let _ = std::fs::remove_file(entry.path());
            }
        }
    }

    // Copy src → dst
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        if entry.file_type()?.is_file() {
            let dst_file = dst.join(entry.file_name());
            std::fs::copy(entry.path(), &dst_file)?;
        }
    }
    Ok(())
}

/// Recursively copy a directory.
fn copy_dir_recursive(src: &Path, dst: &Path) -> Result<()> {
    std::fs::create_dir_all(dst)?;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let ty = entry.file_type()?;
        let dst_path = dst.join(entry.file_name());
        if ty.is_dir() {
            copy_dir_recursive(&entry.path(), &dst_path)?;
        } else {
            std::fs::copy(entry.path(), &dst_path)?;
        }
    }
    Ok(())
}

/// Overwrite files with zeros before deleting (basic secure delete).
/// Single-pass zero overwrite is considered sufficient per NIST SP 800-88 Rev. 1
/// for modern drives (including SSDs where multi-pass is ineffective due to wear leveling).
/// For SSD media, ATA Secure Erase via the drive controller is the definitive method,
/// but that requires OS-level privileges beyond a desktop app's scope.
fn secure_delete_dir(dir: &Path) -> Result<()> {
    if !dir.exists() {
        return Ok(());
    }
    for entry in walkdir::WalkDir::new(dir).contents_first(true) {
        let entry = entry?;
        let path = entry.path();
        if path.is_file() {
            // Overwrite with zeros
            if let Ok(metadata) = std::fs::metadata(path) {
                let size = metadata.len() as usize;
                if size > 0 {
                    let zeros = vec![0u8; size.min(1024 * 1024)]; // cap at 1MB chunks
                    if let Ok(mut file) = std::fs::OpenOptions::new().write(true).open(path) {
                        use std::io::Write;
                        let mut remaining = size;
                        while remaining > 0 {
                            let chunk = remaining.min(zeros.len());
                            let _ = file.write_all(&zeros[..chunk]);
                            remaining -= chunk;
                        }
                        let _ = file.flush();
                    }
                }
            }
            std::fs::remove_file(path)?;
        } else if path.is_dir() {
            std::fs::remove_dir(path)?;
        }
    }
    Ok(())
}
