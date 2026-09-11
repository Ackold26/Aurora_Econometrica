//! Сторож (б): в правом положении запрос ассистента не идёт в локальный Claude Code клиента.
//!
//! 10.09.2026 средний маршрут сломал показ покупателю. Владелец включил облачную обработку и
//! обоснованно считал, что работа идёт через наш сервер. Фактически сработало автоопределение:
//! Claude Code на машине нашёлся, маршрут стал локальным, запрос ушёл в него и вернул чужой
//! английский отказ `Failed to authenticate. API error 403`. Узел этого запроса не видел вовсе.
//!
//! Маршрут через Claude Code клиента убран целиком. Этот сторож держит убранное убранным:
//! опасность не в том, что кто-то напишет ветку заново, а в том, что она вернётся при слиянии
//! старой ветки — молча и с виду безобидно.
//!
//! Проверяется структура исходников, а не прогон. Прогон доказал бы поведение на одной машине
//! и одном входе; структура доказывает отсутствие пути на всех.

use std::fs;
use std::path::{Path, PathBuf};

fn src_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("src")
}

fn read(rel: &str) -> String {
    let path = src_dir().join(rel.replace('/', std::path::MAIN_SEPARATOR_STR));
    fs::read_to_string(&path).unwrap_or_else(|e| panic!("{} обязан читаться: {e}", path.display()))
}

/// Отбрасывает комментарии, сохраняя строковые литералы (см. соседний сторож — там же
/// объяснение, почему литералы важны). Проверяется тестом ниже.
fn strip_comments(src: &str) -> String {
    let chars: Vec<char> = src.chars().collect();
    let mut out = String::with_capacity(src.len());
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        let next = chars.get(i + 1).copied().unwrap_or('\0');
        if c == '/' && next == '/' {
            while i < chars.len() && chars[i] != '\n' {
                i += 1;
            }
            continue;
        }
        if c == '/' && next == '*' {
            let mut depth = 1;
            i += 2;
            while i < chars.len() && depth > 0 {
                if chars[i] == '/' && chars.get(i + 1) == Some(&'*') {
                    depth += 1;
                    i += 2;
                } else if chars[i] == '*' && chars.get(i + 1) == Some(&'/') {
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
        if c == '"' {
            out.push(c);
            i += 1;
            while i < chars.len() {
                if chars[i] == '\\' {
                    out.push(chars[i]);
                    if i + 1 < chars.len() {
                        out.push(chars[i + 1]);
                    }
                    i += 2;
                    continue;
                }
                out.push(chars[i]);
                let end = chars[i] == '"';
                i += 1;
                if end {
                    break;
                }
            }
            continue;
        }
        out.push(c);
        i += 1;
    }
    out
}

/// Вырезать тело функции: от заголовка до закрывающей скобки в начале строки.
fn extract_fn(code: &str, signature: &str) -> String {
    let start = code
        .find(signature)
        .unwrap_or_else(|| panic!("не найдена функция «{signature}» — сторож проверял бы пустоту"));
    let tail = &code[start..];
    let end = tail.find("\n}").map(|e| e + 2).unwrap_or(tail.len());
    tail[..end].to_string()
}

/// 🔴 Ни одна точка входа ассистента не ведёт к запуску чужой программы на машине клиента.
///
/// Мутация, которую обязан ловить этот тест: вернуть вызов `run_claude_inner(...)` в
/// `run_claude` или `run_claude_pipeline`.
#[test]
fn assistant_entry_points_never_reach_the_local_cli() {
    let code = strip_comments(&read("commands/claude.rs"));
    for entry in ["pub async fn run_claude(", "pub async fn run_claude_pipeline("] {
        let body = extract_fn(&code, entry);
        for forbidden in ["run_claude_inner(", "find_claude_binary(", "windows_cmd_command_line("] {
            assert!(
                !body.contains(forbidden),
                "{entry} снова ведёт к локальному Claude Code клиента ({forbidden}). Этот \
                 маршрут убран решением владельца 10.09.2026: он выбирался молча, требовал у \
                 клиента установленной и авторизованной чужой программы и подменял наши \
                 сообщения английской диагностикой поставщика.",
            );
        }
        assert!(
            body.contains("gateway_executor::run_claude"),
            "{entry} обязана вести к шлюзу Авроры — другого пути у ассистента нет",
        );
    }
}

/// 🔴 Автоопределения маршрута нет ни в одном рабочем пути.
///
/// Правило приоритета `resolve`/`decide_with_history` и зонд `claude --version` оставлены в
/// дереве до решения владельца об удалении, но НЕ ВЫЗЫВАЮТСЯ. Зовущий их снова получает отказ
/// здесь, а не у клиента.
#[test]
fn autodetection_is_not_called_from_any_working_path() {
    let mut files = Vec::new();
    collect_rs(&src_dir(), &mut files);
    let mut callers = Vec::new();
    for path in files {
        let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("").to_string();
        // Сам модуль автоопределения — не «вызывающий код»: внутри него определения и
        // собственные проверки, а запрет касается обращений извне.
        if name == "execution_mode.rs" {
            continue;
        }
        let Ok(raw) = fs::read_to_string(&path) else { continue };
        let code = strip_comments(&raw);
        for (idx, line) in code.lines().enumerate() {
            for marker in ["execution_mode::resolve(", "execution_mode::local_available("] {
                if line.contains(marker) {
                    callers.push(format!("{name}:{} → {marker}", idx + 1));
                }
            }
        }
    }
    assert!(
        callers.is_empty(),
        "автоопределение маршрута снова вызывается:\n  {}\n\nРежим теперь всегда явный: \
         переключатель в настройках, два положения, третьего нет.",
        callers.join("\n  "),
    );
}

/// Зонд запуска чужой программы не заводится ни на одном горячем пути.
///
/// 🔴 Отдельной проверкой, потому что зонд возвращался бы не через развилку, а сбоку: его
/// звало состояние переключателя для интерфейса — на каждом открытии кабинета и на каждом
/// возврате фокуса окна. Такой возврат в развилке не виден.
#[test]
fn the_state_for_the_interface_does_not_launch_anything() {
    let code = strip_comments(&read("commands/execution_mode.rs"));
    let body = extract_fn(&code, "pub async fn state(");
    for forbidden in ["local_available(", "probe_local(", "resolve("] {
        assert!(
            !body.contains(forbidden),
            "состояние переключателя снова запускает зонд ({forbidden}): {body}",
        );
    }
    assert!(
        body.contains("route_state(app_handle)"),
        "состояние обязано считаться от единственной оси: {body}",
    );
}

/// Отказ шлюза не уводит никуда молча и приходит с кодом.
#[test]
fn gateway_failure_is_honest_and_coded() {
    let code = strip_comments(&read("commands/claude.rs"));
    assert!(
        code.contains("fn gateway_failure("),
        "отказ шлюза обязан проходить через свой разбор, а не молча всплывать наружу",
    );
    let body = extract_fn(&code, "fn gateway_failure(");
    assert!(body.contains("[CL-GW]"), "отказ обязан нести код: {body}");
    assert!(
        body.contains("никуда больше не отправлялась"),
        "человеку обязано быть сказано, что работа НЕ ушла другим путём: {body}",
    );
    // И сам отказ обязан быть подключён к обеим точкам входа.
    for entry in ["pub async fn run_claude(", "pub async fn run_claude_pipeline("] {
        let entry_body = extract_fn(&code, entry);
        assert!(
            entry_body.contains("map_err(gateway_failure)"),
            "{entry}: отказ шлюза обязан проходить через разбор",
        );
    }
}

/// Локальная редакция (152-ФЗ) не задета: ранний отказ ДО любого пути наружу на месте.
///
/// 🔴 Убиралась работа через Claude Code клиента — «мимо нашего шлюза, но наружу».
/// Сохранялась редакция, где пути наружу нет в коде вовсе. Сторож держит вторую.
#[test]
fn the_local_edition_is_untouched() {
    let code = strip_comments(&read("commands/claude.rs"));
    for entry in ["pub async fn run_claude(", "pub async fn run_claude_pipeline("] {
        let body = extract_fn(&code, entry);
        assert!(
            body.contains("#[cfg(not(feature = \"cloud_advisors\"))]"),
            "{entry}: ветка локальной редакции обязана остаться",
        );
        assert!(
            body.contains("[CL-LOCAL]"),
            "{entry}: ранний отказ локальной редакции обязан остаться дословным",
        );
    }
    let cabinet = strip_comments(&read("commands/cabinet.rs"));
    assert!(
        cabinet.contains("#[cfg(not(feature = \"cloud_advisors\"))]"),
        "в локальной редакции кабинет-советник обязан оставаться скрытым",
    );
}

fn collect_rs(dir: &Path, acc: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else { return };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_rs(&path, acc);
        } else if path.extension().and_then(|e| e.to_str()) == Some("rs") {
            acc.push(path);
        }
    }
}

#[test]
fn comment_stripper_keeps_strings_and_drops_comments() {
    let sample = "let a = \"run_claude_inner(\"; // run_claude_inner(\n/* run_claude_inner( */\n";
    let out = strip_comments(sample);
    assert_eq!(out.matches("run_claude_inner(").count(), 1, "остаться обязан только литерал: {out}");
}
