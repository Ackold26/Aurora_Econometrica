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
    /// 🔴 Батч C (C2): открытый хендл файла-замка `.session-lock` внутри `temp_dir` — признак
    /// ЖИВОЙ сессии для очистки чужого процесса (см. `session/cleanup.rs`). Держится открытым
    /// монопольно всё время жизни сессии и закрывается вместе с ней (Drop хендла при
    /// `close_session`/`close_all` — ЯВНО перед удалением каталога, иначе своё же монопольное
    /// открытие не даст затереть файл). `None` — замок взять не удалось: сессия работает как
    /// раньше, но от чужой очистки не защищена (в журнале — warn).
    lock: Option<std::fs::File>,
}

/// Имя файла-замка живой сессии внутри каталога сессии. Единственный источник правды для
/// `manager.rs` (владелец держит открытым) и `cleanup.rs` (проверяет занятость).
pub(crate) const SESSION_LOCK_FILE: &str = ".session-lock";

/// Открыть файл-замок МОНОПОЛЬНО (Windows: `share_mode(0)` — никто другой не откроет файл, пока
/// хендл жив; внешних зависимостей не требует). Пока владелец держит хендл, тот же вызов из
/// другого процесса вернёт ошибку — это и есть признак «сессия живая».
///
/// 🔴 Режим открытия задан дословно и НЕ подлежит «естественному прочтению»: `create(true)` +
/// `write(true)`, и НИКОГДА `create_new(true)`. Операционная система освобождает при падении
/// процесса ДЕСКРИПТОР, а сам файл замка остаётся на диске — с `create_new` первое же аварийное
/// завершение продукта заставило бы создание вечно падать с `AlreadyExists`. По той же причине
/// файл замка при освобождении не удаляется.
///
/// Не-Windows: монопольного режима у `OpenOptions` нет, а POSIX-блокировки рекомендательные и
/// требуют внешнего крейта. Здесь открытие просто удаётся всегда, поэтому очистка на не-Windows
/// цели ведёт себя как до этой правки (каталог считается осиротевшим). Продукт собирается и
/// поставляется только под Windows — ветка нужна лишь чтобы крейт компилировался на других целях.
pub(crate) fn open_session_lock(lock_path: &Path) -> std::io::Result<std::fs::File> {
    let mut options = std::fs::OpenOptions::new();
    options.create(true).read(true).write(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.share_mode(0); // 0 = никакого совместного доступа: ни чтения, ни записи, ни удаления
    }
    options.open(lock_path)
}

/// Создать каталог сессии и СРАЗУ взять его замок — одним вызовом, без промежутка.
///
/// 🔴 Поправка внешнего аудита к контракту (M21): между `create_dir_all(temp_dir)` и появлением
/// `.session-lock` каталог выглядит осиротевшим, и очистка чужого экземпляра успевает снести его
/// вместе с уже распакованными расшифрованными файлами. Два шага сведены в один, чтобы у
/// вызывающего физически не было возможности вставить между ними работу. Отказ взять замок не
/// фатален для открытия кабинета (каталог уже создан, отказ здесь означает сломанную ФС) — пишем
/// warn и работаем без защиты, как до правки. Сторож —
/// `cleanup::tests::session_dir_is_protected_from_the_moment_it_is_created`.
pub(crate) fn create_locked_session_dir(temp_dir: &Path) -> std::io::Result<Option<std::fs::File>> {
    std::fs::create_dir_all(temp_dir)?;
    match open_session_lock(&temp_dir.join(SESSION_LOCK_FILE)) {
        Ok(file) => Ok(Some(file)),
        Err(e) => {
            warn!(
                "Не взят замок живой сессии {}: {e} — очистка другого экземпляра может снести этот каталог",
                temp_dir.display()
            );
            Ok(None)
        }
    }
}

/// Manages active sessions per cabinet.
pub struct SessionManager {
    sessions: Mutex<HashMap<String, Session>>,
    sessions_root: PathBuf,
}

impl SessionManager {
    pub fn new() -> Result<Self> {
        // CPD-30 (2026-07-29): per-app каталог — до этого все Aurora-продукты машины
        // расшифровывали vault'ы во ОБЩИЙ AIAgency\sessions, и cleanup_stale_sessions()
        // (см. session/cleanup.rs) при старте одного продукта могла снести ЖИВУЮ, ещё
        // открытую сессию другого продукта. Каталог с расшифрованными vault'ами — эфемерный
        // рабочий кэш (пересоздаётся на каждое открытие кабинета), переносить содержимое не
        // нужно; durable_store::app_state_dir сюда всё равно уместен — поддиректории (сами
        // сессии) он не трогает (копирует только файлы верхнего уровня legacy-каталога,
        // которых в sessions\ никогда не было), так что вызов — просто per-app путь с
        // бесплатным маркером «сканировать больше не надо».
        let sessions_root = crate::durable_store::app_state_dir(crate::durable_store::SESSIONS_SUB)?;

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
        // 🔴 Батч C (C2 + поправка M21): каталог создаётся УЖЕ с замком внутри — одним вызовом,
        // до распаковки расшифрованного vault'а. Двумя шагами («создали → потом взяли замок»)
        // между ними оставалось окно, в котором каталог выглядит осиротевшим и очистка второго
        // экземпляра приложения успевает его снести.
        let lock = create_locked_session_dir(&temp_dir)?;

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
            // 🔴 Батч C (C2): файл-замок — служебный маркер каталога сессии, в рабочую папку
            // кабинета он не копируется. Плюс копирование его же и не удалось бы: хендл открыт
            // монопольно, чтение из другого дескриптора Windows не даст.
            if name_str == SESSION_LOCK_FILE {
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
            lock,
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
        // 🔴 Батч C (C2 + M21): dev-сессия помечается замком так же, как боевая — иначе очистка
        // второго экземпляра снесла бы каталог работающей dev-сессии.
        let lock = create_locked_session_dir(&temp_dir)?;
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
            lock,
        };
        sessions.insert(cabinet_id.to_string(), session);

        Ok(work_dir)
    }

    /// Close a session and securely delete decrypted files.
    pub fn close_session(&self, cabinet_id: &str) -> Result<()> {
        let mut sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(mut session) = sessions.remove(cabinet_id) {
            info!("Closing session for {cabinet_id}, cleaning up: {}", session.temp_dir.display());
            // 🔴 Батч C (C2): замок отпускаем ДО удаления каталога — файл открыт монопольно, и
            // затирающее удаление не смогло бы его ни перезаписать, ни снести.
            drop(session.lock.take());
            clear_inbox(&session.user_workspace);
            let wipe = secure_delete_dir(&session.temp_dir).map_err(|e| {
                warn!("Secure delete failed for {}: {e}", session.temp_dir.display());
                e
            })?;
            if wipe == WipeOutcome::Incomplete {
                warn!(
                    "Каталог сессии {} удалён, но затёрт НЕ полностью — часть расшифрованных \
                     файлов кабинета восстановима с диска (см. warn выше с именами файлов)",
                    session.temp_dir.display()
                );
            }
        }
        Ok(())
    }

    /// Close all sessions (on app exit).
    pub fn close_all(&self) -> Result<()> {
        let mut sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());
        let cabinet_ids: Vec<String> = sessions.keys().cloned().collect();
        info!("Closing all sessions ({})", cabinet_ids.len());
        for id in cabinet_ids {
            if let Some(mut session) = sessions.remove(&id) {
                // 🔴 Батч C (C2): см. close_session — замок отпускаем ДО затирающего удаления.
                drop(session.lock.take());
                clear_inbox(&session.user_workspace);
                match secure_delete_dir(&session.temp_dir) {
                    Ok(WipeOutcome::Complete) => {}
                    Ok(WipeOutcome::Incomplete) => warn!(
                        "Сессия {id} закрыта, но затирание неполное — часть расшифрованных файлов \
                         восстановима с диска"
                    ),
                    Err(e) => error!("Secure delete failed for session {id}: {e}"),
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

/// Итог затирания: удаление либо прошло с полным затиранием, либо файл(ы) удалены БЕЗ него.
///
/// 🔴 Поправка внешнего аудита к контракту (M20): затирание было «по возможности» — не удалось
/// открыть файл на запись, и оно молча пропускалось, а проход считался успешным. Расшифрованные
/// файлы кабинета, удалённые без затирания, восстанавливаются с диска, то есть обещание «данные
/// клиента стёрты» оставалось необеспеченным и при этом невидимым. Теперь неполное затирание —
/// отдельный ИСХОД, а не тишина.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum WipeOutcome {
    /// Всё содержимое затёрто нулями и удалено.
    Complete,
    /// Файл(ы) удалены, но затереть их не удалось — восстановимы с диска, в журнале есть имена.
    Incomplete,
}

/// Overwrite files with zeros before deleting (basic secure delete).
/// Single-pass zero overwrite is considered sufficient per NIST SP 800-88 Rev. 1
/// for modern drives (including SSDs where multi-pass is ineffective due to wear leveling).
/// For SSD media, ATA Secure Erase via the drive controller is the definitive method,
/// but that requires OS-level privileges beyond a desktop app's scope.
///
/// 🔴 Батч C (C2 п.3): видимость расширена до `pub(crate)` — очистка старта
/// (`session/cleanup.rs`) сносила осиротевшие каталоги обычным `remove_dir_all`, то есть ровно в
/// том единственном случае, когда на диске остались расшифрованные файлы клиента (аварийное
/// завершение), они стирались БЕЗ затирания.
/// 🔴 Внешний аудит 2026-07-30 (High, M20 доехала не полностью): проход БОЛЬШЕ НЕ прерывается
/// первой ошибкой. Прежние `entry?` / `secure_delete_file(path)?` / `remove_dir(path)?` означали,
/// что один занятый файл (индексатор, антивирус, второе окно) оставлял ВЕСЬ остаток каталога с
/// расшифрованными файлами клиента нетронутым, а вызывающий получал ошибку без указания, сколько
/// успело удалиться. Теперь отказ по одной записи считается и не мешает остальным.
///
/// 🔴 Два РАЗНЫХ факта разведены намеренно: «файл удалён, но НЕ затёрт» (`WipeOutcome::Incomplete`
/// — каталог всё же снесён, данные восстановимы) и «запись не удалена вовсе» (каталог остался на
/// диске, проход обязан признать отказ — `Err`). Свести их в один счётчик нельзя: тогда каталог с
/// неудалимым файлом числился бы снесённым, и правка против ложного успеха сама создала бы ложный
/// успех. Вызывающий (`session/cleanup.rs::sweep_dir`) на этом различии и построен: `Ok` —
/// `removed`, `Err` — `failed`.
pub(crate) fn secure_delete_dir(dir: &Path) -> Result<WipeOutcome> {
    if !dir.exists() {
        return Ok(WipeOutcome::Complete);
    }
    let mut outcome = WipeOutcome::Complete;
    let mut not_removed = 0usize;
    for entry in walkdir::WalkDir::new(dir).contents_first(true) {
        let entry = match entry {
            Ok(e) => e,
            Err(e) => {
                warn!("Очистка {}: запись обхода пропущена — {e}", dir.display());
                not_removed += 1;
                continue;
            }
        };
        let path = entry.path();
        if path.is_file() {
            match secure_delete_file(path) {
                Ok(WipeOutcome::Complete) => {}
                Ok(WipeOutcome::Incomplete) => outcome = WipeOutcome::Incomplete,
                Err(e) => {
                    warn!("Очистка: файл не удалён {} — {e}", path.display());
                    not_removed += 1;
                }
            }
        } else if path.is_dir() {
            if let Err(e) = std::fs::remove_dir(path) {
                warn!("Очистка: каталог не удалён {} — {e}", path.display());
                not_removed += 1;
            }
        }
    }
    if not_removed > 0 {
        anyhow::bail!(
            "очистка {} неполная: {} запис(ей) остались на диске, затирание остального {}",
            dir.display(),
            not_removed,
            match outcome {
                WipeOutcome::Complete => "выполнено",
                WipeOutcome::Incomplete => "ТОЖЕ неполное",
            }
        );
    }
    Ok(outcome)
}

/// Затирание ОДНОГО файла нулями перед удалением — прежнее тело цикла `secure_delete_dir`,
/// вынесенное отдельно.
///
/// 🔴 Батч C (C8): «очистить историю» обязана уносить и карантинные копии переписки
/// (`session/history.rs`), а там данные клиента ровно того же рода, что в каталоге сессии.
/// Отдельная функция, а не вторая копия той же логики затирания: расхождение копий — главный
/// класс дефектов этого аудита.
///
/// 🔴 Поправка M20: отказ затирания больше не глотается. Одна повторная попытка (обычная причина
/// — файл на миг держит индексатор или антивирус, это проходит за миллисекунды), затем `warn` с
/// именем файла и исход `Incomplete`. Само удаление при этом выполняется: оставить нетронутый
/// расшифрованный файл лежать на диске хуже, чем удалить его без затирания, — но «хуже/лучше»
/// обязано быть видно, а не решаться молча.
pub(crate) fn secure_delete_file(path: &Path) -> Result<WipeOutcome> {
    let mut outcome = WipeOutcome::Complete;
    if let Err(first) = overwrite_with_zeros(path) {
        std::thread::sleep(crate::durable_store::STATE_RETRY_PAUSE);
        if let Err(second) = overwrite_with_zeros(path) {
            warn!(
                "Затирание {} не выполнено ({first}; повтор: {second}) — файл будет удалён БЕЗ \
                 затирания и восстановим с диска",
                path.display()
            );
            outcome = WipeOutcome::Incomplete;
        }
    }
    std::fs::remove_file(path)?;
    Ok(outcome)
}

/// Собственно перезапись нулями. Ошибки НЕ глотаются (в этом вся суть поправки M20): пустой файл
/// и отсутствующий считаются затёртыми — затирать в них нечего.
fn overwrite_with_zeros(path: &Path) -> std::io::Result<()> {
    let size = match std::fs::metadata(path) {
        Ok(md) => md.len() as usize,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(e),
    };
    if size == 0 {
        return Ok(());
    }
    let zeros = vec![0u8; size.min(1024 * 1024)]; // cap at 1MB chunks
    let mut file = std::fs::OpenOptions::new().write(true).open(path)?;
    use std::io::Write;
    let mut remaining = size;
    while remaining > 0 {
        let chunk = remaining.min(zeros.len());
        file.write_all(&zeros[..chunk])?;
        remaining -= chunk;
    }
    file.flush()?;
    Ok(())
}

// testleak-фикс (2026-07-29): тест-инвариант "manager и cleanup резолвят один каталог" раньше
// жил здесь и вызывал настоящий SessionManager::new() — тот резолвит durable_store::app_state_dir,
// который в тестовом окружении (durable_store::init() тестами не вызывается) уходит в фолбэк
// по CARGO_PKG_NAME — РЕАЛЬНЫЙ каталог профиля разработчика, не временный; create_dir_all внутри
// app_state_dir создавал там настоящие директории (найдено при приёмке CPD-30). Инвариант
// перенесён в `session/mod.rs` — сканирование исходников на использование общей константы
// `durable_store::SESSIONS_SUB`, без единого обращения к диску.

#[cfg(test)]
mod wipe_tests {
    use super::*;

    /// 🔴 Сторож находки внешнего аудита 2026-07-30 (High): один неудалимый файл НЕ имеет права
    /// прерывать проход. Прежний `let entry = entry?` / `secure_delete_file(path)?` бросал остаток
    /// каталога — а там лежат РАСШИФРОВАННЫЕ файлы кабинета, и остаются они лежать после того, как
    /// продукт уже посчитал сессию закрытой.
    ///
    /// Проверяются оба следствия сразу: остальные файлы всё-таки удалены (обход продолжился) И
    /// проход признан НЕПОЛНЫМ с называнием причины (иначе очистка рапортовала бы успех поверх
    /// оставшихся данных клиента).
    ///
    /// 🔴 Имя занятого файла начинается с цифры намеренно: NTFS отдаёт записи каталога в порядке
    /// имён, значит он встретится ПЕРВЫМ. Иначе прежний код успел бы снести остальные до отказа, и
    /// сторож был бы зелёным по случайности расположения, а не по существу.
    #[cfg(windows)]
    #[test]
    fn one_undeletable_file_does_not_abort_the_rest_of_the_sweep() {
        use std::os::windows::fs::OpenOptionsExt;

        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path().join("econometrist_session");
        let nested = dir.join("z-sub");
        std::fs::create_dir_all(&nested).unwrap();

        let stuck = dir.join("0-stuck.json");
        std::fs::write(&stuck, "расшифрованные данные кабинета").unwrap();
        let siblings = [dir.join("a.json"), dir.join("b.json"), nested.join("inner.json")];
        for f in &siblings {
            std::fs::write(f, "расшифрованные данные кабинета").unwrap();
        }

        // Монопольное открытие: ни перезаписать, ни удалить — так файл держит чужой процесс.
        let held = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .share_mode(0)
            .open(&stuck)
            .unwrap();

        let outcome = secure_delete_dir(&dir);

        for f in &siblings {
            assert!(
                !f.exists(),
                "обход обязан продолжиться после неудалимого файла: {} остался на диске, а это \
                 расшифрованные данные клиента",
                f.display()
            );
        }
        assert!(!nested.exists(), "пустой подкаталог обязан быть снесён после своих файлов");

        let err = outcome.expect_err(
            "каталог с неудалимым файлом обязан давать НЕПОЛНЫЙ проход: иначе очистка рапортует \
             успех, а расшифрованные файлы кабинета остаются на диске",
        );
        let text = format!("{err:#}");
        assert!(
            text.contains("неполная"),
            "отказ обязан называть причину — неполноту прохода: {text}"
        );

        drop(held);
        assert!(stuck.exists(), "занятый файл действительно остался — сценарий воспроизведён");
    }

    /// Негативный контроль к сторожу выше: без помех проход сносит каталог целиком и сообщает о
    /// ПОЛНОМ затирании. Без этого случая «неполный проход» удовлетворялся бы отказом всегда.
    #[test]
    fn clean_sweep_removes_everything_and_reports_complete_wipe() {
        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path().join("econometrist_session");
        let nested = dir.join("sub");
        std::fs::create_dir_all(&nested).unwrap();
        std::fs::write(dir.join("a.json"), "данные").unwrap();
        std::fs::write(nested.join("inner.json"), "данные").unwrap();

        let outcome = secure_delete_dir(&dir).expect("без помех проход обязан пройти");

        assert_eq!(outcome, WipeOutcome::Complete);
        assert!(!dir.exists(), "каталог сессии обязан быть снесён целиком");
    }
}
