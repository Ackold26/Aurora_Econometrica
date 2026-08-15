//! Структурный сторож против возврата CPD-88 — стык двух списков категории обратной связи.
//!
//! **Найдено живым прогоном Docs Lab 0.12.4 (14.08.2026).** Форма обратной связи отвечала
//! `400 Bad Request`, и отзыв не уходил НИКОГДА — ни у одного продукта линейки. Причина: поле
//! «Категория» на стороне формы — ВЫПАДАЮЩИЙ СПИСОК с ответами по-русски («Проблемы» /
//! «Предложения» / «Вопросы»), а окно настроек шлёт внутренние значения переключателя латиницей
//! (`problem` / `suggestion` / `question`). Правка (`src/commands/feedback.rs::form_category`)
//! переводит значение перед отправкой и отказывается слать нераспознанное.
//!
//! Опасность не в самом переводе, а в том, что он молча РАССИНХРОНИЗИРУЕТСЯ с разметкой: кто-то
//! добавит в `<select>` настроек новую тему и забудет пару в `CATEGORY_MAP` (или наоборот). Каждая
//! сторона по отдельности при этом выглядит исправной — ни один прежний тест такое не ловил.
//! Сторож проверяет ровно СТЫК: каждое значение `<option value="…">` переключателя темы обязано
//! иметь перевод. Проверено мутацией (см. отчёт `Projects/FIX_CPD88_ECON_2026-08-15.md`) —
//! временное добавление четвёртой темы без пары в разметку валило этот тест с названием
//! забытого значения.
//!
//! Идиома чтения чужого исходника как текста через `CARGO_MANIFEST_DIR` — как в
//! `guard_no_regressed_cpd77_cpd79.rs`. Разница в том, что здесь сторож дополнительно линкуется
//! с библиотечным крейтом продукта (`aurora_econometrica_lib`), чтобы сверяться с ЖИВОЙ таблицей
//! перевода `form_category`, а не с её текстовой копией — иначе сторож можно было бы обмануть,
//! не меняя код перевода вовсе.

use aurora_econometrica_lib::commands::feedback::form_category;
use std::fs;
use std::path::Path;

/// Извлекает значения `<option value="…">` из блока `<select>` переключателя темы обращения.
///
/// Ищет `bind:value={fbCategory}` как якорь начала блока (это и есть переключатель темы в
/// окне настроек) и `</select>` как конец — то же ограничение диапазона поиска, что и в
/// эталонной правке Docs Lab (`d9b02ef`).
fn extract_settings_category_values(markup: &str) -> Vec<String> {
    let anchor = "bind:value={fbCategory}";
    let block_start = markup
        .find(anchor)
        .unwrap_or_else(|| panic!("переключатель темы обращения (\"{anchor}\") не найден в разметке настроек — сторож устарел"));
    let block = &markup[block_start..];
    let block_end = block
        .find("</select>")
        .expect("конец переключателя (</select>) не найден после bind:value={fbCategory}");
    let block = &block[..block_end];

    block
        .split("<option value=\"")
        .skip(1)
        .map(|chunk| chunk.split('"').next().unwrap_or_default().to_string())
        .collect()
}

/// Главная проверка: каждое значение переключателя темы из разметки настроек обязано иметь
/// перевод в живой таблице `form_category`. Расхождение в любую сторону — сигнал регресса
/// CPD-88 (форма снова начнёт отвечать 400 на часть или все темы).
#[test]
fn settings_choices_and_category_map_do_not_drift_apart() {
    let manifest_dir =
        std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR не задан тестовым раннером");
    // src-tauri/tests/ → ../../src/routes/settings/+page.svelte = src/routes/settings/+page.svelte
    let settings_path = Path::new(&manifest_dir)
        .join("..")
        .join("src")
        .join("routes")
        .join("settings")
        .join("+page.svelte");
    let markup = fs::read_to_string(&settings_path)
        .unwrap_or_else(|e| panic!("не удалось прочитать {}: {e}", settings_path.display()));

    let ui_values = extract_settings_category_values(&markup);
    assert!(
        !ui_values.is_empty(),
        "переключатель темы обращения найден, но ни одного <option value=\"…\"> не извлечено — \
         сторож не проверяет ничего, разбор разметки сломан"
    );

    let missing: Vec<&String> = ui_values
        .iter()
        .filter(|value| form_category(value).is_none())
        .collect();

    assert!(
        missing.is_empty(),
        "в разметке настроек есть темы обращения без перевода в form_category: {missing:?}. \
         Форма Google (entry.1292211421) отвергнет их отказом 400, а человек увидит только код \
         ошибки FB-001 — это регресс CPD-88. Добавьте пару в CATEGORY_MAP \
         (src-tauri/src/commands/feedback.rs) с ответом, который реально есть в выпадающем списке \
         формы."
    );
}

/// Дополнительная проверка направления обратного дрейфа: любое значение из живой таблицы
/// перевода обязано существовать в разметке настроек. Если пара осталась в `CATEGORY_MAP`
/// после удаления темы из интерфейса — не баг, но мёртвый код стоит заметить явно, а не молчать.
#[test]
fn category_map_has_no_orphaned_entries_missing_from_settings() {
    let manifest_dir =
        std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR не задан тестовым раннером");
    let settings_path = Path::new(&manifest_dir)
        .join("..")
        .join("src")
        .join("routes")
        .join("settings")
        .join("+page.svelte");
    let markup = fs::read_to_string(&settings_path)
        .unwrap_or_else(|e| panic!("не удалось прочитать {}: {e}", settings_path.display()));

    let ui_values = extract_settings_category_values(&markup);

    let orphaned: Vec<&str> = aurora_econometrica_lib::commands::feedback::CATEGORY_MAP
        .iter()
        .map(|(ui, _)| *ui)
        .filter(|ui| !ui_values.iter().any(|v| v == ui))
        .collect();

    assert!(
        orphaned.is_empty(),
        "в CATEGORY_MAP есть значения без темы в разметке настроек: {orphaned:?} — мёртвая пара, \
         тему убрали из интерфейса, а перевод забыли убрать вслед"
    );
}

// ── Проверка самого сторожа: извлечение значений не должно ни терять, ни путать темы ──────────

#[test]
fn extract_settings_category_values_reads_all_options_in_order() {
    let markup = r#"
        <select class="fb-select" bind:value={fbCategory}>
          <option value="problem">Проблема</option>
          <option value="suggestion">Пожелание</option>
          <option value="question">Вопрос</option>
        </select>
    "#;
    assert_eq!(
        extract_settings_category_values(markup),
        vec!["problem", "suggestion", "question"]
    );
}

#[test]
fn extract_settings_category_values_stops_at_select_close() {
    // Значение ПОСЛЕ </select> не должно попасть в разбор — иначе сторож проверял бы чужой блок.
    let markup = r#"
        <select bind:value={fbCategory}>
          <option value="problem">Проблема</option>
        </select>
        <select bind:value={somethingElse}>
          <option value="unrelated">Не тема обращения</option>
        </select>
    "#;
    assert_eq!(extract_settings_category_values(markup), vec!["problem"]);
}

/// Ось мутации сторожа (см. отчёт FIX_CPD88_ECON для реального прогона): если бы в разметке
/// появилась тема без пары, извлечение обязано её всё равно вернуть — иначе главный тест
/// не сможет её назвать.
#[test]
fn extract_settings_category_values_returns_value_even_without_a_translation_pair() {
    let markup = r#"
        <select bind:value={fbCategory}>
          <option value="problem">Проблема</option>
          <option value="typo_no_pair">Опечатка без перевода</option>
        </select>
    "#;
    assert_eq!(
        extract_settings_category_values(markup),
        vec!["problem", "typo_no_pair"]
    );
}
