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
    /// пользуются другие сторожи продукта. Ручного списка больше нет — ему негде
    /// протухнуть, потому что он не существует отдельно от кода.
    #[test]
    fn help_error_codes_page_matches_error_code_enum_both_ways() {
        use std::collections::HashSet;

        // "ErrorCode::XX000" в исходнике компилируется только если XX000 — настоящий
        // вариант enum'а; значит каждое совпадение — подлинное использование кода
        // где-то в продукте, а не гипотеза о нём.
        let usage_re =
            regex::Regex::new(r"ErrorCode::([A-Z]{2})([0-9]{3})").expect("valid regex");
        let src_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
        let mut reachable_codes: HashSet<String> = HashSet::new();
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
        }
        assert!(
            !reachable_codes.is_empty(),
            "обход src-tauri/src не нашёл ни одного вызова ErrorCode:: — путь или regex сломаны, \
             проверка ничего не сторожит"
        );

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
