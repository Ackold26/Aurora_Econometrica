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
        Ok(())
    } else {
        warn!(
            "durable_store: перенос '{label}' не завершён — {} из {} файлов не скопировано ({}); \
             маркер не записан, следующий запуск попробует снова",
            failed.len(),
            copied + failed.len(),
            failed.join("; ")
        );
        // 🔴 Внешний аудит 2026-07-29 (Critical): раньше здесь возвращался Ok, и потребитель
        // немедленно работал с ПУСТЫМ местом непереехавшего файла — показывал пустую историю и
        // создавал новый файл поверх. На следующем запуске правило «свежее важнее legacy»
        // навсегда закрывало дорогу оригиналу, маркер писался, переписка клиента исчезала без
        // единого признака отказа. Честный отказ лучше молчаливой потери: пусть вызывающий
        // решает, показать ошибку или отступить, но не пишет на место непереехавшего.
        anyhow::bail!(
            "перенос состояния '{label}' не завершён: {} из {} файлов не скопировано ({}). \
             Данные остались в прежнем каталоге; повторите запуск после устранения причины",
            failed.len(),
            copied + failed.len(),
            failed.join("; ")
        );
    }
}

fn migration_stamp() -> String {
    format!(
        "перенесено {}\n",
        chrono::Local::now().format("%Y-%m-%dT%H:%M:%S")
    )
}

// 🔴 Внешний аудит 2026-07-29 (High): три функции ниже возвращены из донора-эталона
// (`ROSST_AI_Media/src-tauri/src/durable_store.rs`, продукт Smart Analytica) — при переносе
// состояния в per-app каталог сюда перенесли только миграционную логику (`migrate_into` выше), а
// эти защитные примитивы забыли. Без них: `save_message`/`save_to_disk`/`save_ratings` писали
// напрямую в целевой файл — обрыв процесса на середине записи оставлял усечённый JSON; чтение
// битого JSON падало на `unwrap_or_else`/`unwrap_or_default()` без следа — файл истории/метрик
// молча превращался в пустой список, и следующее же сохранение стирало оригинал НАВСЕГДА (тот же
// класс отказа, что и у `migrate_into` при обрыве переноса, только не при переносе, а при обычной
// работе); `audit.log` рос без предела.

/// Атомарная запись: tmp в том же каталоге → rename (краш на середине не бьёт целевой файл).
pub fn write_atomic(path: &Path, bytes: &[u8]) -> Result<()> {
    let tmp = path.with_extension("tmp.write");
    std::fs::write(&tmp, bytes).with_context(|| format!("не записать {}", tmp.display()))?;
    if let Err(e) = std::fs::rename(&tmp, path) {
        // Windows: rename поверх существующего иногда требует удаления цели
        let _ = std::fs::remove_file(path);
        std::fs::rename(&tmp, path).with_context(|| format!("не заменить {}: {e}", path.display()))?;
    }
    Ok(())
}

/// Прочитать JSON; битый файл НЕ теряется молча — уводится в `<имя>.corrupt.bak` с warn.
pub fn read_json_or_quarantine<T: serde::de::DeserializeOwned>(path: &Path) -> Option<T> {
    if !path.exists() {
        return None;
    }
    let content = match std::fs::read_to_string(path) {
        Ok(c) => c,
        Err(e) => {
            warn!("durable_store: не прочитан {}: {e}", path.display());
            return None;
        }
    };
    match serde_json::from_str::<T>(&content) {
        Ok(v) => Some(v),
        Err(e) => {
            let bak = path.with_extension("corrupt.bak");
            let _ = std::fs::rename(path, &bak);
            warn!(
                "durable_store: битый JSON {} → карантин {} ({e})",
                path.display(),
                bak.display()
            );
            None
        }
    }
}

/// Ротация лог-файла: при превышении лимита текущий уходит в `<имя>.1` (одно поколение).
pub fn rotate_if_large(path: &Path, max_bytes: u64) {
    if let Ok(md) = std::fs::metadata(path) {
        if md.len() > max_bytes {
            let rolled = path.with_extension("log.1");
            let _ = std::fs::remove_file(&rolled);
            if std::fs::rename(path, &rolled).is_ok() {
                info!("durable_store: ротация {} (> {} байт)", path.display(), max_bytes);
            }
        }
    }
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
        assert!(
            migrate_into(&new_dir, &legacy, "history", truncating_copy).is_err(),
            "обрыв копирования — неполный перенос, он обязан вернуть ошибку"
        );
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

        // 🔴 Внешний аудит 2026-07-29 (Critical): неполный перенос теперь ОШИБКА. Раньше здесь
        // возвращался Ok, и потребитель работал с пустым местом непереехавшего файла — создавал
        // новый файл поверх, а следующий заход навсегда закрывал дорогу оригиналу.
        let outcome = migrate_into(&new_dir, &legacy, "test", failing_copier);
        assert!(
            outcome.is_err(),
            "перенос с отказавшим файлом обязан вернуть ошибку, а не тихий успех"
        );

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

    // ── Внешний аудит 2026-07-29 (High): три защитных примитива, возвращённые из донора выше
    // (write_atomic / read_json_or_quarantine / rotate_if_large).

    /// Бюллет 3 задачи: после атомарной записи в целевом файле лежит ЦЕЛИКОМ новое содержимое,
    /// а временный файл (`<имя>.tmp.write`) не остаётся.
    #[test]
    fn atomic_write_replaces_existing_and_leaves_no_tmp_file() {
        let dir = std::env::temp_dir().join(format!("ds_test_atomic_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let f = dir.join("x.json");
        write_atomic(&f, b"[1]").unwrap();
        write_atomic(&f, b"[1,2]").unwrap();
        assert_eq!(std::fs::read_to_string(&f).unwrap(), "[1,2]", "содержимое обязано быть целиком новым");
        assert!(!f.with_extension("tmp.write").exists(), "временный файл не должен остаться после rename");
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Бюллет 1 задачи (на уровне примитива): битый JSON не подменяется молча пустым значением —
    /// уходит в карантин `.corrupt.bak`.
    #[test]
    fn corrupt_json_goes_to_quarantine_not_silence() {
        let dir = std::env::temp_dir().join(format!("ds_test_q_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let f = dir.join("h.json");
        std::fs::write(&f, "{битый").unwrap();
        let r: Option<Vec<u32>> = read_json_or_quarantine(&f);
        assert!(r.is_none());
        assert!(!f.exists(), "битый файл должен уйти в карантин");
        assert!(f.with_extension("corrupt.bak").exists(), "карантин-копия обязана существовать");
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Бюллет 2 задачи: после карантина исходное содержимое битого файла сохранено дословно —
    /// данные клиента не уничтожены, их можно восстановить вручную из `.corrupt.bak`.
    #[test]
    fn quarantine_preserves_original_corrupt_content() {
        let dir = std::env::temp_dir().join(format!("ds_test_qc_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let f = dir.join("h.json");
        let garbage = "{битый json, не список сообщений клиента";
        std::fs::write(&f, garbage).unwrap();
        let r: Option<Vec<u32>> = read_json_or_quarantine(&f);
        assert!(r.is_none());
        assert_eq!(
            std::fs::read_to_string(f.with_extension("corrupt.bak")).unwrap(),
            garbage,
            "карантинная копия обязана содержать ИСХОДНЫЕ байты без искажения"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Бюллет 4 задачи: ротация срабатывает при превышении порога и не теряет содержимое —
    /// текущий файл уходит в `<имя>.1` целиком, а не обрезается и не отбрасывается.
    #[test]
    fn rotate_rolls_over_and_preserves_content() {
        let dir = std::env::temp_dir().join(format!("ds_test_r_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let f = dir.join("a.log");
        let content = vec![b'x'; 100];
        std::fs::write(&f, &content).unwrap();
        rotate_if_large(&f, 10);
        assert!(!f.exists(), "текущий путь обязан освободиться для нового лога");
        assert_eq!(
            std::fs::read(f.with_extension("log.1")).unwrap(), content,
            "содержимое ротированного файла обязано остаться полным — не потеряны свежие записи"
        );
        // Ниже порога — ротации не происходит (файла для сравнения ещё нет).
        std::fs::write(&f, vec![b'y'; 5]).unwrap();
        rotate_if_large(&f, 10);
        assert!(f.exists(), "файл ниже порога не должен ротироваться");
        let _ = std::fs::remove_dir_all(&dir);
    }
}
