//! Структурный сторож против возврата CPD-77 / CPD-79.
//!
//! Из продукта убраны два порождения внешних процессов, которые поведенческая защита
//! антивируса (Kaspersky, 10.08 и 11.08.2026) распознавала как вредоносные и снимала оболочку
//! продукта с диска у пользователя:
//! - `icacls <каталог> /inheritance:r /grant:r …` — переустановка прав каталога сессий
//!   (`/grant:r` ЗАМЕНЯЕТ список прав целиком, из-за чего SYSTEM и «Администраторы» молча
//!   исчезали); подробности и замена без порождения процесса — `src/win_acl.rs`;
//! - `cmd /C "netstat -ano | findstr :порт"` — разведка процессов по порту перед снятием
//!   зависшего движка (CPD-77), и следом регресс той же правки, потерявший гарантию, что
//!   найденный процесс — держатель НАШЕГО порта (CPD-79); подробности —
//!   `src/econ_sidecar.rs::kill_sidecar_from_state` и `src/sidecar_runtime.rs`.
//!
//! Опасность не в том, что кто-то напишет эти вызовы заново, а в том, что они молча вернутся
//! при слиянии старой ветки: на 14.08.2026 обе части дефекта живы как минимум в
//! `feat/econ-canon-p0` и `fix/econ-gw-sign-prefix`. Слияние любой из них должно быть поймано
//! здесь, а не у клиента.
//!
//! Почему тест лежит в `src-tauri/tests/`, а не рядом с кодом в `src-tauri/src/`: интеграционные
//! тесты Cargo — отдельная директория, которую этот же сторож не сканирует (он смотрит только
//! `src/`). Самоисключение получается по расположению файла, а не по имени внутри списка
//! проверяемых файлов — не нужно помнить вычеркнуть себя при переименовании.

use std::fs;
use std::path::{Path, PathBuf};

/// Образцы, запрещённые в исполняемом коде продукта (после отбрасывания комментариев).
/// Поиск без учёта регистра — см. `scan_file`.
const FORBIDDEN_PATTERNS: &[&str] = &["icacls", "/grant:r", "netstat", "findstr", "tasklist"];

/// Один найденный запрещённый образец — файл, строка, что именно нашлось и сама строка.
struct Hit {
    file: PathBuf,
    line: usize,
    pattern: &'static str,
    text: String,
}

/// Отбрасывает построчные (`//`, `///`, `//!`) и блочные (`/* … */`, в т.ч. вложенные,
/// Rust это допускает) комментарии.
///
/// Содержимое строковых литералов — обычных, byte- и raw-строк — СОХРАНЯЕТСЯ дословно и
/// экранирование (`\`) внутри них учитывается, чтобы кавычка-escape не оборвала строку раньше
/// времени. Строки — не шум для отбрасывания, а именно то место, где стоят опасные вызовы вида
/// `Command::new("icacls")`.
///
/// Символьные литералы (`'x'`) и лайфтаймы (`'a`) в отдельное состояние намеренно не выделены:
/// они физически не могут вместить многобуквенный запрещённый образец («icacls», «netstat» и
/// т.д.), поэтому отсутствие такого разбора не создаёт ни ложных срабатываний, ни пропусков.
///
/// Переносы строк не удаляются нигде, включая многострочные блочные комментарии, — номер
/// строки в отчёте об отказе обязан совпадать с номером строки в исходном файле.
fn strip_comments(src: &str) -> String {
    let chars: Vec<char> = src.chars().collect();
    let n = chars.len();
    let mut out = String::with_capacity(src.len());
    let mut i = 0;

    while i < n {
        // Построчный комментарий: `//`, `///`, `//!`.
        if chars[i] == '/' && i + 1 < n && chars[i + 1] == '/' {
            while i < n && chars[i] != '\n' {
                i += 1;
            }
            continue; // сам '\n' допишется обычной веткой на следующем шаге цикла
        }

        // Блочный комментарий `/* … */` — Rust допускает вложенность.
        if chars[i] == '/' && i + 1 < n && chars[i + 1] == '*' {
            let mut depth = 1;
            i += 2;
            while i < n && depth > 0 {
                if chars[i] == '/' && i + 1 < n && chars[i + 1] == '*' {
                    depth += 1;
                    i += 2;
                } else if chars[i] == '*' && i + 1 < n && chars[i + 1] == '/' {
                    depth -= 1;
                    i += 2;
                } else {
                    if chars[i] == '\n' {
                        out.push('\n');
                    }
                    i += 1;
                }
            }
            continue;
        }

        // Raw-строка: необязательный `b`, `r`, N решёток, открывающая кавычка.
        if let Some((content_start, hashes)) = raw_string_prefix(&chars, i) {
            for &pc in &chars[i..content_start] {
                out.push(pc);
            }
            let mut j = content_start;
            while j < n {
                if chars[j] == '"' && closes_raw_string(&chars, j, hashes) {
                    for k in 0..=hashes {
                        out.push(chars[j + k]);
                    }
                    j += hashes + 1;
                    break;
                }
                out.push(chars[j]);
                j += 1;
            }
            i = j;
            continue;
        }

        // Обычная (в т.ч. byte-) строка `"…"` — экранирование `\` учитывается.
        if chars[i] == '"' {
            out.push('"');
            i += 1;
            while i < n {
                let c = chars[i];
                out.push(c);
                i += 1;
                if c == '\\' && i < n {
                    out.push(chars[i]);
                    i += 1;
                    continue;
                }
                if c == '"' {
                    break;
                }
            }
            continue;
        }

        out.push(chars[i]);
        i += 1;
    }

    out
}

/// Если позиция `i` — начало raw-строки (`r"…"`, `r#"…"#`, `br##"…"##`, …), возвращает индекс
/// первого символа содержимого и число решёток. Иначе `None`.
fn raw_string_prefix(chars: &[char], i: usize) -> Option<(usize, usize)> {
    let n = chars.len();
    let mut j = i;
    if j < n && chars[j] == 'b' {
        j += 1;
    }
    if j >= n || chars[j] != 'r' {
        return None;
    }
    j += 1;
    let mut hashes = 0;
    while j < n && chars[j] == '#' {
        hashes += 1;
        j += 1;
    }
    if j < n && chars[j] == '"' {
        Some((j + 1, hashes))
    } else {
        None
    }
}

/// Проверяет, что кавычка в позиции `j` закрывает raw-строку с данным числом решёток
/// (`chars[j+1..=j+hashes]` — ровно `hashes` символов `#`).
fn closes_raw_string(chars: &[char], j: usize, hashes: usize) -> bool {
    let n = chars.len();
    if j + hashes >= n {
        return false;
    }
    (1..=hashes).all(|k| chars[j + k] == '#')
}

/// Сканирует один файл на запрещённые образцы после отбрасывания комментариев.
/// Поиск без учёта регистра — тривиальный обход вида `ICACLS`/`NetStat` тоже должен упасть.
fn scan_file(path: &Path) -> Vec<Hit> {
    let raw = fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("не удалось прочитать {}: {e}", path.display()));
    let cleaned = strip_comments(&raw);
    let mut hits = Vec::new();
    for (idx, line) in cleaned.lines().enumerate() {
        let lower = line.to_lowercase();
        for pat in FORBIDDEN_PATTERNS {
            if lower.contains(pat) {
                hits.push(Hit {
                    file: path.to_path_buf(),
                    line: idx + 1,
                    pattern: pat,
                    text: line.trim().to_string(),
                });
            }
        }
    }
    hits
}

/// Обходит все `.rs`-файлы `src-tauri/src` (сам сторож в `src-tauri/tests/` не входит в этот
/// каталог, см. шапку модуля) и падает, если после отбрасывания комментариев в исполняемом
/// коде находится хотя бы один запрещённый образец CPD-77/CPD-79.
#[test]
fn no_regressed_cpd77_cpd79_calls_in_product_sources() {
    let manifest_dir =
        std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR не задан тестовым раннером");
    let src_dir = Path::new(&manifest_dir).join("src");
    assert!(
        src_dir.is_dir(),
        "каталог исходников не найден: {} — сторож проверять нечего",
        src_dir.display()
    );

    let mut hits = Vec::new();
    for entry in walkdir::WalkDir::new(&src_dir)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| e.file_type().is_file())
        .filter(|e| e.path().extension().and_then(|ext| ext.to_str()) == Some("rs"))
    {
        hits.extend(scan_file(entry.path()));
    }

    if !hits.is_empty() {
        let mut msg = String::from(
            "Сторож CPD-77/CPD-79 нашёл запрещённый образец в исполняемом коде (комментарии уже \
             отброшены) — возврат опасного вызова из старой ветки:\n",
        );
        for h in &hits {
            msg.push_str(&format!(
                "  {}:{} — образец «{}» → {}\n",
                h.file.display(),
                h.line,
                h.pattern,
                h.text
            ));
        }
        msg.push_str(
            "См. src-tauri/tests/guard_no_regressed_cpd77_cpd79.rs и src/win_acl.rs / \
             src/econ_sidecar.rs / src/sidecar_runtime.rs за объяснением, чем заменены эти вызовы.",
        );
        panic!("{msg}");
    }
}

// ── Проверка самого сторожа: strip_comments не должен ни съедать код, ни путать строки ───────

#[test]
fn strip_comments_removes_line_and_nested_block_comments_but_keeps_line_count() {
    let src = "a\n// icacls comment\nb /* netstat\nnested /* inner */ still comment */ c\nd";
    let cleaned = strip_comments(src);
    assert_eq!(cleaned.lines().count(), src.lines().count(), "число строк обязано совпасть");
    assert!(!cleaned.to_lowercase().contains("icacls"), "построчный комментарий не отброшен");
    assert!(!cleaned.to_lowercase().contains("netstat"), "блочный комментарий не отброшен");
    assert!(cleaned.contains('a') && cleaned.contains('b') && cleaned.contains('c'));
    assert!(cleaned.contains('d'), "код после комментария потерян");
}

#[test]
fn strip_comments_keeps_string_and_raw_string_literal_content() {
    let src = "let a = \"icacls\"; // не трогать вызов внутри строки\nlet b = r\"netstat #tasklist\";";
    let cleaned = strip_comments(src);
    assert!(cleaned.contains("\"icacls\""), "обычный строковый литерал не должен исчезнуть");
    assert!(cleaned.contains("netstat #tasklist"), "raw-строка не должна исчезнуть");
    assert!(!cleaned.contains("не трогать"), "текст комментария обязан быть отброшен");
}
