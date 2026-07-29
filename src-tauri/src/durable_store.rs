//! Durable-состояние приложения: per-app каталог + one-shot миграция из общего legacy-каталога.
//!
//! CPD-30 (2026-07-29): все Aurora-продукты машины писали историю/метрики/сессии в ОБЩИЙ
//! `%LOCALAPPDATA%\AIAgency\<sub>` без идентификатора продукта. Имя файла истории — идентификатор
//! кабинета, поэтому продукты с одноимённым кабинетом читали и перезаписывали чужую историю
//! (доказано вживую на этой машине: `econometrist.json` в общем `AIAgency\history\` — тот же файл,
//! что читал бы кабинет econometrist в любом другом Aurora-продукте с этим кабинетом). Решение —
//! per-app каталог (`app_local_data_dir()`, чистится деинсталлятором) с одноразовым переносом
//! legacy-файлов при первом запуске.
//!
//! Эталон-донор этого файла — `ROSST_AI_DocMaster/src-tauri/src/durable_store.rs` (сам он —
//! усиленная версия первопроходца `ROSST_AI_Media`, см. докстринг там же про `fresh = !dir.exists()`
//! до `create_dir_all` и глотание ошибок `fs::copy(...).is_ok()` — в Econometrica этих слабостей
//! не было НИКОГДА, копируем сразу усиленный контракт).
//!
//! Признак завершённого переноса — ОТДЕЛЬНЫЙ файл-маркер (`.legacy-migrated`) ВНУТРИ нового
//! каталога, записывается ТОЛЬКО когда ВСЕ файлы перенесены без единой ошибки:
//! - маркера нет → перенос выполняется (в т.ч. повторно после оборванного);
//! - файл уже существует в новом каталоге → НЕ перезаписывается (свежая история продукта
//!   важнее legacy-копии);
//! - хотя бы один файл не скопировался → маркер НЕ пишется, `warn!` с именем файла и причиной,
//!   следующий запуск пробует снова;
//! - legacy-каталог не удаляется никогда — им пользуются другие установленные Aurora-продукты,
//!   а при откате версии история должна остаться на месте.

use anyhow::{Context, Result};
use log::{info, warn};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

/// Имя файла-маркера завершённого переноса (внутри НОВОГО каталога, не трогает legacy).
const MIGRATION_MARKER: &str = ".legacy-migrated";

fn local_app_data() -> PathBuf {
    PathBuf::from(
        std::env::var("LOCALAPPDATA").unwrap_or_else(|_| "C:\\Users\\Default\\AppData\\Local".to_string()),
    )
}

/// База durable-состояния = папка приложения (`app_local_data_dir()` = `%LOCALAPPDATA%\<identifier>`).
/// Инициализируется один раз при старте (см. `lib.rs::run()` и `.setup()`) — чтобы состояние
/// лежало там же, где остальные данные приложения, и чистилось деинсталлятором.
static BASE_DIR: OnceLock<PathBuf> = OnceLock::new();

/// Вызывается один раз в `run()`/`.setup()`: base = per-app каталог (`%LOCALAPPDATA%\<identifier>`).
pub fn init(base: PathBuf) {
    let _ = BASE_DIR.set(base);
}

fn base_dir() -> PathBuf {
    // Фолбэк (тесты/вызов до init): per-app по имени пакета — тоже уникально на вариант сборки
    // (Cargo.toml::name отличается у каждого Aurora-продукта форка).
    BASE_DIR
        .get()
        .cloned()
        .unwrap_or_else(|| local_app_data().join(env!("CARGO_PKG_NAME")))
}

/// Имя подкаталога сессий — единственный источник правды для `session/manager.rs` и
/// `session/cleanup.rs` (testleak-фикс, 2026-07-29): раньше оба места писали независимый
/// строковый литерал `"sessions"`, которые могли незаметно разойтись; теперь оба ссылаются на
/// эту константу — расхождение стало ошибкой компиляции, а не тихим дефектом. Гейт
/// `session::tests::manager_and_cleanup_reference_the_same_sessions_constant`
/// (`session/mod.rs`) сканирует исходники и красит, если кто-то вернётся к литералу.
pub const SESSIONS_SUB: &str = "sessions";

/// Путь, который вернёт `app_state_dir(sub)`, — БЕЗ создания каталогов и БЕЗ миграции. Чистая
/// функция (никакого I/O): читает `BASE_DIR`, если он уже инициализирован, иначе считает тот
/// же фолбэк, что и `base_dir()`. Существует, чтобы тесты могли резолвить путь, не трогая
/// диск и не завися от того, вызывал ли кто-то `init()` в этом процессе.
pub fn resolve_path(sub: &str) -> PathBuf {
    if sub.is_empty() { base_dir() } else { base_dir().join(sub) }
}

/// Per-app каталог durable-состояния с one-shot миграцией из общего legacy `AIAgency\<sub>`.
/// `sub` — подкаталог (`"history"`, `"metrics"`, `"sessions"`); пустая строка — сам каталог
/// приложения (для файлов, лежавших прямо в legacy-корне `AIAgency\`, например `audit.log`).
pub fn app_state_dir(sub: &str) -> Result<PathBuf> {
    let dir = resolve_path(sub);
    let legacy = if sub.is_empty() {
        local_app_data().join("AIAgency")
    } else {
        local_app_data().join("AIAgency").join(sub)
    };
    migrate_into(&dir, &legacy, sub, |s: &Path, d: &Path| std::fs::copy(s, d))?;
    Ok(dir)
}

/// Ядро переноса — тестируемое, без глобальных LOCALAPPDATA/BASE_DIR (пути передаются явно,
/// `copier` инъецируется, чтобы тест мог детерминированно смоделировать отказ копирования
/// одного файла без порчи файловой системы).
fn migrate_into(
    dir: &Path,
    legacy: &Path,
    label: &str,
    copier: impl Fn(&Path, &Path) -> std::io::Result<u64>,
) -> Result<()> {
    std::fs::create_dir_all(dir).with_context(|| format!("не создать каталог состояния '{label}'"))?;

    let marker = dir.join(MIGRATION_MARKER);
    if marker.exists() {
        return Ok(()); // перенос уже завершён без ошибок — не пересканируем legacy впустую
    }

    if !legacy.is_dir() {
        // Legacy-каталога нет вовсе (чистая установка либо продукт никогда не писал сюда) —
        // переносить нечего; маркер всё равно пишем, чтобы не читать read_dir на каждый вызов.
        std::fs::write(&marker, migration_stamp())
            .with_context(|| format!("не записать маркер переноса {}", marker.display()))?;
        return Ok(());
    }

    let mut copied = 0usize;
    let mut failed: Vec<String> = vec![];

    match std::fs::read_dir(legacy) {
        Ok(read_dir) => {
            for entry in read_dir {
                let entry = match entry {
                    Ok(e) => e,
                    Err(err) => {
                        failed.push(format!("<запись каталога>: {err}"));
                        continue;
                    }
                };
                let src = entry.path();
                if !src.is_file() {
                    continue; // поддиректории (напр. чужие подпродукты) переносом не затрагиваются
                }
                let name = entry.file_name();
                let dst = dir.join(&name);
                if dst.exists() {
                    // Свежая история продукта важнее legacy-копии — не перезаписываем.
                    continue;
                }
                // 🔴 Внешний аудит 2026-07-29 (High): копируем во ВРЕМЕННЫЙ файл рядом и
                // переименовываем. Прямая запись в `dst` при обрыве (питание, полный диск)
                // оставляла усечённый файл, а проверка `dst.exists()` выше пропускала его
                // НАВСЕГДА — маркер записывался, legacy-оригинал больше не читался, и клиент
                // получал обрезанную историю без единого признака сбоя. Переименование в
                // пределах одного каталога атомарно, поэтому промежуточного состояния нет.
                let staging = dir.join(format!(
                    "{}.legacy-migrating",
                    name.to_string_lossy()
                ));
                let _ = std::fs::remove_file(&staging); // хвост прошлого оборванного захода
                match copier(&src, &staging).and_then(|written| {
                    std::fs::rename(&staging, &dst).map(|_| written)
                }) {
                    Ok(_) => copied += 1,
                    Err(err) => {
                        let _ = std::fs::remove_file(&staging);
                        failed.push(format!("{}: {err}", name.to_string_lossy()));
                    }
                }
            }
        }
        Err(err) => failed.push(format!("<не открыт legacy-каталог {}>: {err}", legacy.display())),
    }

    if failed.is_empty() {
        if copied > 0 {
            info!("durable_store: перенесено {copied} файлов из legacy AIAgency/{label}");
        }
        std::fs::write(&marker, migration_stamp())
            .with_context(|| format!("не записать маркер переноса {}", marker.display()))?;
    } else {
        warn!(
            "durable_store: перенос '{label}' не завершён — {} из {} файлов не скопировано ({}); \
             маркер не записан, следующий запуск попробует снова",
            failed.len(),
            copied + failed.len(),
            failed.join("; ")
        );
    }

    Ok(())
}

fn migration_stamp() -> String {
    format!(
        "перенесено {}\n",
        chrono::Local::now().format("%Y-%m-%dT%H:%M:%S")
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_file(dir: &Path, name: &str, content: &str) {
        std::fs::create_dir_all(dir).unwrap();
        std::fs::write(dir.join(name), content).unwrap();
    }

    /// Конкретно-типизированная обёртка над `std::fs::copy` — generic fn-item напрямую как
    /// `impl Fn(&Path, &Path) -> ...` не проходит из-за HRTB-инференции лайфтаймов.
    fn real_copy(s: &Path, d: &Path) -> std::io::Result<u64> {
        std::fs::copy(s, d)
    }

    /// 🔴 Регресс внешнего аудита 2026-07-29 (High): обрыв ВНУТРИ копирования не должен
    /// оставлять усечённый файл в целевом каталоге. Прежде копирование шло прямо в цель, и
    /// оборванный файл на следующем запуске выглядел как уже перенесённый (`dst.exists()` →
    /// пропуск НАВСЕГДА), маркер записывался, legacy-оригинал больше не читался — клиент
    /// получал обрезанную историю без единого признака сбоя.
    #[test]
    fn interrupted_copy_leaves_no_truncated_file_and_resumes_next_run() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let new_dir = tmp.path().join("new");
        write_file(&legacy, "history.json", "полное содержимое истории клиента");

        // Первый заход: копирование записывает ЧАСТЬ и падает — ровно как обрыв питания.
        fn truncating_copy(s: &Path, d: &Path) -> std::io::Result<u64> {
            let content = std::fs::read(s)?;
            std::fs::write(d, &content[..content.len() / 2])?;
            Err(std::io::Error::new(
                std::io::ErrorKind::WriteZero,
                "обрыв на середине копирования",
            ))
        }
        migrate_into(&new_dir, &legacy, "history", truncating_copy).unwrap();
        assert!(
            !new_dir.join("history.json").exists(),
            "усечённого файла в целевом каталоге быть не должно — иначе следующий запуск примет \
             его за перенесённый и пропустит навсегда"
        );
        assert!(
            !new_dir.join(MIGRATION_MARKER).exists(),
            "маркера после отказа копирования быть не должно"
        );

        // Второй заход: копирование исправно — файл обязан доехать ЦЕЛИКОМ.
        migrate_into(&new_dir, &legacy, "history", real_copy).unwrap();
        assert_eq!(
            std::fs::read_to_string(new_dir.join("history.json")).unwrap(),
            "полное содержимое истории клиента",
            "после дозавершения в целевом каталоге обязан лежать ПОЛНЫЙ файл"
        );
        assert!(new_dir.join(MIGRATION_MARKER).exists());
    }

    /// (а) Перенос при пустом новом каталоге переносит файлы.
    #[test]
    fn migration_copies_files_into_empty_new_dir() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let new_dir = tmp.path().join("new");
        write_file(&legacy, "a.json", "A");
        write_file(&legacy, "b.json", "B");

        migrate_into(&new_dir, &legacy, "test", real_copy).unwrap();

        assert_eq!(std::fs::read_to_string(new_dir.join("a.json")).unwrap(), "A");
        assert_eq!(std::fs::read_to_string(new_dir.join("b.json")).unwrap(), "B");
        assert!(new_dir.join(MIGRATION_MARKER).exists(), "маркер обязан быть записан после успешного переноса");
    }

    /// (б) Повторный запуск ничего не дублирует и не перезаписывает.
    #[test]
    fn second_run_does_not_duplicate_or_overwrite() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let new_dir = tmp.path().join("new");
        write_file(&legacy, "a.json", "legacy-A");

        migrate_into(&new_dir, &legacy, "test", real_copy).unwrap();
        // Продукт поработал — файл в новом каталоге изменился своей жизнью.
        std::fs::write(new_dir.join("a.json"), "fresh-A-after-first-run").unwrap();
        std::fs::write(legacy.join("a.json"), "legacy-A-changed-later").unwrap();

        migrate_into(&new_dir, &legacy, "test", real_copy).unwrap();

        assert_eq!(
            std::fs::read_to_string(new_dir.join("a.json")).unwrap(),
            "fresh-A-after-first-run",
            "повторный вызов после маркера не имеет права трогать файлы"
        );
    }

    /// (в) ГЛАВНЫЙ тест: оборванный перенос (маркера нет, часть файлов уже на месте)
    /// дозавершается при следующем запуске — ради этого весь контракт.
    #[test]
    fn interrupted_migration_resumes_on_next_run() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let new_dir = tmp.path().join("new");
        write_file(&legacy, "a.json", "A");
        write_file(&legacy, "b.json", "B");
        write_file(&new_dir, "a.json", "A"); // уже скопирован до "обрыва питания"
        assert!(!new_dir.join(MIGRATION_MARKER).exists(), "маркера после обрыва быть не должно");

        migrate_into(&new_dir, &legacy, "test", real_copy).unwrap();

        assert_eq!(
            std::fs::read_to_string(new_dir.join("b.json")).unwrap(), "B",
            "недостающий файл обязан докопироваться при следующем запуске"
        );
        assert!(new_dir.join(MIGRATION_MARKER).exists(), "после дозавершения маркер обязан появиться");
    }

    /// (г) Существующий в новом каталоге файл не затирается legacy-версией.
    #[test]
    fn existing_file_in_new_dir_is_not_overwritten_by_legacy() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let new_dir = tmp.path().join("new");
        write_file(&legacy, "a.json", "legacy-version");
        write_file(&new_dir, "a.json", "fresh-product-version");

        migrate_into(&new_dir, &legacy, "test", real_copy).unwrap();

        assert_eq!(
            std::fs::read_to_string(new_dir.join("a.json")).unwrap(),
            "fresh-product-version",
            "свежая история продукта важнее legacy-копии"
        );
    }

    #[test]
    fn no_legacy_dir_still_marks_migration_done() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("does-not-exist");
        let new_dir = tmp.path().join("new");

        migrate_into(&new_dir, &legacy, "test", real_copy).unwrap();
        assert!(new_dir.join(MIGRATION_MARKER).exists());
    }

    /// Отказ копирования ОДНОГО файла — маркер не пишется, следующий вызов (уже без отказа)
    /// докапирует недостающее. Отказ смоделирован инъецированным `copier`, а не порчей ФС —
    /// детерминированно и кроссплатформенно.
    #[test]
    fn one_failed_file_blocks_marker_and_retries_next_run() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let new_dir = tmp.path().join("new");
        write_file(&legacy, "a.json", "A");
        write_file(&legacy, "b.json", "B"); // этот "не скопируется"

        let failing_copier = |src: &Path, dst: &Path| -> std::io::Result<u64> {
            if src.file_name().and_then(|n| n.to_str()) == Some("b.json") {
                return Err(std::io::Error::new(std::io::ErrorKind::PermissionDenied, "смоделированный отказ"));
            }
            std::fs::copy(src, dst)
        };

        migrate_into(&new_dir, &legacy, "test", failing_copier).unwrap();

        assert_eq!(std::fs::read_to_string(new_dir.join("a.json")).unwrap(), "A", "успешный файл обязан скопироваться");
        assert!(!new_dir.join("b.json").exists(), "провалившийся файл не должен появиться");
        assert!(!new_dir.join(MIGRATION_MARKER).exists(), "хотя бы один отказ — маркер не пишется");

        // Следующий запуск — уже без отказа — обязан докопировать недостающее.
        migrate_into(&new_dir, &legacy, "test", real_copy).unwrap();
        assert_eq!(std::fs::read_to_string(new_dir.join("b.json")).unwrap(), "B", "повтор обязан докопировать после отказа");
        assert!(new_dir.join(MIGRATION_MARKER).exists());
    }

    /// Файлы прямо в legacy-корне (`sub=""`, случай audit.log) — join("") не должен ломать путь.
    #[test]
    fn empty_sub_targets_base_dir_itself() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy-root");
        let new_dir = tmp.path().join("new-root");
        write_file(&legacy, "audit.log", "log-line-1\n");

        migrate_into(&new_dir, &legacy, "", real_copy).unwrap();

        assert_eq!(std::fs::read_to_string(new_dir.join("audit.log")).unwrap(), "log-line-1\n");
        assert!(new_dir.join(MIGRATION_MARKER).exists());
    }
}
