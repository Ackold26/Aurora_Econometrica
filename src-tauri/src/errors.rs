//! Коды ошибок продукта. Определения переехали в общий крейт `aurora_core` (трассирующий
//! срез 15.08.2026) — здесь остался реэкспорт, чтобы весь остальной код продукта, ссылающийся
//! на `crate::errors::…`, продолжал работать без единой правки.
pub use aurora_core::errors::*;

/// 🔴 Приёмочная проверка СТЫКА с общим крейтом.
///
/// Внешний аудит блока 2.4.10: после выноса кодов ошибок в `aurora_core` юнит-тесты уехали
/// туда вместе с кодом, и на стороне продукта стык не проверялся ничем. Между тем формат
/// строки — клиентская поверхность: он напечатан в `help/error-codes.html` и в документации,
/// по нему клиент ищет свою ошибку. Смени в крейте `coded()` на `"LI-005: detail"` или
/// переименуй вариант, сохранив сигнатуру, — продукт соберётся без единой правки, а строки
/// у клиента разойдутся с документацией молча.
///
/// Здесь проверяется ровно договор, на который опирается продукт, а не внутренности крейта:
/// формат обёртки и присутствие кодов, названных в клиентской документации.
#[cfg(test)]
mod core_contract_tests {
    use super::*;

    #[test]
    fn coded_keeps_the_bracketed_format_documented_to_clients() {
        assert_eq!(
            coded(ErrorCode::LI005, "срок лицензии истёк"),
            "[LI-005] срок лицензии истёк",
            "формат кода ошибки — клиентская поверхность: он напечатан в справке продукта"
        );
    }

    /// 🔴 Сторож класса ошибки s48-audit: справка (`help-econometrica/error-codes.html`)
    /// когда-то описывала коды `EC-*`/`DP-*`, которых в `ErrorCode` не было вообще, и
    /// молчала про реальные `VT-*`/`CL-*`/`SY-*`/`AU-*`. Прежняя версия этого теста
    /// проверяла три кода поимённо и такое расхождение поймать не могла (справка
    /// красной не становилась, пока кто-то не сверил её вручную). Проверяем сверку
    /// в обе стороны: код есть в справке, но недостижим в продукте — красный; код
    /// реально достижим в продукте, но не упомянут в справке — тоже красный.
    ///
    /// s48-codesfix: эталоном раньше был ПОЛНЫЙ платформенный перечень `ErrorCode`
    /// (крейт `aurora_core` общий на всю линейку Aurora AI) — из-за этого справка была
    /// обязана документировать `AU-*` (онлайн-авторизация) и `SY-*` (система), хотя
    /// в Эконометрике они не конструируются НИ РАЗУ: `online_auth.rs` ведёт свой
    /// статус-протокол без `ErrorCode`, а сервер не присылает код ошибки в ответе
    /// вовсе (проверено фактом 14.09.2026). Правильный эталон — не полный перечень
    /// `ErrorCode`, а перечень кодов, РЕАЛЬНО достижимых в ЭТОМ продукте. Он выводится
    /// автоматически из фактических вызовов `ErrorCode::` по всему `src-tauri/src`
    /// (кроме этого файла — здесь код только цитируется ради проверки формата в
    /// `coded_keeps_the_bracketed_format_documented_to_clients`, а не конструируется
    /// как ошибка пользователю), тем же приёмом обхода дерева (`walkdir`), каким уже
    /// пользуются другие сторожи продукта.
    ///
    /// 🔴 s48-audit (2026-09-14, вторая волна): модель «эталон = только `src-tauri/src`»
    /// оказалась НЕПОЛНОЙ — она выбросила `FB-002`, потому что код, реально его строящий,
    /// живёт не здесь, а в общем крейте (`aurora_core::feedback::submit`, feedback.rs:73
    /// на закреплённой ревизии, см. `PINNED_AURORA_CORE_REV` ниже), а продукт лишь вызывает
    /// эту функцию из `commands/feedback.rs::submit_feedback` — команда с `#[tauri::command]`,
    /// реально зарегистрированная в `generate_handler!` (лицо клиента может вызвать её через
    /// `invoke` напрямую, даже если разметка фронтенда её больше не зовёт — см. докстринг
    /// `commands/feedback.rs`). Обход `walkdir` по `aurora_core` здесь не работает: крейт —
    /// git-зависимость вне этого репозитория, и `cargo metadata` для поиска её исходников на
    /// диске ненадёжен КАК ПРОВЕРКА ТЕСТА (офлайн-окружение валит его сетевой ошибкой —
    /// проверено фактом 14.09.2026, `getaddrinfo() thread failed to start`). Поэтому для кодов
    /// из `aurora_core` — явный список `AURORA_CORE_FEEDBACK_CODES`, но не свободный: он
    /// подключается к `reachable_codes` ТОЛЬКО если этот же обход находит реальный вызов
    /// `aurora_core::feedback::submit` в `src-tauri/src` (значит функция правда используется
    /// продуктом, не гипотеза), и список привязан к конкретной ревизии крейта — если
    /// `Cargo.lock` укажет другую ревизию `aurora_core`, тест падает ДО того, как список
    /// молча устареет, требуя пересверки с `feedback.rs` на новой ревизии.
    #[test]
    fn help_error_codes_page_matches_error_code_enum_both_ways() {
        use std::collections::HashSet;

        /// Ревизия `aurora_core`, на которой сверен `AURORA_CORE_FEEDBACK_CODES` ниже
        /// (см. `Cargo.lock`: `source = "git+.../aurora-platform-core.git?tag=aurora_core-v0.1.0#<rev>"`).
        const PINNED_AURORA_CORE_REV: &str = "35d8345c4f20f66efc1012be4190b90f620f1ddb";
        /// Коды, которые на ревизии `PINNED_AURORA_CORE_REV` строит
        /// `aurora_core::feedback::submit` (сверено вручную по исходнику функции: FB-001 —
        /// нераспознанная категория / отказ формы, FB-002 — вызов раньше минимального
        /// интервала между отправками).
        const AURORA_CORE_FEEDBACK_CODES: &[&str] = &["FB-001", "FB-002"];

        // "ErrorCode::XX000" в исходнике компилируется только если XX000 — настоящий
        // вариант enum'а; значит каждое совпадение — подлинное использование кода
        // где-то в продукте, а не гипотеза о нём.
        let usage_re =
            regex::Regex::new(r"ErrorCode::([A-Z]{2})([0-9]{3})").expect("valid regex");
        let src_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
        let mut reachable_codes: HashSet<String> = HashSet::new();
        let mut calls_aurora_core_feedback = false;
        for entry in walkdir::WalkDir::new(&src_root)
            .into_iter()
            .filter_map(|e| e.ok())
        {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("rs") {
                continue;
            }
            if path.file_name().and_then(|n| n.to_str()) == Some("errors.rs") {
                continue;
            }
            let src = std::fs::read_to_string(path)
                .unwrap_or_else(|e| panic!("не удалось прочитать {}: {e}", path.display()));
            for caps in usage_re.captures_iter(&src) {
                reachable_codes.insert(format!("{}-{}", &caps[1], &caps[2]));
            }
            if src.contains("aurora_core::feedback::submit") {
                calls_aurora_core_feedback = true;
            }
        }
        assert!(
            !reachable_codes.is_empty(),
            "обход src-tauri/src не нашёл ни одного вызова ErrorCode:: — путь или regex сломаны, \
             проверка ничего не сторожит"
        );

        if calls_aurora_core_feedback {
            let cargo_lock_path =
                std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("Cargo.lock");
            let cargo_lock = std::fs::read_to_string(&cargo_lock_path).unwrap_or_else(|e| {
                panic!("не удалось прочитать {}: {e}", cargo_lock_path.display())
            });
            let rev_re = regex::Regex::new(r#"name = "aurora_core"\nversion = "[^"]+"\nsource = "git\+[^"]*#([0-9a-f]{40})""#)
                .expect("valid regex");
            let actual_rev = rev_re
                .captures(&cargo_lock)
                .unwrap_or_else(|| {
                    panic!(
                        "{}: не нашёл строку 'aurora_core' с git-ревизией — формат Cargo.lock изменился?",
                        cargo_lock_path.display()
                    )
                })
                .get(1)
                .expect("regex захватывает ревизию")
                .as_str();
            assert_eq!(
                actual_rev, PINNED_AURORA_CORE_REV,
                "aurora_core в Cargo.lock указывает на ревизию {actual_rev}, а \
                 AURORA_CORE_FEEDBACK_CODES сверен с {PINNED_AURORA_CORE_REV} — пересверь \
                 список кодов с aurora_core::feedback::submit на новой ревизии и обнови обе \
                 константы, иначе список молча устареет"
            );
            for code in AURORA_CORE_FEEDBACK_CODES {
                reachable_codes.insert((*code).to_string());
            }
        }

        let html_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("help-econometrica")
            .join("error-codes.html");
        let html = std::fs::read_to_string(&html_path)
            .unwrap_or_else(|e| panic!("не удалось прочитать {}: {e}", html_path.display()));

        // [A-Z]{2}-[0-9]{3} ловит реальные коды (LI-005, CL-010, …) и НЕ ловит плейсхолдер
        // "XX-NNN" (буквы вместо цифр) или случайные тире в прозе ("R-hat > 1.1").
        let code_re = regex::Regex::new(r"\b[A-Z]{2}-[0-9]{3}\b").expect("valid regex");
        let html_codes: HashSet<&str> = code_re.find_iter(&html).map(|m| m.as_str()).collect();

        let invented: Vec<&&str> = html_codes
            .iter()
            .filter(|c| !reachable_codes.contains(**c))
            .collect();
        let undocumented: Vec<&String> = reachable_codes
            .iter()
            .filter(|c| !html_codes.contains(c.as_str()))
            .collect();

        assert!(
            invented.is_empty(),
            "справка называет коды, которых нет среди достижимых в продукте (выдумка или код \
             недостижимого класса вроде AU-*/SY-*): {invented:?}"
        );
        assert!(
            undocumented.is_empty(),
            "в продукте реально достижимы коды, не описанные в \
             help-econometrica/error-codes.html: {undocumented:?}"
        );
    }
}
