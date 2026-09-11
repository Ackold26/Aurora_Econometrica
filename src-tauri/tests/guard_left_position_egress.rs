//! Сторож (а): в левом положении переключателя наружу уходят только три названных обращения.
//!
//! Левое положение — «полностью локально»: ИИ-ассистент отключён, материалы, вопросы и файлы
//! не покидают машину. Допустимых исходящих обращений ровно три (решение владельца 10.09.2026
//! плюс Р-1 от 11.09.2026): проверка лицензии, обновления программы и докачка содержимого
//! кабинетов и оболочки.
//!
//! 🔴 Список обращений сторож берёт ИЗ ИСХОДНИКОВ, а не из заранее выписанного перечня.
//! Перечень по построению слеп к обращению, которого в нём нет, — а заводятся потом именно
//! такие. Поэтому порядок обратный: сначала находим в коде ВСЕ места, откуда программа может
//! обратиться наружу, затем требуем, чтобы каждое было либо одним из трёх названных в подписи,
//! либо закрытым гейтом левого положения — и гейт для КАЖДОГО такого файла доказывается
//! структурно (см. `gated_by_route_files_actually_gate_their_egress`), список по имени файла
//! больше ничему не верит на слово. Незнакомое место — отказ с именем файла и строкой.
//!
//! Чего сторож НЕ доказывает: что закрытое гейтом место действительно молчит во время работы
//! (это доказывает прогон, а не чтение) и что сервер по ту сторону ведёт себя как обещано.
//! Он доказывает ровно одно, зато без пропусков: нового пути наружу мимо гейта в дереве нет.

use std::fs;
use std::path::{Path, PathBuf};

/// Три обращения, разрешённые в левом положении, — по ПУТИ файла-владельца (относительно
/// `src-tauri/src`) и слову, которым обращение названо человеку в подписи под переключателем.
///
/// 🔴 Путь, не имя файла (находка внешнего аудита, Medium, s41): список по голому имени
/// прощал бы любой файл с таким же именем в любой другой папке — `src/commands/x/updater.rs`
/// с чужим адресом проходил бы как «обновления» точно так же, как настоящий обновитель.
///
/// 🔴 Пара «путь → слово» связывает код с текстом на экране. Если появится четвёртый
/// разрешённый канал, его придётся и назвать человеку, и внести сюда — иначе подпись
/// начнёт врать умолчанием, а сторож промолчит.
const ALLOWED_INFRA: &[(&str, &str)] = &[
    ("commands/online_auth.rs", "лицензи"),
    ("commands/updater.rs", "обновлени"),
    ("commands/content_updater.rs", "докачка"),
];

/// Файлы (по пути относительно `src-tauri/src`), чей выход наружу закрыт гейтом левого
/// положения (ассистент и его окружение). Гейт для каждого из них ДОКАЗЫВАЕТСЯ структурно
/// тестом `gated_by_route_files_actually_gate_their_egress`, а не принимается на веру по
/// присутствию в этом списке.
const GATED_BY_ROUTE: &[&str] =
    &["commands/claude.rs", "commands/gateway_executor.rs", "commands/rag_client.rs"];

/// Файлы, где `reqwest::`/сырые сокеты встречаются ЛЕГИТИМНО и вопроса «куда уходят
/// материалы в левом положении» вообще не касаются — общение со СВОИМИ, локальными
/// sidecar-процессами продукта, строго на loopback. Проверено чтением исходников
/// 11.09.2026 (адресные константы у каждой строки).
///
/// 🔴 Список закрывает только сам факт присутствия сетевых СИМВОЛОВ (`raw_egress_symbols_...`
/// ниже) — НЕ отменяет обычный поиск литералов-адресов (выше), который проверяет эти же
/// файлы наравне со всеми: появись в любом из них НОВЫЙ внешний литерал-адрес, он будет
/// найден как обычно, этот список тут ни при чём.
const LOOPBACK_SIDECAR_FILES: &[&str] = &[
    // Brand Hub RAG-библиотека: RAG_BASE = "http://127.0.0.1:7420" — свой sidecar.
    "commands/brand.rs",
    // Parser sidecar: PARSER_BASE = "http://127.0.0.1:7421".
    "commands/parser.rs",
    // Эконометрика: econ_sidecar::base_url() строит "http://127.0.0.1:<port>".
    "commands/econometrica.rs",
    // Сам эконометрический sidecar — запуск/health/остановка, включая
    // `TcpStream::connect_timeout` на 127.0.0.1 (быстрая TCP-проверка живости).
    "econ_sidecar.rs",
    // Управление процессом sidecar'а (порт, health-проверки) — тоже loopback.
    "sidecar_runtime.rs",
];

/// Сырые сетевые символы — путь наружу МИМО литерала-адреса: адрес приходит
/// переменной/параметром, а не строкой в этом же файле, и поиск литералов его не
/// видит вовсе. Прямой сокет (`TcpStream::connect`/`UdpSocket::bind`) или обращение
/// к HTTP-клиенту (`reqwest::`/`ureq::`/`hyper::`) — само по себе повод назвать файл
/// человеку или доказать гейт, вне зависимости от того, нашёлся ли рядом литерал.
const RAW_EGRESS_SYMBOLS: &[&str] =
    &["TcpStream::connect", "UdpSocket::bind", "reqwest::", "ureq::", "hyper::"];

/// Обращение к своей же машине наружу не считается.
///
/// 🔴 Хост разбирается ТОЧНО, не подстрокой (находка внешнего аудита, Medium, s41):
/// `https://127.0.0.1.attacker.example` содержит «127.0.0.1» как подстроку, но ведёт на
/// чужой домен. Тот же разбор хоста, что и в `rag_client.rs::validate_rag_url` — два места,
/// решающие один и тот же вопрос «это моя машина?», обязаны решать его одинаково.
///
/// 🔴 Находка проверяющего-противника (11.09.2026): нарезка строки текстом (было —
/// `trim_start_matches` + `split(':')`) брала ПЕРВЫЙ сегмент адреса. На
/// `http://localhost:80@evil.example/x` первый сегмент — `localhost`, хотя настоящий
/// хост, на который пойдёт клиент, — то, что ПОСЛЕ `@` (`evil.example`): userinfo в
/// URL — это учётные данные ДЛЯ хоста, а не сам хост. Разбор — тем же разборщиком, что
/// и у клиента, который по этому адресу пойдёт (`reqwest::Url`, стандарт WHATWG), с
/// тем же условием, что теперь стоит в продукте (запись 4a685fa6): непустые имя или
/// пароль в адресе — сами по себе чужая машина, даже если хост после `@` похож на
/// loopback. `host_str()` для IPv6 loopback нормализует хост со скобками (`[::1]`) —
/// сравниваем с тем, что реально возвращает разборщик, а не с тем, что кажется логичным.
fn is_loopback(url: &str) -> bool {
    let substituted = substitute_format_placeholders(url);
    let Ok(parsed) = reqwest::Url::parse(&substituted) else {
        return false;
    };
    let no_credentials = parsed.username().is_empty() && parsed.password().is_none();
    let loopback = matches!(parsed.host_str(), Some("localhost" | "127.0.0.1" | "[::1]"));
    no_credentials && loopback
}

/// Заменить плейсхолдеры формат-строки (`{}`, `{port}` — Rust `format!`/`write!`) на
/// безопасную цифровую заглушку ДО разбора адреса разборщиком URL.
///
/// 🔴 Честная краснота на реальном дереве при первом прогоне этого пункта (11.09.2026):
/// литерал в исходнике зачастую ШАБЛОН, а не готовый адрес — `"http://127.0.0.1:{port}/health"`
/// (`econ_sidecar.rs`/`sidecar_runtime.rs`), порт подставляется в рантайме. `reqwest::Url::parse`
/// такой текст не разбирает вовсе (порт — не число), и честный loopback-шаблон становился
/// ложной находкой. Заглушка не подделывает безопасность: если плейсхолдер стоит В ПОРТУ (все
/// реальные случаи дерева), адрес становится разбираемым и хост остаётся собой (`127.0.0.1`).
/// Если бы плейсхолдер стоял В ХОСТЕ (`"http://{host}/x"`), заглушка даёт хост `0` — не
/// совпадающий ни с одним loopback-именем, находка осталась бы находкой.
fn substitute_format_placeholders(url: &str) -> String {
    let mut out = String::with_capacity(url.len());
    let mut chars = url.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '{' {
            if chars.peek() == Some(&'{') {
                // `{{` — экранированная фигурная скобка в format!, не плейсхолдер.
                out.push('{');
                chars.next();
                continue;
            }
            let mut closed = false;
            for inner in chars.by_ref() {
                if inner == '}' {
                    closed = true;
                    break;
                }
            }
            if closed {
                out.push('0');
                continue;
            }
            out.push('{');
            continue;
        }
        out.push(c);
    }
    out
}

/// Отбрасывает комментарии, СОХРАНЯЯ строковые литералы: адреса живут именно в них.
///
/// Проверяется собственным тестом ниже — сторож, чья разметка исходника не проверена,
/// молчит не потому, что всё хорошо, а потому, что смотрит не туда.
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
                    // Переводы строк сохраняются: номер строки в отказе обязан совпадать
                    // с номером строки в файле.
                    if chars[i] == '\n' {
                        out.push('\n');
                    }
                    i += 1;
                }
            }
            continue;
        }
        // 🔴 Находка проверяющего-противника (11.09.2026): сырые строки (`r"…"`,
        // `r#"…"#`, `br"…"`) кавычки внутри себя НЕ экранируют — `r"\\?\UNC\"`
        // (sidecar_runtime.rs) заканчивается на `\"`, и обычный разбор строки ниже
        // трактует это как ЭКРАНИРОВАННУЮ кавычку (раз перед ней `\`) и продолжает
        // искать «настоящую» закрывающую кавычку ДАЛЬШЕ, теряя синхронизацию на
        // сотни строк вниз — следующие честные адреса на этом пути либо пропадают,
        // либо обрезаются на середине. Сырую строку поглощаем целиком отдельно: по
        // числу `#` после `r`/`br`, затем до `"`, за которой идёт ровно столько же `#`.
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
            // Не сырая строка (обычный идентификатор, начинающийся на `r`/`b`) —
            // падаем в общий разбор ниже как одиночный символ.
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
        // 🔴 Находка внешнего аудита (Medium, s41): символьный литерал `'"'` открывал режим
        // строки на общих основаниях — одиночная кавычка проходила как обычный символ, а
        // следующая за ней двойная кавычка запускала разбор строки, и до следующей
        // НАСТОЯЩЕЙ двойной кавычки в файле комментарии не вырезались вовсе. Отличаем
        // литерал (`'"'`, `'\''`, `'\\'`, `'x'`) от времени жизни (`'a`, `'static`)
        // закрывающей кавычкой в пределах разумной длины тела литерала: у времени жизни
        // её нет никогда.
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

fn rust_files(dir: &Path, acc: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else { return };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            rust_files(&path, acc);
        } else if path.extension().and_then(|e| e.to_str()) == Some("rs") {
            acc.push(path);
        }
    }
}

fn src_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("src")
}

/// Путь файла относительно `src-tauri/src`, разделители нормализованы к `/` — Windows
/// отдаёт `\`, а список `ALLOWED_INFRA`/`GATED_BY_ROUTE` пишется один раз для всех платформ.
fn relative_path(path: &Path) -> String {
    path.strip_prefix(src_dir())
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}

/// Одно найденное обращение наружу: файл (путь относительно `src-tauri/src`), строка, адрес.
struct Egress {
    file: String,
    line: usize,
    url: String,
}

/// Байтовый диапазон тела функции — тот же приём поиска конца, что и `extract_fn` ниже:
/// закрывающая скобка в начале строки.
fn extract_fn_range(code: &str, signature: &str) -> Option<std::ops::Range<usize>> {
    let start = code.find(signature)?;
    let tail = &code[start..];
    let end = tail.find("\n}").map(|e| e + 2).unwrap_or(tail.len());
    Some(start..start + end)
}

/// Гейт/вызов внутри замыкания — НЕ оператор верхнего уровня тела функции:
/// замыкание исполняется, только когда его кто-то ЗОВЁТ, а объявить и ни разу не
/// позвать — законный Rust (`let _g = || { ensure_gateway_route(..)?; .. };`
/// компилируется и ничего не проверяет, пока `_g` не вызван). «Верхнего уровня»
/// здесь — эвристика: `{`, которой непосредственно (не считая пробелов)
/// предшествует `|` — ровно то, чем оканчивается сигнатура замыкания без явного
/// типа возврата (`|x, y|`, `move || `). Обычные блоки (`if`/`match`/
/// `#[cfg(..)] { .. }`) под эту эвристику не попадают и проходят как раньше.
/// Строковые и большинство символьных литералов пропускаются тем же приёмом, что и
/// `strip_comments`, — иначе фигурные скобки внутри формат-строки
/// (`"{cabinet_id}"`) сбили бы счёт вложенности.
///
/// 🔴 Чего не ловит: замыкание с явным типом возврата (`|x| -> T { .. }`) — символ
/// перед `{` там не `|`, а последний символ типа. В проверяемых файлах такой формы
/// нет (проверено 11.09.2026) — появись она, эвристика не сработает.
fn position_is_inside_closure(body: &str, pos: usize) -> bool {
    let bytes = body.as_bytes();
    let mut stack: Vec<bool> = Vec::new();
    let mut i = 0usize;
    while i < bytes.len() && i < pos {
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
                let mut k = i;
                let mut prev = None;
                while k > 0 {
                    k -= 1;
                    if !(bytes[k] as char).is_whitespace() {
                        prev = Some(bytes[k]);
                        break;
                    }
                }
                stack.push(prev == Some(b'|'));
                i += 1;
            }
            b'}' => {
                stack.pop();
                i += 1;
            }
            _ => {
                i += 1;
            }
        }
    }
    stack.iter().any(|&is_closure| is_closure)
}

/// Имена всех `pub fn`/`pub async fn` верхнего уровня в файле — ИЗ исходника, а не
/// переписанные руками: список на веру (двумя именами) не увидел бы новую pub fn,
/// появившуюся в файле позже (находка проверяющего-противника, 11.09.2026 —
/// `request_cancel` была именно такой, третьей, незамеченной pub fn).
fn pub_fn_names(code: &str) -> Vec<String> {
    let mut names = Vec::new();
    for prefix in ["pub fn ", "pub async fn "] {
        let mut search_from = 0usize;
        while let Some(rel) = code[search_from..].find(prefix) {
            let start = search_from + rel;
            let name_start = start + prefix.len();
            let name: String = code[name_start..]
                .chars()
                .take_while(|c| c.is_alphanumeric() || *c == '_')
                .collect();
            search_from = name_start + name.len().max(1);
            if !name.is_empty() {
                names.push(name);
            }
        }
    }
    names
}

/// Слово `word` встречается в `haystack` как ЦЕЛЫЙ идентификатор (границы — не
/// буква/цифра/`_` с обеих сторон). Та же проверка, что и в соседнем стороже
/// (`guard_assistant_route_single_path.rs::contains_word`) — обе копии решают один
/// и тот же вопрос «это отдельное слово или часть более длинного имени», обязаны
/// решать его одинаково.
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

/// Все `use`-выражения файла как текст от `use` до ближайшего `;` включительно.
fn use_statements(code: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut search_from = 0usize;
    while let Some(rel) = code[search_from..].find("use ") {
        let start = search_from + rel;
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

/// Если `stmt` импортирует `item` (голым именем, в {..}, с `as`), вернуть под каким
/// именем `item` дальше упоминается в файле: `Some(alias)`, если переименован через
/// `as`, иначе `Some(item.to_string())` (без переименования — искать в коде нужно
/// само имя, уже покрыто прямым текстовым маркером `{item}(` снаружи). `None` —
/// `item` в этом `use`-выражении не импортирован вовсе.
///
/// 🔴 Находка проверяющего-противника (11.09.2026): `use
/// ...gateway_executor::run_claude_gateway as go; let _ = go;` — прямой текстовый
/// маркер `run_claude_gateway(` этого не видит, функция дальше упоминается уже под
/// именем `go`.
fn imported_item_alias(stmt: &str, item: &str) -> Option<String> {
    if !contains_word(stmt, item) {
        return None;
    }
    let h: Vec<char> = stmt.chars().collect();
    let it: Vec<char> = item.chars().collect();
    let is_ident = |c: char| c.is_alphanumeric() || c == '_';
    'outer: for start in 0..=(h.len().saturating_sub(it.len())) {
        for (k, ic) in it.iter().enumerate() {
            if h[start + k] != *ic {
                continue 'outer;
            }
        }
        let before_ok = start == 0 || !is_ident(h[start - 1]);
        let after_idx = start + it.len();
        if !before_ok || (after_idx < h.len() && is_ident(h[after_idx])) {
            continue;
        }
        let rest: String = h[after_idx..].iter().collect();
        let rest_trimmed = rest.trim_start();
        if let Some(tail) = rest_trimmed.strip_prefix("as ") {
            let alias: String = tail.trim_start().chars().take_while(|c| is_ident(*c)).collect();
            if !alias.is_empty() {
                return Some(alias);
            }
        }
        return Some(item.to_string());
    }
    None
}

/// Каждый строковый литерал на строке: позиция открывающей кавычки (для точной
/// привязки к диапазону карв-аута — та же позиция, что раньше давал поиск маркера) и
/// содержимое без внешних кавычек.
///
/// 🔴 Находка проверяющего-противника (11.09.2026): прежний поиск ловил находку,
/// только если литерал НАЧИНАЛСЯ буквально с `"https://`/`"http://`. Адрес, собранный
/// по кускам (`concat!("ht", "tps://evil.example/x")`, `format!("{s}://{h}", s =
/// "https", ..)`, `["https", "://", host].concat()`), невидим такому поиску: ни один
/// отдельный литерал не начинается с полной схемы. Разбор теперь достаёт ВСЕ
/// литералы строки — классификация (`classify_literal`) решает за каждый отдельно.
fn string_literals_on_line(line: &str) -> Vec<(usize, String)> {
    let mut out = Vec::new();
    let bytes = line.as_bytes();
    let mut i = 0usize;
    while i < bytes.len() {
        if bytes[i] == b'"' {
            let quote_pos = i;
            let content_start = i + 1;
            let mut j = content_start;
            loop {
                if j >= bytes.len() {
                    break;
                }
                if bytes[j] == b'\\' {
                    j += 2;
                    continue;
                }
                if bytes[j] == b'"' {
                    break;
                }
                j += 1;
            }
            let content_end = j.min(line.len());
            out.push((quote_pos, line[content_start..content_end].to_string()));
            i = content_end + 1;
            continue;
        }
        i += 1;
    }
    out
}

/// Три взаимоисключающие формы литерала, каждая — сама по себе находка, требующая
/// объяснения (запись в `ALLOWED_INFRA`/`GATED_BY_ROUTE` или карв-аут):
///  - **полная схема** (`https://host…`) — обычный адрес целиком в одном литерале;
///  - **осколок** (содержит `://` не с начала строки) — адрес, собранный по кускам
///    (см. докстрок `string_literals_on_line`) — сам кусок несёт хвост схемы и
///    начало хоста, а не схему целиком, поэтому не «полная схема»;
///  - **голая схема-константа** (равна целиком `http`/`https` или оканчивается на
///    `http:`/`https:`) — строительный блок (`const SCHEME: &str = "https"`,
///    `String::from("https:")`, элемент `["https", "://", host].concat()`).
///
/// 🔴 Регистронезависимо (находка проверяющего-противника: `"HTTPS://evil…"`) и по
/// содержимому БЕЗ ведущих пробелов (находка: `" https://evil…"` — ведущий пробел не
/// делает адрес менее адресом, а прежний текстовый поиск маркера `"https://` такой
/// литерал не находил вовсе, поскольку кавычка стояла не перед самой схемой).
enum LiteralShape {
    FullScheme,
    Fragment,
    BareScheme,
}

/// `://` где-то в литерале — осколок, ТОЛЬКО если сразу за ним стоит непробельный
/// символ (похоже на начало хоста), а не в любом месте.
///
/// 🔴 Честная краснота на реальном дереве при первом прогоне этого пункта
/// (11.09.2026): человеческий текст, поясняющий формат адреса
/// (`lib.rs: "Invalid URL: must start with http:// or https://".to_string()`),
/// содержит «://» ДВАЖДЫ, но оба раза — перед пробелом («…http:// or…») или
/// концом строки («…https://»), никакого хоста рядом нет вообще. Настоящий
/// осколок адреса (`concat!("ht", "tps://evil.example/x")` даёт литерал
/// `"tps://evil.example/x"`) — сразу за «://» идёт хост, без пробела.
fn contains_address_like_fragment(lower: &str) -> bool {
    let bytes = lower.as_bytes();
    let mut search_from = 0usize;
    while let Some(rel) = lower[search_from..].find("://") {
        let pos = search_from + rel;
        let after = pos + 3;
        if after < bytes.len() && !(bytes[after] as char).is_whitespace() {
            return true;
        }
        search_from = pos + 3;
    }
    false
}

fn classify_literal(content: &str) -> Option<LiteralShape> {
    let trimmed = content.trim_start();
    let lower = trimmed.to_ascii_lowercase();
    if lower.starts_with("https://") || lower.starts_with("http://") {
        return Some(LiteralShape::FullScheme);
    }
    // 🔴 Точечное исключение (честная краснота на реальном дереве при первой
    // реализации этого пункта, 11.09.2026): `aurora://` — своя, зарегистрированная
    // Tauri-схема для отдачи ЛОКАЛЬНЫХ файлов фронтенда из `%LOCALAPPDATA%`
    // (`lib.rs::handle_aurora_protocol`), сети не касается вовсе — не осколок
    // сетевого адреса, а целиком другой, не сетевой протокол. Исключение узкое:
    // если бы в ТОМ ЖЕ литерале рядом нашёлся настоящий `http(s)://`, находка
    // осталась бы (проверяем оба варианта отдельно, не просто «содержит aurora»).
    if lower.contains("aurora://") && !lower.contains("http://") && !lower.contains("https://") {
        return None;
    }
    if contains_address_like_fragment(&lower) {
        return Some(LiteralShape::Fragment);
    }
    // 🔴 РЕГИСТРОЗАВИСИМО нарочно, в отличие от полной схемы выше: голый токен
    // «HTTP» (без «:», без «//») в проверяемом дереве — честный литерал, не имеющий
    // отношения к строительству адреса (lib.rs, тест на отсутствие технического
    // кода в клиентском тексте — сверяет ОТСУТСТВИЕ подстроки «HTTP» в сообщении
    // об отказе). Все показанные проверяющим-противником приёмы строительства
    // схемы-константы (`const SCHEME: &str = "https"`, `String::from("https:")`,
    // элемент `["https", "://", h].concat()`) пишут схему строчными буквами — так
    // пишут в реальном Rust-коде. Регистр здесь — осознанное сужение, проверенное
    // на честном дереве, а не молчаливое прощение: полная схема (с «//») и осколок
    // («://», за которым видно начало хоста) выше по-прежнему ловятся без учёта регистра.
    if trimmed == "http" || trimmed == "https" || trimmed.ends_with("http:") || trimmed.ends_with("https:") {
        return Some(LiteralShape::BareScheme);
    }
    None
}

/// Найти в исходниках ВСЕ обращения наружу: адрес (целиком, осколком или голой
/// схемой) в строковом литерале, плюс прямое обращение к сетевому клиенту/сокету
/// мимо любого литерала (`RAW_EGRESS_SYMBOLS`).
///
/// 🔴 Голая схема («https://» без продолжения) сама по себе не запись: строку теми же
/// двумя символами открывает и сборка адреса через `format!("{}{}", "https://",
/// host)`. Прощается ТОЛЬКО в одном названном месте — `lib.rs::add_url_to_inbox`, где
/// она действительно не обращение, а приставка для разбора ссылки, которую человек
/// кладёт в «Входящие» (там только пишется .url-файл, сети нет; проверено приёмкой
/// 11.09.2026). Везде в остальном коде голая схема (как и осколок, и голая
/// схема-константа) идёт в общий список находок.
///
/// Чего этот способ НЕ делает: не проверяет, что рядом с адресом живёт сетевой клиент
/// (для литералов), и не вычисляет символьное значение произвольной конкатенации
/// (осколок ловится, только если САМ по себе содержит `://` или равен схеме — сборка
/// хоста посимвольно из кусков без единого такого куска этим приёмом не ловится:
/// это потребовало бы частичного исполнения макросов, разбор текста столько не
/// доказывает). Признак «клиент рядом» дал бы пропуски и для литералов — адрес-
/// константа нередко стоит вверху файла, а вызов ниже. Поэтому берём шире: любой
/// адрес/осколок/схема с любой стороны требует объяснения.
fn discover_egress() -> Vec<Egress> {
    let mut files = Vec::new();
    rust_files(&src_dir(), &mut files);
    let mut found = Vec::new();
    for path in files {
        let Ok(raw) = fs::read_to_string(&path) else { continue };
        let code = strip_comments(&raw);
        let name = relative_path(&path);

        // Диапазон байт тела единственной функции, где голая схема — не обращение.
        let bare_scheme_carve_out =
            if name == "lib.rs" { extract_fn_range(&code, "fn add_url_to_inbox(") } else { None };
        let loopback_sidecar = LOOPBACK_SIDECAR_FILES.contains(&name.as_str());

        // 🔴 `code.lines()` съедает и `\n`, и (при CRLF) предшествующий `\r`, но по-разному
        // считает их длину в байтах — файлы этого дерева смешивают окончания строк
        // (`lib.rs` целиком CRLF). Ручной счётчик `+1` за строку молча съезжает на один
        // байт на КАЖДОЙ CRLF-строке, и к 1700-й строке смещение расходится с реальным
        // почти на два килобайта — карв-аут переставал совпадать со своим же диапазоном.
        // `split_inclusive('\n')` возвращает окончание строки в составе среза, так что
        // его байтовая длина всегда точна вне зависимости от переноса.
        let mut offset = 0usize;
        for (idx, raw_line) in code.split_inclusive('\n').enumerate() {
            let line_start = offset;
            offset += raw_line.len();
            let line = raw_line.strip_suffix('\n').unwrap_or(raw_line);
            let line = line.strip_suffix('\r').unwrap_or(line);

            for (pos, content) in string_literals_on_line(line) {
                let Some(shape) = classify_literal(&content) else { continue };
                let trimmed = content.trim_start().to_string();
                if matches!(shape, LiteralShape::FullScheme) {
                    if is_loopback(&trimmed) {
                        continue;
                    }
                    let lower = trimmed.to_ascii_lowercase();
                    let host =
                        lower.trim_start_matches("https://").trim_start_matches("http://");
                    if host.is_empty() {
                        let in_carve_out = bare_scheme_carve_out
                            .as_ref()
                            .map(|r| r.contains(&(line_start + pos)))
                            .unwrap_or(false);
                        if in_carve_out {
                            continue;
                        }
                    }
                }
                // Осколок и голая схема-константа не проверяются на loopback/карв-аут:
                // хоста в них либо нет вовсе, либо не видно, откуда он собирается —
                // безопаснее считать находкой, чем угадывать безопасность.
                found.push(Egress { file: name.clone(), line: idx + 1, url: trimmed });
            }

            // 🔴 Прямой сокет/HTTP-клиент мимо литерала-адреса (зонд
            // проверяющего-противника: `std::net::TcpStream::connect("evil…")`) —
            // поиск литералов его не видит, если адрес приходит переменной. Файлы,
            // где это легитимно (loopback к своим sidecar-процессам), исключены
            // точечно — см. `LOOPBACK_SIDECAR_FILES`.
            if !loopback_sidecar {
                for marker in RAW_EGRESS_SYMBOLS {
                    if line.contains(marker) {
                        found.push(Egress {
                            file: name.clone(),
                            line: idx + 1,
                            url: format!("сырой сетевой символ: {marker}"),
                        });
                    }
                }
            }
        }
    }
    found
}

/// 🔴 Главная проверка: ни одного обращения наружу мимо трёх названных и мимо гейта.
#[test]
fn no_egress_beyond_the_three_named_and_the_gated_assistant() {
    let egress = discover_egress();
    assert!(
        !egress.is_empty(),
        "поиск обращений наружу не нашёл ничего — сторож смотрит не туда и молчал бы всегда",
    );

    let known: Vec<&str> = ALLOWED_INFRA
        .iter()
        .map(|(f, _)| *f)
        .chain(GATED_BY_ROUTE.iter().copied())
        .collect();

    let strays: Vec<String> = egress
        .iter()
        .filter(|e| !known.contains(&e.file.as_str()))
        .map(|e| format!("{}:{} → {}", e.file, e.line, e.url))
        .collect();

    assert!(
        strays.is_empty(),
        "найден путь наружу, который не назван человеку в подписи под переключателем и не \
         закрыт гейтом левого положения:\n  {}\n\nЛибо закройте его гейтом (как ассистента), \
         либо внесите в ALLOWED_INFRA и НАЗОВИТЕ в HEADLINE_LOCAL — подпись, умалчивающая об \
         обращении, врёт человеку о судьбе его материалов.",
        strays.join("\n  "),
    );
}

/// Каждое из трёх разрешённых обращений действительно живёт в исходниках и названо в подписи.
///
/// Проверка двусторонняя нарочно: список без кода — мёртвая буква, код без имени в подписи —
/// умолчание. Ошибка в любую сторону здесь стоит доверия к единственному тексту программы,
/// отвечающему на вопрос «уходят ли мои данные».
#[test]
fn all_three_allowed_calls_exist_in_sources_and_are_named_to_the_person() {
    let egress = discover_egress();
    let headline = read_headline_local();
    for (file, word) in ALLOWED_INFRA {
        assert!(
            egress.iter().any(|e| e.file == *file),
            "разрешённое обращение из {file} в исходниках не найдено — список разошёлся с кодом",
        );
        assert!(
            headline.contains(word),
            "подпись левого положения не называет обращение из {file} (искали «{word}»): {headline}",
        );
    }
}

/// Гейт левого положения стоит в единственной точке входа ассистента и включает обе проверки.
///
/// Мутация, которую обязан ловить этот тест: убрать `ensure_not_local_only` из
/// `ensure_gateway_route` — то есть пропустить материалы наружу в левом положении.
#[test]
fn the_gate_of_the_left_position_is_in_place() {
    let claude = fs::read_to_string(src_dir().join("commands").join("claude.rs"))
        .expect("claude.rs обязан читаться");
    let code = strip_comments(&claude);

    let gate = extract_fn(&code, "fn ensure_gateway_route(")
        .expect("гейт маршрута ассистента обязан существовать в claude.rs");
    assert!(
        gate.contains("ensure_not_local_only"),
        "гейт обязан проверять левое положение переключателя: {gate}",
    );
    assert!(
        gate.contains("ensure_cloud_consent"),
        "гейт обязан проверять согласие — оно часть выбора режима: {gate}",
    );

    // Обе точки входа ассистента закрыты одним и тем же гейтом.
    for entry in ["pub async fn run_claude(", "pub async fn run_claude_pipeline("] {
        let body = extract_fn(&code, entry).unwrap_or_else(|| panic!("{entry} обязана существовать"));
        assert!(
            body.contains("ensure_gateway_route(&app_handle)?"),
            "{entry} обязана начинаться с гейта маршрута",
        );
    }

    // Гейт левого положения читает ту же ось, что и переключатель.
    let user_config = fs::read_to_string(src_dir().join("commands").join("user_config.rs"))
        .expect("user_config.rs обязан читаться");
    assert!(
        strip_comments(&user_config).contains("pub fn stored_local_only("),
        "ось левого положения обязана выводиться одной функцией — иначе перенос прежних \
         настроек разойдётся с гейтом",
    );
}

/// 🔴 `GATED_BY_ROUTE` больше не список на веру (находка внешнего аудита, High, s41):
/// прежде он объявлял `gateway_executor.rs` и `rag_client.rs` закрытыми гейтом, и НИ ОДНА
/// проверка этого не доказывала — новый egress из `rag_client.rs` без единой строки гейта
/// прошёл бы точно так же, как проверенный файл. Для каждого файла из списка, у которого
/// вообще нашлось обращение наружу, тест доказывает структурно, ГДЕ именно стоит гейт.
///
/// Разные файлы гейтуются по-разному, и это доказывается по-разному:
/// - `rag_client.rs` — гейт ВНУТРИ единственной команды (`econ_rag_search` сама зовёт
///   `ensure_not_local_only`/`ensure_cloud_consent` до обращения);
/// - `gateway_executor.rs` — гейт СНАРУЖИ: обращение живёт в исполнителях
///   (`run_claude_gateway`/`run_claude_pipeline_gateway`), а они зовутся только из
///   `claude.rs`, после `ensure_gateway_route` в теле той же функции (уже проверено
///   отдельным тестом выше — здесь проверяется, что вызывает исполнителей ТОЛЬКО claude.rs
///   и что вызов стоит именно ПОСЛЕ гейта, а не до него);
/// - `claude.rs` — свой собственный гейт, тот же `ensure_gateway_route`.
///
/// Мутация, которую обязан ловить этот тест: звать `run_claude_gateway`/
/// `run_claude_pipeline_gateway` из нового места в обход `claude.rs`, либо переставить
/// вызов исполнителя ПЕРЕД `ensure_gateway_route` в `run_claude`/`run_claude_pipeline`.
#[test]
fn gated_by_route_files_actually_gate_their_egress() {
    let egress = discover_egress();
    let gated_files_with_egress: Vec<&str> = GATED_BY_ROUTE
        .iter()
        .copied()
        .filter(|f| egress.iter().any(|e| e.file == *f))
        .collect();

    for file in gated_files_with_egress {
        match file {
            "commands/rag_client.rs" => {
                let src = fs::read_to_string(src_dir().join("commands").join("rag_client.rs"))
                    .expect("rag_client.rs обязан читаться");
                let code = strip_comments(&src);
                let body = extract_fn(&code, "pub async fn econ_rag_search(")
                    .expect("единственная точка входа библиотеки методологии обязана существовать");
                // 🔴 Порядок «гейт до обращения» и «гейт не в замыкании» — находки
                // проверяющего-противника (11.09.2026): прежде проверялось только
                // ПРИСУТСТВИЕ обеих проверок где-то в теле, не их позиция и не то,
                // исполняются ли они безусловно. Первое реальное обращение наружу в
                // этой функции — построение HTTP-клиента (`reqwest::`).
                let egress_pos = body.find("reqwest::");
                for gate in ["ensure_not_local_only(", "ensure_cloud_consent("] {
                    let gate_pos = body.find(gate).unwrap_or_else(|| {
                        panic!("econ_rag_search обязана проверять {gate} ДО обращения наружу: {body}")
                    });
                    assert!(
                        !position_is_inside_closure(&body, gate_pos),
                        "econ_rag_search: {gate} стоит внутри замыкания — замыкание можно \
                         объявить и ни разу не вызвать, гейт исполнится, только если его \
                         позвать: {body}",
                    );
                    if let Some(egress_pos) = egress_pos {
                        assert!(
                            gate_pos < egress_pos,
                            "econ_rag_search: {gate} стоит ПОСЛЕ обращения наружу (reqwest::), \
                             а не до него: {body}",
                        );
                    }
                }
            }
            "commands/gateway_executor.rs" => {
                let gw_src = fs::read_to_string(src_dir().join("commands").join("gateway_executor.rs"))
                    .expect("gateway_executor.rs обязан читаться");
                let gw_code = strip_comments(&gw_src);

                // 🔴 Список pub fn БОЛЬШЕ НЕ на веру двумя именами (находка
                // проверяющего-противника, 11.09.2026): прежде проверялись только
                // `run_claude_gateway`/`run_claude_pipeline_gateway`, а `request_cancel` —
                // тоже pub fn этого файла с обращением наружу (отмена задания на
                // сервере) — вызывался из `lib.rs` мимо этой проверки вовсе. Имена
                // достаются ИЗ исходника (`pub_fn_names`), не переписываются руками —
                // новая pub fn без записи здесь паникует явным текстом, а не молчит.
                //
                // Разрешённые вызывающие — по факту кода, с причиной:
                //  - `run_claude_gateway`/`run_claude_pipeline_gateway`: только
                //    claude.rs, ПОСЛЕ `ensure_gateway_route` в теле той же функции
                //    (проверяется ниже, звено «б»).
                //  - `request_cancel`: только lib.rs (кнопка «Остановить» в интерфейсе).
                //    ЗАКОННЫЙ вызов вне claude.rs — отменяет задание, которое УЖЕ
                //    прошло гейт при старте (номера задания не было бы иначе — тело
                //    функции делает ранний `return false`, если очередь заданий
                //    пуста), новую работу сама не заводит и новый гейт не открывает:
                //    завершение уже разрешённой работы, не обход гейта.
                let allowed_callers: &[(&str, &[&str])] = &[
                    ("run_claude_gateway", &["commands/claude.rs"]),
                    ("run_claude_pipeline_gateway", &["commands/claude.rs"]),
                    ("request_cancel", &["lib.rs"]),
                ];
                let mut files = Vec::new();
                rust_files(&src_dir(), &mut files);
                for fn_name in pub_fn_names(&gw_code) {
                    let Some((_, callers)) =
                        allowed_callers.iter().find(|(n, _)| *n == fn_name)
                    else {
                        panic!(
                            "«{fn_name}» — новая pub fn в gateway_executor.rs без структурного \
                             доказательства гейта в этом стороже. Добавьте её в \
                             `allowed_callers` (и разбор, если вызывающих несколько) или \
                             объясните здесь, почему проверять не нужно.",
                        );
                    };
                    let marker = format!("{fn_name}(");
                    for path in &files {
                        let name = relative_path(path);
                        if name == "commands/gateway_executor.rs" {
                            continue; // своё определение — не вызов
                        }
                        let Ok(raw) = fs::read_to_string(path) else { continue };
                        let code = strip_comments(&raw);
                        let mut mentioned = code.contains(&marker);
                        // 🔴 Находка проверяющего-противника (11.09.2026): `use
                        // ...gateway_executor::run_claude_gateway as go; let _ = go;` —
                        // прямой маркер `{fn_name}(` этого не видит, имя дальше
                        // упоминается уже под другим словом.
                        if !mentioned {
                            for stmt in use_statements(&code) {
                                if !contains_word(&stmt, "gateway_executor") {
                                    continue;
                                }
                                if let Some(alias) = imported_item_alias(&stmt, &fn_name) {
                                    if alias != fn_name && contains_word(&code, &alias) {
                                        mentioned = true;
                                    }
                                }
                            }
                        }
                        if mentioned {
                            assert!(
                                callers.contains(&name.as_str()),
                                "«{fn_name}» вызывается (в т.ч. через псевдоним импорта) из \
                                 {name} — не в списке разрешённых вызывающих ({callers:?}) для \
                                 этой pub fn gateway_executor.rs",
                            );
                        }
                    }
                }

                // Звено (б): в claude.rs вызов исполнителя стоит ПОСЛЕ ensure_gateway_route
                // в теле той же функции (не до него) и гейт — не внутри замыкания
                // (находка проверяющего-противника: `let _g = || { ensure_gateway_route(..)?;
                // .. };` — замыкание объявлено, но никогда не вызвано, а старая проверка
                // сравнивала только текстовые позиции, не «исполнится ли это безусловно»).
                let claude_src = fs::read_to_string(src_dir().join("commands").join("claude.rs"))
                    .expect("claude.rs обязан читаться");
                let claude_code = strip_comments(&claude_src);
                let executor_entry_points = ["run_claude_gateway(", "run_claude_pipeline_gateway("];
                for entry_fn in ["pub async fn run_claude(", "pub async fn run_claude_pipeline("] {
                    let body = extract_fn(&claude_code, entry_fn)
                        .unwrap_or_else(|| panic!("{entry_fn} обязана существовать"));
                    for entry in executor_entry_points {
                        let Some(call_pos) = body.find(entry) else { continue };
                        let gate_pos = body.find("ensure_gateway_route(").unwrap_or_else(|| {
                            panic!(
                                "{entry_fn}: зовёт {entry}, но ensure_gateway_route в теле не \
                                 найден — обращение наружу без гейта",
                            )
                        });
                        assert!(
                            gate_pos < call_pos,
                            "{entry_fn}: {entry} вызывается до ensure_gateway_route — гейт \
                             стоит после обращения, а не перед ним",
                        );
                        assert!(
                            !position_is_inside_closure(&body, gate_pos),
                            "{entry_fn}: ensure_gateway_route стоит внутри замыкания — \
                             замыкание можно объявить и ни разу не вызвать: {body}",
                        );
                    }
                }
            }
            "commands/claude.rs" => {
                // Свой гейт — тот же ensure_gateway_route, уже проверен
                // `the_gate_of_the_left_position_is_in_place`.
            }
            other => panic!(
                "«{other}» в GATED_BY_ROUTE, но для него нет структурного доказательства \
                 гейта в этом сторожe — добавьте разбор ветки в этом тесте или уберите файл \
                 из списка (тогда его обращения обязаны попасть в ALLOWED_INFRA).",
            ),
        }
    }
}

/// 🔴 Регрессия для звена (б) проверки выше: гейт `ensure_gateway_route` обязан стоять
/// В ТЕЛЕ функции ПЕРЕД вызовом исполнителя шлюза, а не после. Проверено на синтетическом
/// тексте, а не на реальном `claude.rs` (реальный файл — общая с коллегой часть дерева,
/// его переупорядочивание для мутационной проверки рискованно) — та же сравнивающая
/// позиции логика, что и в `gated_by_route_files_actually_gate_their_egress`.
///
/// Мутация, которую этот тест ловит без правки продукта: гейт переставлен ПОСЛЕ вызова
/// исполнителя в теле функции — ровно то, что случилось бы, если бы кто-то в `claude.rs`
/// переставил `ensure_gateway_route(&app_handle)?;` за блок с `run_claude_gateway`.
#[test]
fn gate_before_call_ordering_check_catches_reversed_order() {
    let gated_body = "pub async fn run_claude() {\n    ensure_gateway_route(&app_handle)?;\n    run_claude_gateway(a, b);\n}";
    let gate_pos = gated_body.find("ensure_gateway_route(").expect("гейт обязан найтись");
    let call_pos = gated_body.find("run_claude_gateway(").expect("вызов обязан найтись");
    assert!(gate_pos < call_pos, "в честном теле гейт обязан идти раньше вызова");

    let reversed_body = "pub async fn run_claude() {\n    run_claude_gateway(a, b);\n    ensure_gateway_route(&app_handle)?;\n}";
    let gate_pos = reversed_body.find("ensure_gateway_route(").expect("гейт обязан найтись");
    let call_pos = reversed_body.find("run_claude_gateway(").expect("вызов обязан найтись");
    assert!(
        !(gate_pos < call_pos),
        "мутация обязана дать gate_pos > call_pos — иначе проверка порядка в \
         gated_by_route_files_actually_gate_their_egress ничего не доказывает",
    );
}

/// Подпись левого положения — из исходника продукта, не из копии в тесте.
fn read_headline_local() -> String {
    let src = fs::read_to_string(src_dir().join("commands").join("execution_mode.rs"))
        .expect("execution_mode.rs обязан читаться");
    let code = strip_comments(&src);
    let start = code.find("pub const HEADLINE_LOCAL").expect("подпись обязана существовать");
    let tail = &code[start..];
    let end = tail.find(';').expect("объявление подписи обязано заканчиваться");
    tail[..end].to_string()
}

/// Вырезать тело функции: от заголовка до закрывающей скобки в начале строки.
fn extract_fn(code: &str, signature: &str) -> Option<String> {
    let start = code.find(signature)?;
    let tail = &code[start..];
    let end = tail.find("\n}").map(|e| e + 2).unwrap_or(tail.len());
    Some(tail[..end].to_string())
}

/// Разметка исходника проверяется сама: сторож, читающий комментарии как код (или
/// теряющий строковые литералы), молчал бы не потому, что всё хорошо.
#[test]
fn comment_stripper_keeps_strings_and_drops_comments() {
    let sample = "let a = \"https://real.example\"; // \"https://in-comment.example\"\n\
                  /* \"https://in-block.example\" */ let b = 1;\n";
    let out = strip_comments(sample);
    assert!(out.contains("https://real.example"), "адрес в коде обязан уцелеть: {out}");
    assert!(!out.contains("in-comment.example"), "адрес из комментария обязан исчезнуть: {out}");
    assert!(!out.contains("in-block.example"), "адрес из блока обязан исчезнуть: {out}");
}

/// Символьный литерал с кавычкой внутри не имеет права выключить вырезание комментариев
/// на остаток строки (находка внешнего аудита, Medium, s41).
#[test]
fn comment_stripper_handles_char_literals_not_string_mode() {
    // Комментарий БЕЗ кавычек вокруг адреса нарочно (обычный стиль: `// см. https://…`):
    // после единственного символьного литерала `'"'` старая реализация видела в его
    // кавычке открытие строки и не находила ни одной кавычки до конца входа — весь
    // остаток, включая настоящий адрес, уходил в вывод как «содержимое строки».
    let sample = "let q = '\"'; // см. https://in-comment.example\n";
    let out = strip_comments(sample);
    assert!(
        !out.contains("in-comment.example"),
        "адрес в комментарии ПОСЛЕ символьного литерала обязан исчезнуть так же, как без \
         него: {out}",
    );
}

/// Сырая строка с нечётным числом кавычек внутри не сбивает разбор остатка файла —
/// находка проверяющего-противника (11.09.2026).
#[test]
fn comment_stripper_handles_raw_strings_with_odd_inner_quotes() {
    let sample = "const T: &str = r#\"say \"hi\n\"#;\nconst U: &str = \"https://real.example\";\n";
    let out = strip_comments(sample);
    assert!(
        out.contains("https://real.example"),
        "адрес ПОСЛЕ сырой строки с нечётным числом кавычек не имеет права исчезнуть: {out}",
    );
}

/// 🔴 Реальный случай из дерева (sidecar_runtime.rs): сырая строка `r"\\?\UNC\"`
/// заканчивается на `\"` — обычный разбор строки трактует это как ЭКРАНИРОВАННУЮ
/// кавычку (раз перед ней бэкслэш) и продолжает искать закрывающую кавычку дальше,
/// теряя синхронизацию до конца файла. Честный адрес после такой строки обязан
/// остаться на месте.
#[test]
fn comment_stripper_handles_raw_string_ending_in_backslash_quote() {
    let sample = "let x = r\"\\\\?\\UNC\\\";\nconst U: &str = \"https://real.example\";\n";
    let out = strip_comments(sample);
    assert!(
        out.contains("https://real.example"),
        "адрес ПОСЛЕ r\"...\\\" (сырая строка, заканчивающаяся на бэкслэш-кавычку) не имеет \
         права исчезнуть: {out}",
    );
}

/// `is_loopback` разбирает хост точно, а не подстрокой.
///
/// 🔴 Входы теперь ПОЛНЫЕ адреса со схемой — `reqwest::Url::parse` требует абсолютный
/// URL, а не голый `хост:порт`. Это точно совпадает с тем, что реально приходит из
/// `discover_egress` (литерал захватывается вместе со схемой, начиная с маркера
/// `"https://`/`"http://`) — старые входы без схемы в тесте проверяли не тот случай,
/// который встречается в бою.
#[test]
fn is_loopback_matches_host_exactly_not_by_substring() {
    assert!(is_loopback("https://127.0.0.1:8801/search"), "обычный loopback с портом");
    assert!(is_loopback("https://localhost:8801"), "loopback по имени");
    assert!(
        !is_loopback("https://127.0.0.1.attacker.example/search"),
        "хост «127.0.0.1.attacker.example» — чужой домен, содержащий loopback подстрокой",
    );
    assert!(
        !is_loopback("https://evil-localhost.example"),
        "хост «evil-localhost.example» — чужой домен, содержащий «localhost» подстрокой",
    );
}

/// 🔴 Находка проверяющего-противника (11.09.2026): userinfo в адресе
/// (`localhost:80@evil.example`) — учётные данные ДЛЯ хоста ПОСЛЕ `@`, не сам хост.
/// Старая текстовая нарезка брала первый сегмент до `@`/`:` и видела «localhost»,
/// пропуская обращение к чужой машине как «свою». `reqwest::Url` разбирает и `username`,
/// и `password`, и `host_str()` — непустые учётные данные обязаны сами по себе решать
/// «это НЕ своя машина», независимо от того, что стоит в поле хоста.
#[test]
fn is_loopback_rejects_userinfo_smuggling_a_foreign_host() {
    assert!(
        !is_loopback("http://localhost:80@evil.example/x"),
        "«localhost» здесь — имя пользователя перед @, настоящий хост — evil.example",
    );
    assert!(
        !is_loopback("http://[::1]@evil.example/x"),
        "«[::1]» здесь — имя пользователя перед @, настоящий хост — evil.example",
    );
    // Контроль: настоящий loopback без userinfo остаётся собой.
    assert!(is_loopback("http://127.0.0.1:8801/x"), "loopback без userinfo — своя машина");
}

/// 🔴 Честная краснота на реальном дереве при первом прогоне пункта 5 (11.09.2026):
/// литерал в исходнике зачастую ШАБЛОН `format!()`, а не готовый адрес
/// (`"http://127.0.0.1:{port}/health"`, `econ_sidecar.rs`/`sidecar_runtime.rs`) —
/// порт подставляется в рантайме, и `reqwest::Url::parse` такой текст без
/// подстановки не разбирал бы вовсе. Плейсхолдер В ПОРТУ не должен ломать
/// распознавание loopback; плейсхолдер В ХОСТЕ — не должен его подделывать.
#[test]
fn is_loopback_tolerates_format_placeholders_in_port_but_not_in_host() {
    assert!(
        is_loopback("http://127.0.0.1:{port}/health"),
        "шаблон с плейсхолдером в порту — честный loopback, порт подставится в рантайме",
    );
    assert!(is_loopback("http://127.0.0.1:{}/health"), "то же с безымянным плейсхолдером {{}}");
    assert!(
        !is_loopback("http://{host}/x"),
        "плейсхолдер В ХОСТЕ не подделывает loopback — заглушка «0» не совпадает ни с одним \
         loopback-именем",
    );
}

/// 🔴 Честная краснота на реальном дереве при первом прогоне пункта 4 (11.09.2026):
/// человеческий текст, поясняющий формат адреса (`lib.rs`), содержит «://» дважды,
/// но оба раза — перед пробелом или концом строки, хоста рядом нет вовсе. Не
/// осколок собранного по кускам адреса.
#[test]
fn classify_literal_does_not_flag_prose_mentioning_a_scheme_name() {
    assert!(
        classify_literal("Invalid URL: must start with http:// or https://").is_none(),
        "поясняющий текст про формат адреса — не находка, хоста рядом с «://» нет",
    );
}

/// 🔴 Регрессия найдена этим же батчем правок (11.09.2026): `lib.rs` целиком в CRLF, и
/// подсчёт смещения строки «+1 байт за перевод» на нём расходится с реальным — CRLF-строка
/// на байт длиннее LF-строки, и к 1700-й строке файла расхождение доходит почти до
/// килобайта. Из-за этого карв-аут «голая схема разрешена только внутри
/// `add_url_to_inbox`» переставал совпадать со своим собственным диапазоном, и сторож
/// падал на честном, не мутированном дереве. Подсчёт через `split_inclusive('\n')`
/// (как в `discover_egress`) обязан давать точное смещение независимо от переноса строки.
#[test]
fn line_offsets_survive_crlf_line_endings() {
    let code = "fn f() {\r\n    let a = \"https://x.example\";\r\n}\r\n";
    let mut offset = 0usize;
    let mut found_at = None;
    for raw_line in code.split_inclusive('\n') {
        let line_start = offset;
        offset += raw_line.len();
        let line = raw_line.strip_suffix('\n').unwrap_or(raw_line);
        let line = line.strip_suffix('\r').unwrap_or(line);
        if let Some(pos) = line.find("\"https://") {
            found_at = Some(line_start + pos);
        }
    }
    let found_at = found_at.expect("маркер обязан найтись");
    assert_eq!(
        &code[found_at..found_at + 9],
        "\"https://",
        "смещение, посчитанное по CRLF-строкам, обязано указывать точно на начало литерала",
    );
}

/// Два адреса в одной строке — оба обязаны быть найдены, не только первый. Проверяет
/// РЕАЛЬНЫЙ `string_literals_on_line`, а не повторяет старую логику текстом сбоку —
/// иначе тест молча перестаёт быть регрессией продукта, когда меняется реализация.
#[test]
fn discover_egress_finds_every_marker_on_the_same_line() {
    let line = "let (a, b) = (\"https://first.example\", \"https://second.example\");";
    let hits: Vec<String> = string_literals_on_line(line).into_iter().map(|(_, c)| c).collect();
    assert_eq!(
        hits,
        vec!["https://first.example".to_string(), "https://second.example".to_string()],
        "оба адреса одной строки обязаны найтись: {hits:?}",
    );
}

/// 🔴 Находка проверяющего-противника (11.09.2026): адрес, собранный по кускам, не
/// начинается ни в одном отдельном литерале с полной схемы — `concat!("ht",
/// "tps://evil.example/x")` даёт литерал-осколок `tps://evil.example/x`, который
/// содержит `://`, но не с начала. Классификация обязана поймать это как `Fragment`.
#[test]
fn classify_literal_catches_scheme_split_across_pieces() {
    assert!(matches!(classify_literal("tps://evil-concat.example/x"), Some(LiteralShape::Fragment)));
}

/// Голая схема-константа (`const SCHEME: &str = "https"`, `String::from("https:")`) —
/// строительный блок адреса, сама по себе находка.
#[test]
fn classify_literal_catches_bare_scheme_constants() {
    assert!(matches!(classify_literal("https"), Some(LiteralShape::BareScheme)));
    assert!(matches!(classify_literal("https:"), Some(LiteralShape::BareScheme)));
    assert!(matches!(classify_literal("http"), Some(LiteralShape::BareScheme)));
}

/// Полная схема — регистронезависимо (`"HTTPS://evil-upper.example/x"`, находка
/// проверяющего-противника) и с ведущим пробелом (`" https://evil-space.example/x"`).
#[test]
fn classify_literal_full_scheme_is_case_insensitive_and_trims_leading_space() {
    assert!(matches!(
        classify_literal("HTTPS://evil-upper.example/x"),
        Some(LiteralShape::FullScheme)
    ));
    assert!(matches!(
        classify_literal(" https://evil-space.example/x"),
        Some(LiteralShape::FullScheme)
    ));
}

/// 🔴 Точечное исключение, проверенное на честном дереве (11.09.2026): `aurora://` —
/// своя, не сетевая Tauri-схема (`lib.rs::handle_aurora_protocol`) — не находка. Но
/// если в ТОМ ЖЕ литерале рядом стоит настоящий `http(s)://`, находка остаётся.
#[test]
fn classify_literal_excludes_own_aurora_scheme_but_not_a_real_scheme_next_to_it() {
    assert!(classify_literal("aurora://localhost/some/path").is_none());
    assert!(classify_literal("aurora://localhost").is_none());
    assert!(matches!(
        classify_literal("aurora://localhost, https://evil.example"),
        Some(LiteralShape::Fragment)
    ));
}

/// 🔴 Голая схема-константа регистрозависима НАРОЧНО — токен «HTTP» (без «:», без
/// «//») в реальном дереве честный (lib.rs, проверка отсутствия технического кода в
/// клиентском тексте) и не имеет отношения к строительству адреса. Полная схема
/// (с «//») выше по-прежнему нечувствительна к регистру.
#[test]
fn classify_literal_bare_scheme_is_case_sensitive_on_purpose() {
    assert!(classify_literal("HTTP").is_none(), "голый «HTTP» без «:»/«//» — не находка");
    assert!(classify_literal("HTTP 403").is_none(), "текст с «HTTP» внутри — тем более не находка");
}

/// `position_is_inside_closure` ловит замыкание с телом (`|| { .. }`), но не путает
/// обычный блок (`#[cfg(..)] { .. }`, `if .. { .. }`) с замыканием.
#[test]
fn position_is_inside_closure_detects_closure_body_not_ordinary_blocks() {
    let closure_body =
        "pub async fn f() {\n    let _g = || {\n        ensure_gateway_route(&a)?;\n    };\n}";
    let gate_pos = closure_body.find("ensure_gateway_route(").expect("гейт обязан найтись");
    assert!(
        position_is_inside_closure(closure_body, gate_pos),
        "гейт внутри тела замыкания обязан быть распознан как таковой",
    );

    let ordinary_body = "pub async fn f() {\n    #[cfg(feature = \"x\")]\n    {\n        ensure_gateway_route(&a)?;\n    }\n}";
    let gate_pos = ordinary_body.find("ensure_gateway_route(").expect("гейт обязан найтись");
    assert!(
        !position_is_inside_closure(ordinary_body, gate_pos),
        "обычный блок (#[cfg] {{ .. }}) — не замыкание, ложной красноты быть не должно",
    );
}

/// `pub_fn_names` достаёт имена ИЗ исходника — список из трёх реальных pub fn
/// `gateway_executor.rs` не переписан руками и не устареет молча, если появится
/// четвёртая (тест упадёт явно на панике в `gated_by_route_files_actually_gate_their_egress`,
/// а не пропустит её).
#[test]
fn pub_fn_names_extracts_both_pub_fn_and_pub_async_fn() {
    let sample = "pub fn a() {}\npub async fn b() {}\nfn c() {}\npub(crate) fn d() {}\n";
    let names = pub_fn_names(sample);
    assert_eq!(names, vec!["a".to_string(), "b".to_string()], "нашлись обязаны быть только a и b: {names:?}");
}
