//! Команда обратной связи продукта. Тело (ограничение частоты, перевод категории, HTTP-отправка)
//! переехало в общий крейт `aurora_core` (трассирующий срез 15.08.2026, `Projects/CRATE_DESIGN_2026-08-15.md`).
//! Здесь остаются: реэкспорт `form_category`/`CATEGORY_MAP` (сторож `guard_cpd88_feedback_category_map.rs`
//! линкуется именно с этим путём) и тонкая обёртка с `#[tauri::command]` — атрибут в крейт не
//! переносился намеренно, граница крейта проходит ровно по нему.
pub use aurora_core::feedback::{form_category, CATEGORY_MAP};

/// Submit user feedback via HTTP POST. Тело — в `aurora_core::feedback::submit`.
#[tauri::command]
pub async fn submit_feedback(
    category: String,
    message: String,
    contact: String,
) -> Result<String, String> {
    aurora_core::feedback::submit(category, message, contact).await
}
