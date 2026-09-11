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
        // 🔴 Находка проверяющего-противника (11.09.2026): сырые строки (`r"…"`,
        // `r#"…"#`, `br"…"`) кавычки внутри себя НЕ экранируют. Обычный разбор строки
        // ниже об этом не знает: первая же внутренняя кавычка сырой строки закрывала
        // бы (в его понимании) «обычную» строку, и на нечётном числе кавычек внутри
        // разбор терял синхронизацию на весь остаток файла — в частности, `//` внутри
        // следующего же адреса («https://…») попадал в режим «обычный код» и стирался
        // как комментарий вместе с адресом. Сырую строку поглощаем целиком отдельно:
        // считаем число `#` после `r`/`br`, затем ищем `"`, за которой идёт ровно
        // столько же `#`.
        if (c == 'r' || (c == 'b' && next == 'r'))
            && (i == 0 || !(chars[i - 1].is_alphanumeric() || chars[i - 1] == '_'))
        {
            let mut j = if c == 'b' { i + 2 } else { i + 1 };
            let hash_start = j;
            while j < chars.len() && chars[j] == '#' {
                j += 1;
            }
            let hashes = j - hash_start;
            if j < chars.len() && chars[j] == '"' {
                for k in i..=j {
                    out.push(chars[k]);
                }
                i = j + 1;
                loop {
                    if i >= chars.len() {
                        break;
                    }
                    if chars[i] == '"' {
                        let mut k = i + 1;
                        let mut matched = 0usize;
                        while k < chars.len() && chars[k] == '#' && matched < hashes {
                            matched += 1;
                            k += 1;
                        }
                        if matched == hashes {
                            for m in i..k {
                                out.push(chars[m]);
                            }
                            i = k;
                            break;
                        }
                    }
                    out.push(chars[i]);
                    i += 1;
                }
                continue;
            }
            // Не сырая строка (например, обычный идентификатор, начинающийся на `r`
            // или `b`) — падаем в общий разбор ниже как одиночный символ.
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

/// Три имени execution_mode, обращение к которым извне запрещено — «выведенные имена»
/// автоопределения (правило приоритета resolve/decide_with_history и зонд
/// local_available, см. докстрок теста ниже).
const FORBIDDEN_EXECUTION_MODE_NAMES: [&str; 3] =
    ["resolve", "local_available", "decide_with_history"];

/// Слово `word` встречается в `haystack` как ЦЕЛЫЙ идентификатор (границы — не
/// буква/цифра/`_` с обеих сторон), не как часть более длинного имени
/// (`resolve_something_else` не считается вхождением слова `resolve`).
fn contains_word(haystack: &str, word: &str) -> bool {
    let h: Vec<char> = haystack.chars().collect();
    let w: Vec<char> = word.chars().collect();
    if w.is_empty() || h.len() < w.len() {
        return false;
    }
    let is_ident = |c: char| c.is_alphanumeric() || c == '_';
    'outer: for start in 0..=(h.len() - w.len()) {
        for (k, wc) in w.iter().enumerate() {
            if h[start + k] != *wc {
                continue 'outer;
            }
        }
        let before_ok = start == 0 || !is_ident(h[start - 1]);
        let after_idx = start + w.len();
        let after_ok = after_idx >= h.len() || !is_ident(h[after_idx]);
        if before_ok && after_ok {
            return true;
        }
    }
    false
}

/// Все `use`-выражения файла как текст от `use` до ближайшего `;` включительно —
/// хватает однострочных и фигурноскобочных многострочных импортов одинаково.
fn use_statements(code: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut search_from = 0usize;
    while let Some(rel) = code[search_from..].find("use ") {
        let start = search_from + rel;
        // "use " обязано начинать выражение, не быть хвостом более длинного
        // идентификатора (например, "reuse ").
        let boundary_ok = start == 0
            || !code[..start]
                .chars()
                .next_back()
                .map(|c| c.is_alphanumeric() || c == '_')
                .unwrap_or(false);
        if !boundary_ok {
            search_from = start + 4;
            continue;
        }
        let Some(semi_rel) = code[start..].find(';') else { break };
        let end = start + semi_rel + 1;
        out.push(code[start..end].to_string());
        search_from = end;
    }
    out
}

/// Если в `stmt` модуль `module` переименован через ` as <псевдоним>`, вернуть
/// псевдоним. `use crate::commands::execution_mode::resolve;` вернёт `None`
/// (это импорт ИМЕНИ изнутри модуля, не переименование самого модуля — тот случай
/// ловит прямая проверка `FORBIDDEN_EXECUTION_MODE_NAMES` через `contains_word`).
fn module_alias_after(stmt: &str, module: &str) -> Option<String> {
    let h: Vec<char> = stmt.chars().collect();
    let m: Vec<char> = module.chars().collect();
    if h.len() < m.len() {
        return None;
    }
    let is_ident = |c: char| c.is_alphanumeric() || c == '_';
    'outer: for start in 0..=(h.len() - m.len()) {
        for (k, mc) in m.iter().enumerate() {
            if h[start + k] != *mc {
                continue 'outer;
            }
        }
        let before_ok = start == 0 || !is_ident(h[start - 1]);
        let after_idx = start + m.len();
        if !before_ok || (after_idx < h.len() && is_ident(h[after_idx])) {
            continue;
        }
        let rest: String = h[after_idx..].iter().collect();
        let rest = rest.trim_start();
        if let Some(tail) = rest.strip_prefix("as ") {
            let alias: String =
                tail.trim_start().chars().take_while(|c| is_ident(*c)).collect();
            if !alias.is_empty() {
                return Some(alias);
            }
        }
    }
    None
}

/// 🔴 Автоопределения маршрута нет ни в одном рабочем пути.
///
/// Правило приоритета `resolve`/`decide_with_history` и зонд `claude --version` оставлены в
/// дереве до решения владельца об удалении, но НЕ ВЫЗЫВАЮТСЯ. Зовущий их снова получает отказ
/// здесь, а не у клиента.
///
/// 🔴 Находки проверяющего-противника (11.09.2026): полное имя `execution_mode::resolve(`
/// в тексте — не единственный способ его позвать. Обход первый — `use`-импорт (голым
/// именем, в фигурных скобках, с `as`-переименованием): `use ...execution_mode::{resolve,
/// local_available}; resolve(..)`. Обход второй — псевдоним МОДУЛЯ: `use
/// ...execution_mode as em; em::resolve(..)`. Оба обхода закрываются на первопричине —
/// на самом `use`-выражении, а не на месте вызова: без импорта или псевдонима модуля
/// голое имя `resolve` физически не может в Rust разрешиться в
/// `execution_mode::resolve` (неявных путей нет), так что запрет самого`use`-выражения
/// необходим и достаточен. Это НАРОЧНО не бан «голого слова resolve где угодно в
/// крейте» — такое имя используется в claude.rs для совсем другого, не связанного с
/// execution_mode, параметра (`resolve: impl FnOnce() -> ...`), и голый запрет дал бы
/// ложную красноту на честном дереве.
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
        let code = strip_test_modules(&code);
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
        // use-импорт выведенных имён (голым именем, в {..}, с `as`) и псевдоним
        // модуля execution_mode с последующим вызовом через него.
        for stmt in use_statements(&code) {
            if !contains_word(&stmt, "execution_mode") {
                continue;
            }
            for forbidden in FORBIDDEN_EXECUTION_MODE_NAMES {
                if contains_word(&stmt, forbidden) {
                    callers.push(format!(
                        "{name} → use-импорт выведенного имени `{forbidden}` из execution_mode: {}",
                        stmt.trim(),
                    ));
                }
            }
            if let Some(alias) = module_alias_after(&stmt, "execution_mode") {
                for forbidden in FORBIDDEN_EXECUTION_MODE_NAMES {
                    // 🔴 Голое имя через псевдоним (без обязательной скобки) — тоже
                    // находка (находка проверяющего-противника: `let _a5 =
                    // em::local_available;`, указатель на функцию без вызова).
                    // Коллизии нет: «alias» — конкретный псевдоним ИЗ ЭТОГО ЖЕ
                    // use-выражения этого же файла, не произвольное слово.
                    let marker = format!("{alias}::{forbidden}");
                    if contains_word(&code, &marker) {
                        callers.push(format!(
                            "{name} → псевдоним модуля `{alias}` (из {}) → {marker}",
                            stmt.trim(),
                        ));
                    }
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
///
/// 🔴 Находка проверяющего-противника (11.09.2026): требование скобки сразу после
/// имени (`run_claude_inner(`) не видело обхода без вызова — голого указателя
/// (`let g = crate::commands::claude::run_claude_inner;`) или `use`-импорта с
/// переименованием (`use ...run_claude_inner as inner; let f = inner;`), после
/// которого имя дальше упоминается уже под другим словом. Проверка теперь ищет
/// ГОЛОЕ имя `run_claude_inner` (без обязательной скобки) — коллизии с другим,
/// не связанным именем в крейте нет (проверено: имя встречается только в
/// определении и в собственных, уже вырезаемых `strip_comments`, doc-комментариях).
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
            if !contains_word(line, "run_claude_inner") {
                continue;
            }
            // Собственное определение — не вызов и не обход.
            if line.contains("fn run_claude_inner(") {
                continue;
            }
            callers.push(format!("{name}:{} → run_claude_inner", idx + 1));
        }
    }
    assert!(
        callers.is_empty(),
        "run_claude_inner упоминается в обход единственных точек входа ассистента:\n  {}\n\n\
         Локальный Claude Code клиента убран из маршрута решением владельца 10.09.2026: \
         промежуточная функция, псевдоним или голый указатель на функцию скрыли бы это \
         упоминание от проверки тел run_claude/run_claude_pipeline.",
        callers.join("\n  "),
    );
}

/// Конец блока `{ .. }`, начинающегося сразу после открывающей скобки в позиции
/// `body_start` (сама скобка уже учтена — глубина стартует с 1). Считает пары
/// фигурных скобок посимвольно, а не текстом `\n}`.
///
/// 🔴 Находка проверяющего-противника (11.09.2026): поиск буквального `\n}` не видит
/// вложенный `#[cfg(test)] mod tests { .. }` внутри обычного `mod x { .. }` —
/// закрывающая скобка вложенного модуля почти всегда с отступом (`    }`), а не одна
/// в начале строки, и текстовый поиск проскакивает её, находя следующую бесотступную
/// `}` — то есть конец ВНЕШНЕГО блока. Всё, что лежало между вложенным тестовым
/// модулем и концом внешнего (включая живой код), стиралось вместе с тестами.
/// Строковые и символьные литералы, где могут жить свои `{`/`}` (например, в
/// формат-строке `"{cabinet_id}"`), пропускаются тем же приёмом, что и
/// `strip_comments` — иначе счёт скобок сбился бы на первом же таком литерале.
fn find_matching_brace_end(code: &str, body_start: usize) -> usize {
    let bytes = code.as_bytes();
    let mut depth: i32 = 1;
    let mut i = body_start;
    while i < bytes.len() {
        match bytes[i] {
            b'"' => {
                i += 1;
                while i < bytes.len() {
                    if bytes[i] == b'\\' {
                        i += 2;
                        continue;
                    }
                    let end = bytes[i] == b'"';
                    i += 1;
                    if end {
                        break;
                    }
                }
            }
            b'\'' => {
                let mut j = i + 1;
                let limit = bytes.len().min(i + 12);
                let mut close = None;
                while j < limit {
                    if bytes[j] == b'\\' {
                        j += 2;
                        continue;
                    }
                    if bytes[j] == b'\'' {
                        close = Some(j);
                        break;
                    }
                    j += 1;
                }
                i = close.map(|c| c + 1).unwrap_or(i + 1);
            }
            b'{' => {
                depth += 1;
                i += 1;
            }
            b'}' => {
                depth -= 1;
                i += 1;
                if depth == 0 {
                    break;
                }
            }
            _ => {
                i += 1;
            }
        }
    }
    i
}

/// Вырезает тело `#[cfg(test)] mod ... { ... }`, чтобы тестовый код не считался
/// рабочим путём. Конец тела ищется счётом фигурных скобок (`find_matching_brace_end`),
/// не текстом `\n}` — вложенные тестовые модули и модули без тела больше не режут
/// чужой код (обе бреши — находки проверяющего-противника, 11.09.2026).
///
/// 🔴 `#[cfg(test)] mod tests;` (БЕЗ тела — объявление модуля во внешнем файле) —
/// раньше искало `{` без ограничения расстояния и находило открывающую скобку
/// СЛЕДУЮЩЕЙ живой функции, стирая её тело целиком вместо пустого объявления. Теперь
/// сравниваются позиции ближайших `;` и `{`: что раньше, то и решает форму объявления.
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
        let semi_rel = code[after_marker..].find(';');
        let brace_rel = code[after_marker..].find('{');
        let is_bodyless = match (semi_rel, brace_rel) {
            (Some(s), Some(b)) => s < b,
            (Some(_), None) => true,
            (None, _) => false,
        };
        if is_bodyless {
            let Some(semi_rel) = semi_rel else { unreachable!("проверено выше") };
            // Объявление модуля без тела — вырезать нечего, оставляем как обычный код.
            let decl_end = after_marker + semi_rel + 1;
            result.push_str(&code[marker_pos..decl_end]);
            search_from = decl_end;
            continue;
        }
        let Some(brace_rel) = brace_rel else {
            result.push_str(marker);
            search_from = after_marker;
            continue;
        };
        let body_start = after_marker + brace_rel + 1;
        let body_end = find_matching_brace_end(code, body_start);
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

/// Сырая строка с нечётным числом кавычек внутри (`r#"say "hi\n"#`) не сбивает разбор
/// остатка файла — находка проверяющего-противника (11.09.2026): без распознавания
/// сырых строк внутренняя кавычка закрывала «обычную» строку раньше времени, разбор
/// терял синхронизацию, и `//` внутри следующего же адреса стирал его как комментарий.
#[test]
fn comment_stripper_handles_raw_strings_with_odd_inner_quotes() {
    let sample = "const T: &str = r#\"say \"hi\n\"#;\nconst U: &str = \"run_claude_inner(\";\n";
    let out = strip_comments(sample);
    assert_eq!(
        out.matches("run_claude_inner(").count(),
        1,
        "адрес/литерал ПОСЛЕ сырой строки с нечётным числом кавычек не имеет права \
         исчезнуть из разбора: {out}",
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

/// 🔴 Находка проверяющего-противника (11.09.2026): `#[cfg(test)] mod tests;` БЕЗ тела
/// (объявление модуля во внешнем файле) раньше искало ближайшую `{` без ограничения
/// расстояния — и находило открывающую скобку СЛЕДУЮЩЕЙ живой функции, стирая её тело
/// целиком. Модуль без тела обязан остаться нетронутым, а живой код после него —
/// не вырезаться из разбора.
#[test]
fn strip_test_modules_does_not_eat_the_next_function_after_a_bodyless_mod_tests() {
    let sample = "#[cfg(test)]\n\
                  mod tests;\n\
                  \n\
                  pub async fn live_after_bodyless_mod() {\n\
                      run_claude_inner();\n\
                  }\n";
    let out = strip_test_modules(sample);
    assert_eq!(
        out.matches("run_claude_inner(").count(),
        1,
        "живая функция после `mod tests;` без тела обязана остаться в разборе: {out}",
    );
    assert!(
        out.contains("pub async fn live_after_bodyless_mod()"),
        "сигнатура живой функции обязана уцелеть: {out}",
    );
}

/// 🔴 Находка проверяющего-противника (11.09.2026): вложенный `#[cfg(test)] mod tests
/// { .. }` (внутри обычного `mod x { .. }`) резался текстовым поиском `\n}` до конца
/// ВНЕШНЕГО модуля — его закрывающая скобка с отступом пропускалась, а бесотступная
/// скобка внешнего блока принималась за свою. Живой код между вложенным тестовым
/// модулем и концом внешнего блока обязан уцелеть.
#[test]
fn strip_test_modules_does_not_eat_past_a_nested_test_module() {
    let sample = "mod inner_live {\n\
                      #[cfg(test)]\n\
                      mod tests {\n\
                          #[test]\n\
                          fn t() {}\n\
                      }\n\
                      \n\
                      pub async fn live_after_nested_test_mod() {\n\
                          run_claude_inner();\n\
                      }\n\
                  }\n";
    let out = strip_test_modules(sample);
    assert_eq!(
        out.matches("run_claude_inner(").count(),
        1,
        "живая функция ПОСЛЕ вложенного mod tests обязана остаться в разборе: {out}",
    );
    assert!(
        out.contains("pub async fn live_after_nested_test_mod()"),
        "сигнатура живой функции внутри внешнего mod обязана уцелеть: {out}",
    );
}
