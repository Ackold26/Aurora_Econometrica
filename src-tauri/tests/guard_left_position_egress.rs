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
//! либо закрытым гейтом левого положения. Незнакомое место — отказ с именем файла и строкой.
//!
//! Чего сторож НЕ доказывает: что закрытое гейтом место действительно молчит во время работы
//! (это доказывает прогон, а не чтение) и что сервер по ту сторону ведёт себя как обещано.
//! Он доказывает ровно одно, зато без пропусков: нового пути наружу мимо гейта в дереве нет.

use std::fs;
use std::path::{Path, PathBuf};

/// Три обращения, разрешённые в левом положении, — по файлу-владельцу и слову, которым
/// обращение названо человеку в подписи под переключателем.
///
/// 🔴 Пара «файл → слово» связывает код с текстом на экране. Если появится четвёртый
/// разрешённый канал, его придётся и назвать человеку, и внести сюда — иначе подпись
/// начнёт врать умолчанием, а сторож промолчит.
const ALLOWED_INFRA: &[(&str, &str)] = &[
    ("online_auth.rs", "лицензи"),
    ("updater.rs", "обновлени"),
    ("content_updater.rs", "докачка"),
];

/// Файлы, чей выход наружу закрыт гейтом левого положения (ассистент и его окружение).
const GATED_BY_ROUTE: &[&str] = &["claude.rs", "gateway_executor.rs", "rag_client.rs"];

/// Обращение к своей же машине наружу не считается.
fn is_loopback(url: &str) -> bool {
    url.contains("127.0.0.1") || url.contains("localhost") || url.contains("0.0.0.0")
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

/// Одно найденное обращение наружу: файл, строка, адрес.
struct Egress {
    file: String,
    line: usize,
    url: String,
}

/// Найти в исходниках ВСЕ обращения наружу: адрес в строковом литерале.
///
/// 🔴 Адресом считается литерал, у которого после схемы ЕСТЬ хост. Голая схема («https://»
/// без продолжения) — не обращение, а приставка для разбора строки: так проверяют ссылку,
/// которую человек кладёт в «Входящие», и так же вырезают домен для имени файла. Без этого
/// различения сторож краснел на `add_url_to_inbox`, где сетевого вызова нет вовсе
/// (найдено приёмкой 11.09.2026).
///
/// Чего этот способ НЕ делает: не проверяет, что рядом с адресом живёт сетевой клиент.
/// Признак «клиент рядом» дал бы пропуски — адрес-константа нередко стоит вверху файла,
/// а вызов ниже. Поэтому берём шире: любой адрес с хостом требует объяснения.
fn discover_egress() -> Vec<Egress> {
    let mut files = Vec::new();
    rust_files(&src_dir(), &mut files);
    let mut found = Vec::new();
    for path in files {
        let Ok(raw) = fs::read_to_string(&path) else { continue };
        let code = strip_comments(&raw);
        let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("").to_string();
        for (idx, line) in code.lines().enumerate() {
            for marker in ["\"https://", "\"http://"] {
                let Some(pos) = line.find(marker) else { continue };
                let rest = &line[pos + 1..];
                let url: String = rest.chars().take_while(|c| *c != '"').collect();
                if is_loopback(&url) {
                    continue;
                }
                // Голая схема без хоста — разбор строки, а не обращение (см. докстроку выше).
                let host = url
                    .trim_start_matches("https://")
                    .trim_start_matches("http://");
                if host.is_empty() {
                    continue;
                }
                found.push(Egress { file: name.clone(), line: idx + 1, url });
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
