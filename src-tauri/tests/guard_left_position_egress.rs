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

/// Обращение к своей же машине наружу не считается.
///
/// 🔴 Хост разбирается ТОЧНО, не подстрокой (находка внешнего аудита, Medium, s41):
/// `https://127.0.0.1.attacker.example` содержит «127.0.0.1» как подстроку, но ведёт на
/// чужой домен. Тот же разбор хоста, что и в `rag_client.rs::validate_rag_url` — два места,
/// решающие один и тот же вопрос «это моя машина?», обязаны решать его одинаково.
fn is_loopback(url: &str) -> bool {
    let rest = url.trim_start_matches("https://").trim_start_matches("http://");
    let host_port = rest.split(['/', '?', '#']).next().unwrap_or("");
    let host = if let Some(stripped) = host_port.strip_prefix('[') {
        stripped.split(']').next().unwrap_or("")
    } else {
        host_port.split(':').next().unwrap_or("")
    };
    host == "127.0.0.1" || host == "localhost" || host == "::1" || host == "0.0.0.0"
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

/// Найти в исходниках ВСЕ обращения наружу: адрес в строковом литерале.
///
/// 🔴 Адресом считается литерал, у которого после схемы ЕСТЬ хост. Голая схема («https://»
/// без продолжения) сама по себе не запись: строку теми же двумя символами открывает и
/// сборка адреса через `format!("{}{}", "https://", host)` — обход, при котором сам литерал
/// адреса невидим для поиска подстроки (находка внешнего аудита, High, s41). Поэтому голая
/// схема прощается ТОЛЬКО в одном названном месте — `lib.rs::add_url_to_inbox`, где она
/// действительно не обращение, а приставка для разбора ссылки, которую человек кладёт в
/// «Входящие» (там только пишется .url-файл, сети нет; проверено приёмкой 11.09.2026).
/// Везде в остальном коде голая схема теперь идёт в общий список находок — без хоста она не
/// доказывает безопасность, а доказывает лишь то, что в ЭТОЙ строке хоста нет.
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
        let name = relative_path(&path);

        // Диапазон байт тела единственной функции, где голая схема — не обращение.
        let bare_scheme_carve_out =
            if name == "lib.rs" { extract_fn_range(&code, "fn add_url_to_inbox(") } else { None };

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

            for marker in ["\"https://", "\"http://"] {
                // 🔴 Находка внешнего аудита (Medium, s41): `line.find` брал только
                // ПЕРВОЕ вхождение на строке — два адреса в одной строке, второй был
                // невидим. Ищем ВСЕ вхождения маркера в строке.
                let mut search_from = 0usize;
                while let Some(rel_pos) = line[search_from..].find(marker) {
                    let pos = search_from + rel_pos;
                    let rest = &line[pos + 1..];
                    let url: String = rest.chars().take_while(|c| *c != '"').collect();
                    search_from = pos + marker.len();

                    if is_loopback(&url) {
                        continue;
                    }
                    let host = url.trim_start_matches("https://").trim_start_matches("http://");
                    if host.is_empty() {
                        let in_carve_out = bare_scheme_carve_out
                            .as_ref()
                            .map(|r| r.contains(&(line_start + pos)))
                            .unwrap_or(false);
                        if in_carve_out {
                            continue;
                        }
                    }
                    found.push(Egress { file: name.clone(), line: idx + 1, url });
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
                assert!(
                    body.contains("ensure_not_local_only(") && body.contains("ensure_cloud_consent("),
                    "econ_rag_search обязана проверять обе оси гейта левого положения ДО \
                     обращения наружу: {body}",
                );
            }
            "commands/gateway_executor.rs" => {
                // Звено (а): исполнители шлюза зовутся только из claude.rs.
                let mut files = Vec::new();
                rust_files(&src_dir(), &mut files);
                let executor_entry_points = ["run_claude_gateway(", "run_claude_pipeline_gateway("];
                for path in &files {
                    let name = relative_path(path);
                    if name == "commands/gateway_executor.rs" {
                        continue; // своё определение — не вызов
                    }
                    let Ok(raw) = fs::read_to_string(path) else { continue };
                    let code = strip_comments(&raw);
                    for entry in executor_entry_points {
                        if code.contains(entry) {
                            assert_eq!(
                                name, "commands/claude.rs",
                                "исполнитель шлюза {entry} вызывается из {name} в обход \
                                 единственного гейта в claude.rs",
                            );
                        }
                    }
                }
                // Звено (б): в claude.rs вызов исполнителя стоит ПОСЛЕ ensure_gateway_route
                // в теле той же функции, а не до него.
                let claude_src = fs::read_to_string(src_dir().join("commands").join("claude.rs"))
                    .expect("claude.rs обязан читаться");
                let claude_code = strip_comments(&claude_src);
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

/// `is_loopback` разбирает хост точно, а не подстрокой.
#[test]
fn is_loopback_matches_host_exactly_not_by_substring() {
    assert!(is_loopback("127.0.0.1:8801/search"), "обычный loopback с портом");
    assert!(is_loopback("localhost:8801"), "loopback по имени");
    assert!(
        !is_loopback("127.0.0.1.attacker.example/search"),
        "хост «127.0.0.1.attacker.example» — чужой домен, содержащий loopback подстрокой",
    );
    assert!(
        !is_loopback("evil-localhost.example"),
        "хост «evil-localhost.example» — чужой домен, содержащий «localhost» подстрокой",
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

/// Два адреса в одной строке — оба обязаны быть найдены, не только первый.
#[test]
fn discover_egress_finds_every_marker_on_the_same_line() {
    let line = "let (a, b) = (\"https://first.example\", \"https://second.example\");";
    let mut hits = Vec::new();
    let mut search_from = 0usize;
    let marker = "\"https://";
    while let Some(rel) = line[search_from..].find(marker) {
        let pos = search_from + rel;
        let rest = &line[pos + 1..];
        let url: String = rest.chars().take_while(|c| *c != '"').collect();
        hits.push(url);
        search_from = pos + marker.len();
    }
    assert_eq!(
        hits,
        vec!["https://first.example".to_string(), "https://second.example".to_string()],
        "оба адреса одной строки обязаны найтись: {hits:?}",
    );
}
