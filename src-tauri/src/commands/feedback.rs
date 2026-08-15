use crate::errors::{coded, ErrorCode};
use log::{info, warn};
use std::sync::Mutex;
use std::time::Instant;

/// Minimum interval between feedback submissions (60 seconds).
const RATE_LIMIT_SECS: u64 = 60;

/// Endpoint for feedback submission.
fn feedback_url() -> String {
    "https://docs.google.com/forms/d/e/1FAIpQLSdK_JroYSnX09InTfhEYl_WFFDzmA3BQun7PWWscdBZoUR25w/formResponse".to_string()
}

static LAST_SUBMIT: Mutex<Option<Instant>> = Mutex::new(None);

/// Соответствие значений выбора в окне настроек и допустимых ответов формы.
///
/// 🔴 CPD-88 (найдено живым прогоном Docs Lab 0.12.4, 14.08.2026, эталон правки `d9b02ef`):
/// форма обратной связи отвечала `400 Bad Request`, и отзыв не уходил НИКОГДА — ни у одного
/// продукта линейки. Причина — поле «Категория» на стороне формы это ВЫПАДАЮЩИЙ СПИСОК с тремя
/// ответами по-русски, а программа слала внутренние значения переключателя латиницей
/// (`problem`, `suggestion`, `question`). Для выбора из списка сервис проверяет значение и
/// отвергает всё, чего в списке нет; свободный текст он принял бы молча, поэтому дефект и жил
/// незамеченным — два других поля формы как раз свободные.
///
/// Порядок пар — как в списке формы. Значения справа менять только вместе с самой формой:
/// расхождение снова вернёт отказ, и снова без внятной причины для человека.
pub const CATEGORY_MAP: &[(&str, &str)] = &[
    ("problem", "Проблемы"),
    ("suggestion", "Предложения"),
    ("question", "Вопросы"),
];

/// Перевод значения переключателя в ответ, который примет форма.
///
/// Неизвестное значение НЕ отправляем: сервис ответит отказом, а человек увидит невнятный код
/// ошибки вместо причины. Лучше честно сказать, что выбор не распознан.
pub fn form_category(ui_value: &str) -> Option<&'static str> {
    CATEGORY_MAP
        .iter()
        .find(|(ui, _)| *ui == ui_value)
        .map(|(_, form)| *form)
}

/// Submit user feedback via HTTP POST.
#[tauri::command]
pub async fn submit_feedback(
    category: String,
    message: String,
    contact: String,
) -> Result<String, String> {
    // Rate limit check
    {
        let mut last = LAST_SUBMIT.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(t) = *last {
            if t.elapsed().as_secs() < RATE_LIMIT_SECS {
                return Err(coded(
                    ErrorCode::FB002,
                    "Подождите минуту перед повторной отправкой",
                ));
            }
        }
        *last = Some(Instant::now());
    }

    if message.trim().is_empty() {
        return Err("Сообщение не может быть пустым".to_string());
    }

    let Some(form_category) = form_category(category.trim()) else {
        warn!("Feedback: неизвестная категория «{category}» — отправка не выполнена");
        return Err(coded(
            ErrorCode::FB001,
            "Не удалось распознать выбранную тему обращения. Выберите тему заново и повторите.",
        ));
    };

    info!(
        "Submitting feedback: category={} (форме уходит «{}»), len={}",
        category,
        form_category,
        message.len()
    );

    let params = [
        ("entry.1292211421", form_category),
        ("entry.1623086744", message.as_str()),
        ("entry.1356992057", contact.as_str()),
    ];

    let client = reqwest::Client::new();
    let resp = client
        .post(feedback_url())
        .form(&params)
        .timeout(std::time::Duration::from_secs(15))
        .send()
        .await;

    match resp {
        Ok(r) if r.status().is_success() || r.status().as_u16() == 302 => {
            info!("Feedback submitted successfully");
            Ok("ok".to_string())
        }
        Ok(r) => {
            warn!("Feedback server returned {}", r.status());
            Err(coded(
                ErrorCode::FB001,
                &format!("Сервер вернул ошибку: {}", r.status()),
            ))
        }
        Err(e) => {
            warn!("Feedback submission failed: {}", e);
            Err(coded(ErrorCode::FB001, "Не удалось отправить отзыв"))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Значения переключателя переводятся в ответы, которые форма принимает.
    #[test]
    fn every_ui_choice_maps_to_a_form_answer() {
        assert_eq!(form_category("problem"), Some("Проблемы"));
        assert_eq!(form_category("suggestion"), Some("Предложения"));
        assert_eq!(form_category("question"), Some("Вопросы"));
    }

    /// Незнакомое значение НЕ уходит в форму: сервис ответил бы отказом, а человек увидел бы
    /// код ошибки вместо причины.
    #[test]
    fn unknown_choice_is_refused_before_sending() {
        assert_eq!(form_category("что-то новое"), None);
        assert_eq!(form_category(""), None);
        assert_eq!(
            form_category("Проблемы"),
            None,
            "ответ формы не является значением переключателя"
        );
    }
}
