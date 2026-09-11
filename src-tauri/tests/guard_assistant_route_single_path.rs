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
        // 🔴 Находка внешнего аудита (Medium, s41): символьный литерал `'"'` открывал
        // режим строки на общих основаниях (одиночная кавычка проходила как обычный
        // символ, а следующая за ней двойная кавычка запускала разбор строки) — до
        // следующей НАСТОЯЩЕЙ двойной кавычки в файле комментарии не вырезались вовсе,
        // включая адреса и вызовы в комментариях. Отличаем литерал (`'"'`, `'\''`,
        // `'\\'`, `'x'`) от времени жизни (`'a`, `'static`) закрывающей кавычкой в
        // пределах разумной длины тела литерала: у времени жизни её нет никогда.
        if c == '\'' {
            let mut j = i + 1;
            let limit = chars.len().min(i + 12);
            let mut close = None;
            while j < limit {
                if chars[j] == '\\' {
                    j += 2;
                    continue;
                }
                if chars[j] == '\'' {
                    close = Some(j);
                    break;
                }
                j += 1;
            }
            if let Some(close) = close {
                for k in i..=close {
                    out.push(chars[k]);
                }
                i = close + 1;
                continue;
            }
            // Закрывающей кавычки нет рядом — это время жизни, обычный символ.
            out.push(c);
            i += 1;
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
            // 🔴 Находка внешнего аудита (High, s41): `decide_with_history` — тоже вход
            // автоопределения (правило приоритета «явный выбор → автоопределение»,
            // память о локальной работе), а прежде в списке стояли только `resolve` и
            // `local_available`. Вызов `execution_mode::decide_with_history(..)` из
            // claude.rs воскресил бы молчаливое автоопределение мимо обоих сторожей.
            for marker in [
                "execution_mode::resolve(",
                "execution_mode::local_available(",
                "execution_mode::decide_with_history(",
            ] {
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

/// 🔴 Запрет `run_claude_inner(` — по всему не-тестовому коду крейта, а не только в
/// телах `run_claude`/`run_claude_pipeline` (находка внешнего аудита, High, s41).
///
/// Прежняя проверка смотрела внутрь тел двух точек входа и такой обход не видела:
/// промежуточная функция (`async fn dispatch(){ run_claude_inner(..) }`), вызванная
/// из `run_claude`, содержит вызов `run_claude_inner(` не в теле `run_claude` самой
/// по себе — сторож молчал бы. Здесь запрет снят с двух конкретных функций и
/// поставлен на весь крейт: вызов допустим только в собственном определении функции
/// и в тестовом коде.
///
/// Мутация, которую обязан ловить этот тест: любая функция вне `#[cfg(test)]`,
/// зовущая `run_claude_inner(...)`, кроме самого определения `fn run_claude_inner(`.
#[test]
fn run_claude_inner_is_called_only_from_its_own_definition() {
    let mut files = Vec::new();
    collect_rs(&src_dir(), &mut files);
    let mut callers = Vec::new();
    for path in files {
        let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("").to_string();
        let Ok(raw) = fs::read_to_string(&path) else { continue };
        let code = strip_comments(&raw);
        let code = strip_test_modules(&code);
        for (idx, line) in code.lines().enumerate() {
            if !line.contains("run_claude_inner(") {
                continue;
            }
            // Собственное определение — не вызов.
            if line.contains("fn run_claude_inner(") {
                continue;
            }
            callers.push(format!("{name}:{} → run_claude_inner(", idx + 1));
        }
    }
    assert!(
        callers.is_empty(),
        "run_claude_inner вызывается в обход единственных точек входа ассистента:\n  {}\n\n\
         Локальный Claude Code клиента убран из маршрута решением владельца 10.09.2026: \
         промежуточная функция скрыла бы этот вызов от проверки тел run_claude/\
         run_claude_pipeline.",
        callers.join("\n  "),
    );
}

/// Вырезает тело `#[cfg(test)] mod ... { ... }`, чтобы тестовый код не считался
/// рабочим путём. Тот же приём поиска конца тела, что и `extract_fn`: закрывающая
/// скобка в начале строки — соглашение, которого держится весь этот крейт для
/// тестовых модулей верхнего уровня.
///
/// 🔴 Чего эта функция НЕ ловит: `#[cfg(test)]` на отдельной функции вне `mod tests`
/// (в крейте такого нет ни разу на дату написания — например,
/// `execution_mode.rs::decide` стоит именно внутри top-level `mod tests`). Появись
/// такой случай — тело этой функции не вырежется, и ложная краснота возможна.
fn strip_test_modules(code: &str) -> String {
    let mut result = String::with_capacity(code.len());
    let mut search_from = 0usize;
    let marker = "#[cfg(test)]";
    while let Some(rel) = code[search_from..].find(marker) {
        let marker_pos = search_from + rel;
        result.push_str(&code[search_from..marker_pos]);
        let after_marker = marker_pos + marker.len();
        let trimmed_after = code[after_marker..].trim_start();
        let is_mod = trimmed_after.starts_with("mod ")
            || trimmed_after.starts_with("pub mod ")
            || trimmed_after.starts_with("pub(crate) mod ");
        if !is_mod {
            // #[cfg(test)] на отдельном элементе (не mod) — не наша забота здесь.
            result.push_str(marker);
            search_from = after_marker;
            continue;
        }
        let Some(brace_rel) = code[after_marker..].find('{') else {
            result.push_str(marker);
            search_from = after_marker;
            continue;
        };
        let body_start = after_marker + brace_rel + 1;
        let end_rel = code[body_start..].find("\n}").map(|e| e + 2).unwrap_or(code.len() - body_start);
        let body_end = body_start + end_rel;
        // Сохраняем число строк внутри вырезанного диапазона — номера строк снаружи
        // (в отказах остальных проверок) не должны съехать.
        let removed = &code[marker_pos..body_end];
        result.push_str(&"\n".repeat(removed.matches('\n').count()));
        search_from = body_end;
    }
    result.push_str(&code[search_from..]);
    result
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

/// Символьные литералы не открывают ложный режим строки (соседний сторож держит ту
/// же проверку для своей копии `strip_comments` — см. `guard_left_position_egress.rs`).
///
/// Комментарий БЕЗ кавычек вокруг цели нарочно (обычный стиль: `// см. run_claude_inner(`):
/// после единственного символьного литерала `'"'` старая реализация видела в его
/// кавычке открытие строки и не находила ни одной кавычки до конца входа — весь
/// остаток, включая цель, уходил в вывод как «содержимое строки».
#[test]
fn comment_stripper_handles_char_literals_not_string_mode() {
    let sample = "let q = '\"'; // см. run_claude_inner(\n";
    let out = strip_comments(sample);
    assert_eq!(
        out.matches("run_claude_inner(").count(),
        0,
        "символьный литерал с кавычкой внутри не имеет права выключить вырезание \
         комментариев на остаток строки: {out}",
    );
}

/// `strip_test_modules` вырезает тело `#[cfg(test)] mod tests { ... }`, но не трогает
/// код снаружи и не путает `#[cfg(test)]` на отдельной функции с модулем.
#[test]
fn strip_test_modules_removes_only_the_test_module_body() {
    let sample = "fn live() { run_claude_inner(); }\n\
                  #[cfg(test)]\n\
                  mod tests {\n\
                      fn t() { run_claude_inner(); }\n\
                  }\n\
                  fn after() { run_claude_inner(); }\n\
                  #[cfg(test)]\n\
                  fn standalone() { run_claude_inner(); }\n";
    let out = strip_test_modules(sample);
    assert_eq!(
        out.matches("run_claude_inner(").count(),
        3,
        "внутри mod tests обязана исчезнуть ровно одна находка, три (live/after/standalone) \
         обязаны остаться: {out}",
    );
    assert!(out.contains("fn live()"), "код до модуля обязан остаться: {out}");
    assert!(out.contains("fn after()"), "код после модуля обязан остаться: {out}");
}
