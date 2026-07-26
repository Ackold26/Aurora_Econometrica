//! Gateway-исполнитель тонкой версии (feature `thin`): кабинет исполняется через
//! SSH-транспорт `aurora_gateway` на узле Б, а не локальным Claude CLI. Адаптер
//! зеркалит контракт `claude::run_claude`/`run_claude_pipeline` (та же пара
//! входов, та же семантика suppress_export/suppress_done), чтобы `claude.rs`
//! подключал его минимальной правкой веток `#[cfg(feature = "thin")]`.
//!
//! ## Сессии
//! label = `resume_session_id`, а если `None` — генерируем `tc-<cabinet_id>-<hex>`.
//! Возвращаем label как первый элемент кортежа (`Some(label)`) — существующий
//! механизм продукта `set_claude_session_id`/`get_claude_session_id`/
//! `clear_claude_session_id` (session/manager.rs) АВТОМАТИЧЕСКИ рулит серверными
//! sticky-сессиями: продолжение диалога шлёт тот же label, слэш-сброс — новый.
//! Ноль нового состояния на клиенте.
//!
//! ## Ошибки
//! Коды в стиле claude.rs ([CL-...]): `[TC-GW-TIMEOUT]` (сервер не ответил вовремя),
//! `[TC-GW-SRV]` (сервер вернул error/незнакомый статус), `[TC-GW-SSH]` (транспорт —
//! ssh не запустился, клиентский пакет отсутствует, сеть и т.п.).

use std::path::Path;
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::Result;
use log::{debug, info};
use tauri::{Emitter, Manager};

use crate::commands::claude::auto_save_response;

/// Адрес gateway-узла (узел Б). Переопределяется `AURORA_NODE_B` для тестовых стендов —
/// см. `AURORA_NODE_B` в окружении сборки/дистрибутива тонкого клиента.
fn gateway_node() -> String {
    std::env::var("AURORA_NODE_B").unwrap_or_else(|_| "37.27.218.187".to_string())
}

/// Сгенерировать новую метку сессии для sticky-маршрутизации на сервере.
/// Не крипто-стойкость (детерминированной стойкости не требуется, session_key —
/// не секрет, см. `aurora_gateway::GatewayRequest`) — только уникальность в рамках
/// процесса: наносекунды + монотонный счётчик + PID.
fn generate_session_label(cabinet_id: &str) -> String {
    static COUNTER: AtomicU32 = AtomicU32::new(0);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let counter = COUNTER.fetch_add(1, Ordering::Relaxed);
    // Счётчик замешивается и в МЛАДШИЕ биты (аудит 2026-07-20): только `<< 32` делал его
    // вклад мёртвым — маска ниже берёт биты [0,31], и уникальность держалась бы лишь на
    // тике наносекунд (два «новых диалога» подряд могли получить одну метку → сервер
    // продолжил бы старую sticky-сессию вместо новой).
    let mixed = (nanos as u64) ^ ((counter as u64) << 32) ^ (counter as u64) ^ (std::process::id() as u64);
    format!("tc-{cabinet_id}-{:08x}", (mixed & 0xFFFF_FFFF) as u32)
}

/// Строка-событие `result` для канала `claude-stream-<cabinet>` — минимальный паритет
/// с финальной строкой stream-json локального CLI: ChatPanel добавляет assistant-пузырь
/// из `data.result` при `data.type === "result"` (ChatPanel.svelte, ветка result).
/// В gateway-режиме дельт нет — ответ приходит одной такой строкой.
fn build_result_event(text: &str) -> String {
    serde_json::json!({ "type": "result", "result": text }).to_string()
}

/// Замэппить ответ gateway в текст ответа или классифицированную ошибку. Чистая
/// функция без побочных эффектов (не трогает app_handle/ФС) — тестируется без сети.
fn map_response(resp: aurora_gateway::GatewayResponse) -> Result<String> {
    match resp.status.as_str() {
        // "done" — реальная форма боевого ответа сервера; "ok" — задокументированный
        // альтернативный статус контракта (aurora_gateway::GatewayResponse). Оба
        // означают успех, только если сервер не проставил error отдельно.
        "done" | "ok" if resp.error.is_none() => Ok(resp.text.unwrap_or_default()),
        "timeout" => anyhow::bail!(
            "[TC-GW-TIMEOUT] Превышено время ожидания ответа сервера – повторите позже."
        ),
        _ => {
            let detail = resp.error.unwrap_or(resp.status);
            anyhow::bail!("[TC-GW-SRV] {detail}")
        }
    }
}

/// Русское пояснение к ошибке транспортного уровня. `MissingClientFile` — единственный
/// вариант, для которого typовое сообщение `thiserror` недостаточно самообъясняюще для
/// пользователя тонкого клиента (остальные варианты уже человекочитаемы по-русски).
fn describe_transport_error(err: &aurora_gateway::TransportError) -> String {
    match err {
        aurora_gateway::TransportError::MissingClientFile { .. } => {
            // Путь называем ровно тот, откуда читаем (`app_data_dir()/client`).
            // Прежний текст отправлял пользователя «в папку рядом с приложением» —
            // туда файлы класть бесполезно, программа их там не ищет, и человек
            // добросовестно делает бесполезную работу (репорт владельца 27.07.2026).
            "Помощник недоступен: не установлены файлы доступа к серверу.\n\n\
             Что делать: запустите файл «install_client_package.ps1» из пакета доступа, \
             полученного в поддержке, и перезапустите программу.\n\n\
             Подробность для поддержки: файлы ожидаются в папке client каталога данных \
             программы (переменная APPDATA), а не рядом с исполняемым файлом."
                .to_string()
        }
        other => other.to_string(),
    }
}

/// Общая реализация обоих публичных входов: отправить промпт на gateway, замэппить
/// ответ, эмитировать `claude-done` (если не suppress_done) и сохранить экспорт
/// (если не suppress_export) — тот же контракт, что и `claude::run_claude_inner`.
#[allow(clippy::too_many_arguments)]
async fn execute(
    work_dir: &Path,
    prompt: &str,
    app_handle: tauri::AppHandle,
    cabinet_id: String,
    resume_session_id: Option<String>,
    suppress_export: bool,
    suppress_done: bool,
) -> Result<(Option<String>, String)> {
    let label = resume_session_id.unwrap_or_else(|| generate_session_label(&cabinet_id));
    let node = gateway_node();
    let client_dir = app_handle
        .path()
        .app_data_dir()
        .map_err(|e| anyhow::anyhow!("app_data_dir: {e}"))?
        .join("client");

    info!("Gateway-запрос [{cabinet_id}]: node={node}, label={label}");

    if !suppress_done {
        // Паритет CLI (system/init — первая строка stream-json локального пути): снимает
        // safety-таймер ChatPanel до долгого ответа сервера. Gateway промежуточных строк
        // не шлёт — без init таймер отменил бы длинную задачу и породил гонку UI
        // с поздним result (в CLI init приходит от запустившегося процесса).
        let _ = app_handle.emit(
            &format!("claude-stream-{cabinet_id}"),
            r#"{"type":"system","subtype":"init"}"#.to_string(),
        );
    }

    let cabinet_owned = cabinet_id.clone();
    let prompt_owned = prompt.to_string();
    let label_owned = label.clone();
    // Клиентский потолок ожидания (аудит 2026-07-20): SSH ServerAlive держит канал, пока
    // жив sshd, а НЕ forced-command — зависший движок оставил бы вызов без границы при уже
    // снятом safety-таймере UI (init выше). Паритет CLI-пути (30-мин timeout, claude.rs) +
    // запас над серверным poll-окном gateway (~30 мин), чтобы штатно первым приходил
    // серверный статус "timeout". Осиротевший blocking-поток при истечении не убивается
    // (ssh завершится сам по ServerAlive/серверному пределу); жёсткий kill — фаза 2.
    const GATEWAY_CALL_TIMEOUT_SECS: u64 = 1830;
    let joined = tokio::time::timeout(
        std::time::Duration::from_secs(GATEWAY_CALL_TIMEOUT_SECS),
        tokio::task::spawn_blocking(move || {
            aurora_gateway::send_to_gateway(&node, &client_dir, &cabinet_owned, &prompt_owned, &label_owned)
        }),
    )
    .await;
    let response = match joined {
        Err(_elapsed) => anyhow::bail!(
            "[TC-GW-TIMEOUT] Превышено время ожидания ответа сервера – повторите позже."
        ),
        Ok(join) => {
            join.map_err(|e| anyhow::anyhow!("[TC-GW-JOIN] Поток gateway-вызова прерван: {e}"))?
        }
    };

    let text = match response {
        Ok(resp) => map_response(resp)?,
        Err(err) => anyhow::bail!("[TC-GW-SSH] {}", describe_transport_error(&err)),
    };

    info!("Gateway-ответ получен [{cabinet_id}]: {} байт, label={label}", text.len());

    if !suppress_done {
        // Финальный текст в чат ДО done (порядок CLI-пути: result-строка из stdout,
        // затем claude-done). Без этого события send_message вернул бы Ok(()), а
        // ChatPanel не получил бы текст вовсе — ответ существовал бы только в exports.
        let _ = app_handle.emit(
            &format!("claude-stream-{cabinet_id}"),
            build_result_event(&text),
        );
        let _ = app_handle.emit(
            &format!("claude-done-{cabinet_id}"),
            serde_json::json!({ "exit_code": 0 }),
        );
    }

    if !suppress_export {
        auto_save_response(&app_handle, work_dir, &cabinet_id, prompt, &text, false);
    } else {
        debug!("Skipped auto-save for gateway response [{cabinet_id}]");
    }

    Ok((Some(label), text))
}

/// Зеркалит `claude::run_claude` для feature `thin`. `active_pids`/`model` — часть
/// локального CLI-мира (PID управляемого процесса, выбор модели CLI-флагом), gateway
/// их не использует: вызывающая сторона (`claude.rs`) передаёт их через `let _ = ...`.
pub async fn run_claude_gateway(
    work_dir: &Path,
    prompt: &str,
    app_handle: tauri::AppHandle,
    cabinet_id: String,
    resume_session_id: Option<String>,
    suppress_export: bool,
) -> Result<(Option<String>, String)> {
    execute(work_dir, prompt, app_handle, cabinet_id, resume_session_id, suppress_export, false).await
}

/// Зеркалит `claude::run_claude_pipeline` для feature `thin`. suppress_export и
/// suppress_done жёстко true — pipeline-фазы никогда не эмитят `claude-done` и не
/// пишут в exports/, финальный ответ строит пост-процессор (тот же контракт, что и
/// у CLI-пути: `run_claude_inner(..., true, true, None)`).
pub async fn run_claude_pipeline_gateway(
    work_dir: &Path,
    prompt: &str,
    app_handle: tauri::AppHandle,
    cabinet_id: String,
    resume_session_id: Option<String>,
) -> Result<(Option<String>, String)> {
    execute(work_dir, prompt, app_handle, cabinet_id, resume_session_id, true, true).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use aurora_gateway::{GatewayResponse, TransportError};

    // ── Генерация метки сессии ───────────────────────────────────────────────

    #[test]
    fn session_label_has_expected_prefix_and_length() {
        let label = generate_session_label("legal");
        assert!(label.starts_with("tc-legal-"), "формат префикса: {label}");
        // "tc-legal-" + 8 hex символов.
        assert_eq!(label.len(), "tc-legal-".len() + 8, "8 hex-символов метки: {label}");
    }

    #[test]
    fn session_label_is_unique_across_calls() {
        let a = generate_session_label("econometrist");
        let b = generate_session_label("econometrist");
        assert_ne!(a, b, "две подряд сгенерированные метки не должны совпадать");
    }

    // ── Строка-событие result для ChatPanel ─────────────────────────────────

    #[test]
    fn result_event_parses_back_with_type_and_text() {
        let raw = build_result_event("Ответ советника.");
        let v: serde_json::Value = serde_json::from_str(&raw).expect("строка должна быть валидным JSON");
        assert_eq!(v["type"], "result");
        assert_eq!(v["result"], "Ответ советника.");
    }

    #[test]
    fn result_event_escapes_quotes_and_newlines() {
        // Текст с кавычками/переносами не должен ломать JSON (ChatPanel делает JSON.parse).
        let raw = build_result_event("Строка с «кавычками», \"двойными\"\nи переносом");
        let v: serde_json::Value = serde_json::from_str(&raw).expect("экранирование сломано");
        assert_eq!(v["result"], "Строка с «кавычками», \"двойными\"\nи переносом");
    }

    // ── Маппинг ответа сервера ───────────────────────────────────────────────

    #[test]
    fn map_response_done_without_error_extracts_text() {
        let resp = GatewayResponse {
            status: "done".to_string(),
            text: Some("Ок.".to_string()),
            files: None,
            elapsed: Some(2.9),
            error: None,
        };
        assert_eq!(map_response(resp).unwrap(), "Ок.");
    }

    #[test]
    fn map_response_timeout_status_maps_to_tc_gw_timeout() {
        let resp = GatewayResponse { status: "timeout".to_string(), text: None, files: None, elapsed: None, error: None };
        let err = map_response(resp).unwrap_err();
        assert!(err.to_string().starts_with("[TC-GW-TIMEOUT]"), "получено: {err}");
    }

    #[test]
    fn map_response_error_status_maps_to_tc_gw_srv_with_detail() {
        let resp = GatewayResponse {
            status: "error".to_string(),
            text: None,
            files: None,
            elapsed: None,
            error: Some("кабинет недоступен".to_string()),
        };
        let err = map_response(resp).unwrap_err();
        assert_eq!(err.to_string(), "[TC-GW-SRV] кабинет недоступен");
    }

    // ── Пояснение транспортной ошибки ────────────────────────────────────────

    #[test]
    fn missing_client_file_gets_russian_explanation() {
        let err = TransportError::MissingClientFile { path: std::path::PathBuf::from("client_key") };
        let msg = describe_transport_error(&err);

        assert!(msg.contains("не установлены файлы доступа"), "получено: {msg}");
        assert!(
            msg.contains("install_client_package.ps1"),
            "текст обязан называть, ЧТО запустить: {msg}"
        );
        // Прежний текст звал класть файлы «рядом с приложением», а читаются они из
        // каталога данных. Человек делал бесполезную работу и оставался без помощника.
        assert!(
            !msg.contains("рядом с приложением"),
            "нельзя отправлять пользователя не туда: {msg}"
        );
        assert!(msg.contains("APPDATA"), "верный путь обязан быть назван: {msg}");
    }
}
