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
