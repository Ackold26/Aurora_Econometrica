use crate::errors::{coded, ErrorCode};
use log::{info, warn};
use std::sync::Mutex;
use std::time::Instant;

/// Minimum interval between feedback submissions (60 seconds).
const RATE_LIMIT_SECS: u64 = 60;

/// Endpoint for feedback submission (obfuscated).
fn feedback_url() -> String {
    obfstr::obfstr!("https://docs.google.com/forms/d/e/1FAIpQLSdK_JroYSnX09InTfhEYl_WFFDzmA3BQun7PWWscdBZoUR25w/formResponse").to_string()
}

static LAST_SUBMIT: Mutex<Option<Instant>> = Mutex::new(None);

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

    info!("Submitting feedback: category={}, len={}", category, message.len());

    let params = [
        ("entry.1292211421", category.as_str()),
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
