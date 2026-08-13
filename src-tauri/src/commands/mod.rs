pub mod brand;
pub mod cabinet;
pub mod campaign;
pub mod content_pack;
pub mod claude;
pub mod diagnostics;
pub mod data_migration;
pub mod content_updater;
pub mod econometrica;
/// Выбор режима исполнения советника во время работы (ADR-049): свой Claude Code
/// клиента или шлюз Авроры. Собирается ВСЕГДА — в сборке без облачного пути модуль
/// честно отвечает, что облачного режима нет, вместо того чтобы исчезнуть и заставить
/// вызывающий код снова ветвиться условной компиляцией.
pub mod execution_mode;
pub mod feedback;
#[cfg(feature = "thin")]
pub mod gateway_executor;
pub mod license;
pub mod mqs_tiers;
pub mod online_auth;
pub mod parser;
pub mod pptx_processor;
pub mod project;
pub mod rag_client;
pub mod report;
pub mod updater;
pub mod user_config;
pub mod vault;

use std::path::{Path, PathBuf};

/// Свободное имя файла рядом с `path` — CPD-70: готовый документ клиента (docx/xlsx/md-отчёт)
/// не должен молча затираться повторным экспортом в тот же каталог под тем же именем.
/// Свободное имя возвращается как есть. Занятое — получает суффикс-счётчик перед
/// расширением: `отчёт.docx` занято → `отчёт (2).docx` → `отчёт (3).docx` и так далее, пока
/// не найдётся свободное. Файл на диск не создаётся — только вычисляется путь, запись
/// остаётся на вызывающей стороне (TOCTOU-окно между вызовом и записью неизбежно при таком
/// API, но устраняет РЕГУЛЯРНЫЙ случай — повторный ручной экспорт, а не гонку потоков).
pub fn unique_export_path(path: &Path) -> PathBuf {
    if !path.exists() {
        return path.to_path_buf();
    }
    let parent = path.parent().unwrap_or_else(|| Path::new(""));
    let stem = path.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
    let ext = path.extension().map(|e| e.to_string_lossy().to_string());
    let mut n: u32 = 2;
    loop {
        let candidate_name = match &ext {
            Some(ext) => format!("{stem} ({n}).{ext}"),
            None => format!("{stem} ({n})"),
        };
        let candidate = parent.join(candidate_name);
        if !candidate.exists() {
            return candidate;
        }
        n += 1;
    }
}

#[cfg(test)]
mod unique_export_path_tests {
    use super::unique_export_path;
    use std::fs;

    #[test]
    fn free_name_returned_as_is() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("отчёт.docx");
        assert_eq!(unique_export_path(&path), path);
    }

    #[test]
    fn one_collision_gets_counter_two() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("отчёт.docx");
        fs::write(&path, b"existing").unwrap();
        let expected = tmp.path().join("отчёт (2).docx");
        assert_eq!(unique_export_path(&path), expected);
    }

    #[test]
    fn two_collisions_get_counter_three() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("отчёт.docx");
        fs::write(&path, b"existing").unwrap();
        fs::write(tmp.path().join("отчёт (2).docx"), b"existing2").unwrap();
        let expected = tmp.path().join("отчёт (3).docx");
        assert_eq!(unique_export_path(&path), expected);
    }
}
