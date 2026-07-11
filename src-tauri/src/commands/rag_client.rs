// Клиент серверной эконометрической RAG-библиотеки (узел Б, corpus "econometrics").
// Вопрос пользователя уходит на сервер — тот же egress-класс, что и Claude
// (claude.rs::run_claude): те же гейты (согласие + «только локально»), локальная
// редакция (152-ФЗ) собирается без feature `cloud_advisors` → команда недоступна
// статически. Глушим dead_code ТОЛЬКО для этой конфигурации; egress-гард — на
// входной команде `econ_rag_search`.
#![cfg_attr(not(feature = "cloud_advisors"), allow(dead_code))]

#[cfg(feature = "cloud_advisors")]
use log::{debug, warn};
use serde::Serialize;

/// Дефолтный адрес RAG-сервера (dev: SSH-туннель до узла Б). Прод — через env.
const DEFAULT_RAG_URL: &str = "http://127.0.0.1:8801";

/// Таймаут запроса к RAG-серверу.
const REQUEST_TIMEOUT_SECS: u64 = 5;

/// Корпус захардкожен — эконометрическая библиотека, единственная, с которой
/// работает этот кабинет.
const CORPUS: &str = "econometrics";

/// Дефолт числа выдержек, если фронт не указал.
const DEFAULT_K: u8 = 4;

/// Транспортный инвариант (аудит 2026-07-11, M1): секрет `X-Aurora-Auth` и
/// вопрос пользователя НЕ должны идти открытым http через сеть. Разрешаем
/// `http://` только на loopback (SSH-туннель до узла Б); всё внешнее — только
/// `https://`. Иначе развёртывание с прямым http-адресом узла Б отдало бы
/// секрет и вопросы пользователя в открытом виде.
fn validate_rag_url(base_url: &str) -> Result<(), String> {
    let lower = base_url.trim().to_ascii_lowercase();
    if lower.starts_with("https://") {
        return Ok(());
    }
    if let Some(rest) = lower.strip_prefix("http://") {
        let host_port = rest.split(['/', '?', '#']).next().unwrap_or("");
        let host = if host_port.starts_with('[') {
            host_port.split(']').next().map(|h| &h[1..]).unwrap_or("")
        } else {
            host_port.split(':').next().unwrap_or("")
        };
        if host == "127.0.0.1" || host == "localhost" || host == "::1" {
            return Ok(());
        }
        return Err(format!(
            "[RAG-PLAINTEXT] Небезопасный адрес библиотеки «{base_url}»: http допустим только для 127.0.0.1/localhost (SSH-туннель), внешний адрес — только https"
        ));
    }
    Err(format!(
        "[RAG-URL] Непонятная схема адреса библиотеки «{base_url}» — ожидается http://127.0.0.1… или https://…"
    ))
}

#[derive(Debug, Serialize)]
struct SearchRequest<'a> {
    corpus: &'a str,
    query: &'a str,
    k: u8,
}

/// Defense-in-depth: те же egress-чок-поинты, что и claude.rs::run_claude —
/// запрет, пока не дано согласие на облачную обработку.
#[cfg(feature = "cloud_advisors")]
fn ensure_cloud_consent(app_handle: &tauri::AppHandle) -> Result<(), String> {
    use tauri::Manager;
    let config_dir = app_handle
        .path()
        .app_config_dir()
        .map_err(|e| format!("app_config_dir: {e}"))?;
    if crate::commands::user_config::cloud_consent_required(&config_dir) {
        return Err("[RAG-CONSENT] Требуется согласие на облачную обработку перед использованием библиотеки методологии".to_string());
    }
    Ok(())
}

/// Defense-in-depth: запрет, если включён runtime-режим «только локально»
/// (данные не уходят на серверы). Тот же чок-поинт, что и claude.rs.
#[cfg(feature = "cloud_advisors")]
fn ensure_not_local_only(app_handle: &tauri::AppHandle) -> Result<(), String> {
    use tauri::Manager;
    let config_dir = app_handle
        .path()
        .app_config_dir()
        .map_err(|e| format!("app_config_dir: {e}"))?;
    if crate::commands::user_config::local_only_enabled(&config_dir) {
        return Err("[RAG-LOCAL-ONLY] Включён режим «только локально» — библиотека методологии отключена, данные не уходят".to_string());
    }
    Ok(())
}

/// Поиск по эконометрической RAG-библиотеке первоисточников на узле Б.
/// Вопрос пользователя уходит на сервер — под теми же гейтами, что и Claude
/// (согласие + «только локально»); в локальной редакции (152-ФЗ) недоступна.
#[tauri::command]
pub async fn econ_rag_search(
    query: String,
    k: Option<u8>,
    app_handle: tauri::AppHandle,
) -> Result<serde_json::Value, String> {
    #[cfg(not(feature = "cloud_advisors"))]
    {
        let _ = (query, k, app_handle);
        Err("[RAG-LOCAL] Библиотека методологии недоступна в локальной редакции".to_string())
    }
    #[cfg(feature = "cloud_advisors")]
    {
        ensure_not_local_only(&app_handle)?;
        ensure_cloud_consent(&app_handle)?;

        if query.trim().is_empty() {
            return Err("[RAG-EMPTY] Пустой запрос к библиотеке методологии".to_string());
        }

        let secret = std::env::var("AURORA_RAG_SECRET")
            .map_err(|_| "[RAG-NOAUTH] Не задан секрет доступа к библиотеке методологии".to_string())?;

        let base_url = std::env::var("AURORA_RAG_URL")
            .unwrap_or_else(|_| DEFAULT_RAG_URL.to_string());
        validate_rag_url(&base_url)?;
        let url = format!("{}/search", base_url.trim_end_matches('/'));

        let k = k.unwrap_or(DEFAULT_K).clamp(1, 8);
        let req = SearchRequest { corpus: CORPUS, query: &query, k };

        debug!("RAG search: POST {} (k={})", url, k);

        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(REQUEST_TIMEOUT_SECS))
            .build()
            .map_err(|e| format!("[RAG-HTTP] Не удалось создать клиент: {e}"))?;

        let resp = client
            .post(&url)
            .header("X-Aurora-Auth", &secret)
            .json(&req)
            .send()
            .await
            .map_err(|e| format!("[RAG-HTTP] Библиотека методологии недоступна: {e}"))?;

        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            warn!("RAG search failed: HTTP {status}, body: {body}");
            return Err(format!("[RAG-HTTP] Сервер библиотеки вернул ошибку {status}"));
        }

        resp.json::<serde_json::Value>()
            .await
            .map_err(|e| format!("[RAG-HTTP] Не удалось разобрать ответ библиотеки: {e}"))
    }
}

#[cfg(test)]
mod tests {
    use super::validate_rag_url;

    #[test]
    fn loopback_http_allowed() {
        assert!(validate_rag_url("http://127.0.0.1:8801").is_ok());
        assert!(validate_rag_url("http://localhost:8801").is_ok());
        assert!(validate_rag_url("http://127.0.0.1:8801/").is_ok());
    }

    #[test]
    fn https_allowed_anywhere() {
        assert!(validate_rag_url("https://rag.aurora-platform.pro").is_ok());
        assert!(validate_rag_url("https://37.27.218.187:8801").is_ok());
    }

    #[test]
    fn plaintext_http_to_external_host_rejected() {
        let err = validate_rag_url("http://37.27.218.187:8801").unwrap_err();
        assert!(err.starts_with("[RAG-PLAINTEXT]"), "got: {err}");
        assert!(validate_rag_url("http://evil.example.com/search").is_err());
        // localhost-похожий, но внешний хост не проходит по префиксу
        assert!(validate_rag_url("http://localhost.evil.com:8801").is_err());
    }

    #[test]
    fn garbage_scheme_rejected() {
        assert!(validate_rag_url("ftp://127.0.0.1").is_err());
        assert!(validate_rag_url("127.0.0.1:8801").is_err());
    }
}
