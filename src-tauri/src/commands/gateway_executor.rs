//! Облачный исполнитель кабинета (признак сборки `thin`, ADR-048).
//!
//! Кабинет-советник исполняется на нашем сервере, а не локальным Claude Code: у
//! пользователя тонкой поставки его нет по построению. Всё остальное в продукте
//! не меняется — расчётная часть (MMM-пайплайн) как была местной, так и остаётся.
//!
//! ## Что здесь есть и чего здесь нет
//! Обмен с сервером — лента, откат на опрос, склейка приращений, докачка файлов,
//! повторы, отмена, перевод кодов отказа — живёт в общем слое Core
//! (`aurora_gateway::cloud`). Здесь остаётся то, что принадлежит продукту:
//! события интерфейса, метка диалога, сбор вложений «Входящих» и сохранение
//! ответа.
//!
//! ## Чем это отличается от прежнего пути
//! Прежде адаптер работал по контракту «отправил и жди»: одно соединение до
//! получаса, финальный текст одним куском, ни ленты, ни отмены, ни файлов
//! пользователя, ни выбора модели. Клиент на PC204 из-за этого и не заработал:
//! рукопожатие SSH упиралось в порог посредника. Теперь путь идёт обычным HTTPS.
//!
//! ## Коды ошибок
//! В стиле `claude.rs` (`[CL-...]`): `[TC-GW-NET]` — связь, `[TC-GW-SRV]` — сервер
//! отказал, `[TC-GW-AUTH]` — нет доступа на этой машине.

use std::path::Path;
use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::Result;
use aurora_gateway::cloud::{
    check_ticket, decide_ticket, CloudClient, DeviceIdentity, IdentityStore, InputFile, JobRequest, TicketDecision,
};
use log::{debug, info, warn};
use tauri::{Emitter, Manager};

use crate::commands::claude::auto_save_response;

/// Адрес входа облачного шлюза. Переопределяется `AURORA_CLOUD_URL` для стендов.
fn gateway_base_url() -> String {
    std::env::var("AURORA_CLOUD_URL").unwrap_or_else(|_| "https://rag.auroraai.pro/cloud".to_string())
}

/// Безопасный потолок вложения. Служба принимает до 32 МБ на файл и 64 МБ на
/// задание; берём с запасом, чтобы отказ приходил здесь, с внятным текстом, а не
/// с сервера на середине отправки.
const INPUT_FILE_LIMIT: usize = 24 * 1024 * 1024;
const INPUTS_TOTAL_LIMIT: usize = 48 * 1024 * 1024;

// ── Отмена: прекращает работу НА СЕРВЕРЕ ────────────────────────────────────────
//
// 🔴 Прежде отмена в тонкой поставке была невозможна по построению: команда
// отмены читает карту процессов, а её наполняет только локальный путь. Кнопка при
// этом рисовалась и выглядела рабочей, а задание на сервере продолжало считаться,
// жгло окно подписки и держало одно из трёх мест.

/// Что известно про идущую работу кабинета.
///
/// 🔴 Работа начинается ЗАДОЛГО до того, как у неё появляется номер: сперва
/// подтверждается доступ, потом идёт сетевой круг за сведениями о сервере,
/// потом читаются и отправляются вложения — на десятках мегабайт это минуты.
/// Прежде отметка ставилась только при извещении о принятом задании, и всё это
/// окно отмена докладывала «нечего останавливать», а работа доходила до конца и
/// сохраняла отчёт. Поэтому отметка ставится ПЕРЕД началом работы, а номер
/// добавляется к ней позже.
#[derive(Default)]
struct ActiveWork {
    /// Номер задания на сервере. `None` — задание ещё не принято.
    job_id: Option<String>,
    /// Пользователь попросил остановиться.
    cancelled: bool,
}

fn active_jobs(
) -> &'static std::sync::Mutex<std::collections::HashMap<String, std::collections::HashMap<u64, ActiveWork>>>
{
    static R: std::sync::OnceLock<
        std::sync::Mutex<std::collections::HashMap<String, std::collections::HashMap<u64, ActiveWork>>>,
    > = std::sync::OnceLock::new();
    R.get_or_init(|| std::sync::Mutex::new(std::collections::HashMap::new()))
}

/// Отметить начало работы кабинета. Возвращает её метку в реестре.
fn begin_work(cabinet_id: &str) -> u64 {
    static NEXT: AtomicU64 = AtomicU64::new(1);
    let token = NEXT.fetch_add(1, Ordering::Relaxed);
    active_jobs()
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .entry(cabinet_id.to_string())
        .or_default()
        .insert(token, ActiveWork::default());
    token
}

/// Привязать к начатой работе номер задания, когда сервер его выдал.
fn attach_job_id(cabinet_id: &str, token: u64, job_id: &str) {
    let mut jobs = active_jobs().lock().unwrap_or_else(|e| e.into_inner());
    if let Some(work) = jobs.get_mut(cabinet_id).and_then(|m| m.get_mut(&token)) {
        work.job_id = Some(job_id.to_string());
    }
}

/// Просил ли пользователь остановить именно эту работу.
fn is_cancelled(cabinet_id: &str, token: u64) -> bool {
    active_jobs()
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .get(cabinet_id)
        .and_then(|m| m.get(&token))
        .map(|w| w.cancelled)
        .unwrap_or(false)
}

fn forget_work(cabinet_id: &str, token: u64) {
    let mut jobs = active_jobs().lock().unwrap_or_else(|e| e.into_inner());
    if let Some(set) = jobs.get_mut(cabinet_id) {
        set.remove(&token);
        if set.is_empty() {
            jobs.remove(cabinet_id);
        }
    }
}

/// Учёт одной идущей работы. Снимает свою отметку на ЛЮБОМ выходе, включая
/// ошибку и панику: оставленная отметка заставила бы отмену докладывать успех там,
/// где никто не работает.
struct WorkGuard {
    cabinet_id: String,
    token: u64,
}

impl WorkGuard {
    fn new(cabinet_id: &str) -> Self {
        Self { cabinet_id: cabinet_id.to_string(), token: begin_work(cabinet_id) }
    }

    fn attach(&self, job_id: &str) {
        attach_job_id(&self.cabinet_id, self.token, job_id);
    }

    fn cancelled(&self) -> bool {
        is_cancelled(&self.cabinet_id, self.token)
    }
}

impl Drop for WorkGuard {
    fn drop(&mut self) {
        forget_work(&self.cabinet_id, self.token);
    }
}

/// Остановить работу кабинета на сервере. `true` — работа шла и отмена отправлена.
///
/// Отправка идёт отдельной задачей: команда отмены в интерфейсе синхронная, а ждать
/// сети в ней значило бы подвесить окно ради ответа, который пользователю не нужен.
pub fn request_cancel(app_handle: &tauri::AppHandle, cabinet_id: &str) -> bool {
    // 🔴 Отметка «остановиться» ставится ПЕРВЫМ делом и для работы, у которой
    // номера задания ещё нет. Прежде отмена в этом окне докладывала «нечего
    // останавливать», а работа доходила до конца и сохраняла отчёт, которого
    // пользователь уже не ждал.
    let jobs: Vec<String> = {
        let mut registry = active_jobs().lock().unwrap_or_else(|e| e.into_inner());
        let Some(works) = registry.get_mut(cabinet_id) else {
            return false;
        };
        if works.is_empty() {
            return false;
        }
        let mut ids = Vec::new();
        for work in works.values_mut() {
            work.cancelled = true;
            if let Some(id) = &work.job_id {
                ids.push(id.clone());
            }
        }
        ids
    };

    // Номера ещё нет — останавливать на сервере нечего, но ожидание у клиента
    // уже прекращено отметкой выше, и работа не сохранит отчёт.
    if jobs.is_empty() {
        return true;
    }

    let identity = match identity_for(app_handle) {
        Ok(identity) => identity,
        Err(e) => {
            // Доступа нет — на сервере остановить нечем, но ожидание у клиента
            // прекращено отметкой выше: отчёт не сохранится и не всплывёт.
            warn!("Отмена не отправлена на сервер [{cabinet_id}]: {e}");
            return true;
        }
    };
    let base = gateway_base_url();
    let cabinet = cabinet_id.to_string();
    tauri::async_runtime::spawn(async move {
        let client = match CloudClient::new(&base, identity) {
            Ok(client) => client,
            Err(e) => {
                warn!("Отмена не отправлена [{cabinet}]: {e}");
                return;
            }
        };
        for job_id in jobs {
            match client.cancel(&job_id).await {
                Ok(_) => info!("Задание остановлено на сервере [{cabinet}]: {job_id}"),
                Err(e) => warn!("Задание не удалось остановить [{cabinet}] {job_id}: {e}"),
            }
        }
    });
    true
}

/// Новая метка диалога. Не криптостойкость (метка не секрет) — только уникальность
/// в рамках процесса: наносекунды + счётчик + идентификатор процесса.
fn generate_session_label(cabinet_id: &str) -> String {
    static COUNTER: AtomicU32 = AtomicU32::new(0);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let counter = COUNTER.fetch_add(1, Ordering::Relaxed);
    // Счётчик замешивается и в младшие биты: только сдвиг на 32 сделал бы его вклад
    // мёртвым (маска ниже берёт младшие 32 бита), и два «новых диалога» подряд могли
    // бы получить одну метку — сервер продолжил бы старую липкую сессию вместо новой.
    let mixed = (nanos as u64)
        ^ ((counter as u64) << 32)
        ^ (counter as u64)
        ^ (std::process::id() as u64);
    format!("tc-{cabinet_id}-{:08x}", (mixed & 0xFFFF_FFFF) as u32)
}

/// Событие потока в том же виде, в каком его шлёт локальный путь.
/// `text` — весь накопленный ответ; интерфейс заменит показанное целиком.
fn build_stream_event(text: &str) -> String {
    serde_json::json!({
        "type": "assistant",
        "message": { "content": [ { "type": "text", "text": text } ] }
    })
    .to_string()
}

/// Финальная строка — паритет с последней строкой локального потока.
fn build_result_event(text: &str) -> String {
    serde_json::json!({ "type": "result", "result": text }).to_string()
}

/// С каким усилием считать: настройка пользователя, как и на локальном пути.
fn effort_for(app_handle: &tauri::AppHandle) -> Option<String> {
    app_handle
        .path()
        .app_config_dir()
        .ok()
        .and_then(|d| crate::commands::user_config::load(&d).model_effort)
}

// ── Вложения «Входящих» ─────────────────────────────────────────────────────────
//
// 🔴 Прежде файлы пользователя на сервер не уезжали вовсе: канала передачи в
// прежнем контракте не было. Кабинет-советник, которому положили выгрузку с
// цифрами, работал по одному тексту запроса — и отвечал общими словами там, где
// от него ждали разбора конкретных данных.

/// Отчего вложение не уехало и что об этом сказать пользователю.
#[derive(Debug, PartialEq, Eq)]
pub struct SkippedInput {
    pub name: String,
    pub reason: String,
    pub action: String,
}

/// Собрать файлы «Входящих», которые уедут в работу.
///
/// Чистая функция намеренно: событий не шлёт и окна не требует, поэтому
/// проверяется тестом, который зовёт ровно тот код, что работает в бою.
fn collect_inputs(work_dir: &Path, cabinet_id: &str) -> (Vec<InputFile>, Vec<SkippedInput>) {
    let mut files: Vec<InputFile> = Vec::new();
    let mut skipped: Vec<SkippedInput> = Vec::new();
    let mut total: usize = 0;

    let inbox = work_dir.join("inbox");
    let entries = match std::fs::read_dir(&inbox) {
        Ok(entries) => entries,
        Err(_) => return (files, skipped),
    };

    // Порядок обхода папки операционной системой не определён — упорядочиваем,
    // чтобы и отправка, и перечень в предупреждении не менялись от запуска к запуску.
    let mut names: Vec<String> = entries
        .filter_map(|e| e.ok())
        .filter(|e| e.path().is_file())
        .filter_map(|e| e.file_name().to_str().map(|s| s.to_string()))
        .collect();
    names.sort();

    for name in names {
        let path = inbox.join(&name);
        let bytes = match std::fs::read(&path) {
            Ok(bytes) => bytes,
            Err(e) => {
                warn!("Файл «{name}» не прочитан [{cabinet_id}]: {e}");
                skipped.push(SkippedInput {
                    name: name.clone(),
                    reason: format!("файл «{name}» не удалось прочитать, и в работу он не уехал"),
                    action: "Проверьте файл во «Входящих» и добавьте его заново.".to_string(),
                });
                continue;
            }
        };
        if bytes.len() > INPUT_FILE_LIMIT || total + bytes.len() > INPUTS_TOTAL_LIMIT {
            warn!("Файл «{name}» не уедет [{cabinet_id}]: {} байт", bytes.len());
            skipped.push(SkippedInput {
                name: name.clone(),
                reason: format!("файл «{name}» слишком велик и в работу не уехал"),
                action: "Уберите его из «Входящих» или замените файлом поменьше.".to_string(),
            });
            continue;
        }
        total += bytes.len();
        files.push(InputFile { name, bytes });
    }

    (files, skipped)
}

// ── Доступ к серверу ────────────────────────────────────────────────────────────

/// Личность этой машины: билет лицензии и ключ устройства.
///
/// Билет — тот самый подписанный ответ входа, который продукт уже получает и
/// проверяет. Ключ устройства создаётся один раз и хранится рядом: перехваченный
/// билет без него бесполезен.
fn identity_for(app_handle: &tauri::AppHandle) -> Result<DeviceIdentity> {
    let data_dir = app_handle
        .path()
        .app_data_dir()
        .map_err(|e| anyhow::anyhow!("[TC-GW-AUTH] каталог данных недоступен: {e}"))?;
    let store = IdentityStore::new(data_dir.join("cloud"));

    // 🔴 Сохранённый билет проверяется на годность ДО предъявления серверу. Он
    // живёт файлом и сам не обновляется: без проверки продукт после продления
    // лицензии продолжал слать СТАРЫЙ билет, получал отказ и оставался
    // неработающим до ручной чистки каталога данных — человек видел «доступ не
    // подтверждён» сразу после того, как заплатил. Второй случай — кэш входа от
    // прежней версии продукта, где поля подписи не было вовсе.
    let saved = match store.ticket() {
        Ok(saved) => saved,
        Err(e) => {
            debug!("Билет не прочитан, берём заново: {e}");
            None
        }
    };
    // Решение о годности принимает общий слой: рядом с каталогами и сетью его
    // нельзя было бы предъявить проверке, а цена ошибки — неработающая программа
    // сразу после того, как человек продлил лицензию.
    let ticket = match decide_ticket(saved.as_deref(), &now_utc()) {
        TicketDecision::UseSaved => saved.expect("годный билет обязан быть на месте"),
        TicketDecision::ForgetAndRefresh(problem) => {
            info!("Сохранённый билет негоден ({problem:?}) — беру заново");
            // Негодный билет убираем: иначе он останется лежать и будет мешать
            // при каждом следующем запуске, если взять новый не вышло.
            let _ = store.forget_ticket();
            refresh_ticket(app_handle, &store)?
        }
        TicketDecision::Refresh => refresh_ticket(app_handle, &store)?,
    };
    let key = store
        .device_key()
        .map_err(|e| anyhow::anyhow!("[TC-GW-AUTH] ключ устройства недоступен: {e}"))?;

    DeviceIdentity::new(&ticket, &key).map_err(|e| {
        anyhow::anyhow!(
            "[TC-GW-AUTH] Доступ к облачному помощнику не подтверждён.\n\n\
             Что делать: откройте Настройки и активируйте лицензию заново. \
             Подробность для поддержки: {e}"
        )
    })
}

/// Взять билет из ответа лицензионного входа и сохранить его.
fn refresh_ticket(app_handle: &tauri::AppHandle, store: &IdentityStore) -> Result<String> {
    let config_dir = app_handle
        .path()
        .app_config_dir()
        .map_err(|e| anyhow::anyhow!("[TC-GW-AUTH] каталог настроек недоступен: {e}"))?;
    let grant = crate::commands::online_auth::cached_grant(&config_dir).ok_or_else(|| {
        anyhow::anyhow!(
            "[TC-GW-AUTH] Лицензия на этой машине не подтверждена, поэтому сервер \
             не примет запрос.\n\nЧто делать: откройте Настройки и активируйте лицензию."
        )
    })?;
    let ticket = crate::commands::online_auth::build_cloud_ticket(&grant)
        .map_err(|e| anyhow::anyhow!("[TC-GW-AUTH] билет доступа не собран: {e}"))?;
    if let Err(e) = store.save_ticket(&ticket) {
        // Не смертельно: билет соберётся заново при следующем запуске.
        warn!("Билет не сохранён: {e}");
    }
    Ok(ticket)
}

// ── Исполнение ──────────────────────────────────────────────────────────────────

/// Общая реализация обоих входов: поставить задание, вести поток, забрать файлы.
#[allow(clippy::too_many_arguments)]
async fn execute(
    work_dir: &Path,
    prompt: &str,
    app_handle: tauri::AppHandle,
    cabinet_id: String,
    resume_session_id: Option<String>,
    model: Option<String>,
    suppress_export: bool,
    suppress_done: bool,
) -> Result<(Option<String>, String)> {
    let label = resume_session_id.unwrap_or_else(|| generate_session_label(&cabinet_id));
    // 🔴 Отметка работы ставится ПЕРВЫМ действием, до подтверждения доступа и
    // любых сетевых кругов: всё это время пользователь уже видит индикатор и
    // вправе нажать «Остановить». Прежде отметка появлялась только с номером
    // задания, и отмена в этом окне докладывала «нечего останавливать».
    let work = WorkGuard::new(&cabinet_id);
    let identity = identity_for(&app_handle)?;
    let base = gateway_base_url();
    let client = CloudClient::new(&base, identity)
        .map_err(|e| anyhow::anyhow!("[TC-GW-NET] {}", e.user_text()))?;

    info!("Облачный запрос [{cabinet_id}]: вход={base}, метка={label}");

    if !suppress_done {
        // Паритет с локальным путём: первая строка снимает предохранительный таймер
        // интерфейса. Без неё долгий ответ сервера успел бы «отменить» задачу в
        // интерфейсе и породить гонку с приходящим позже результатом.
        let _ = app_handle.emit(
            &format!("claude-stream-{cabinet_id}"),
            r#"{"type":"system","subtype":"init"}"#.to_string(),
        );
    }

    let (inputs, skipped) = collect_inputs(work_dir, &cabinet_id);
    for item in &skipped {
        let _ = app_handle.emit(
            &format!("inbox-attachments-skipped-{cabinet_id}"),
            serde_json::json!({ "name": item.name, "reason": item.reason, "action": item.action }),
        );
    }

    let effort = effort_for(&app_handle);
    let request = JobRequest {
        cabinet: &cabinet_id,
        prompt,
        model: model.as_deref(),
        effort: effort.as_deref(),
        session_key: Some(&label),
        // Ключ отправки уникален на попытку: повтор с ним не рождает второе задание,
        // и обрыв связи после постановки перестаёт быть потерянной работой.
        idempotency_key: format!("{label}-{}", short_stamp()),
        inputs: &inputs,
    };

    let mut shown = String::new();
    let outcome = {
        let cabinet_for_stream = cabinet_id.clone();
        let handle_for_stream = app_handle.clone();
        client
            .run_job_watched(
                &request,
                |piece| {
                    shown.push_str(piece);
                    if !suppress_done {
                        let _ = handle_for_stream.emit(
                            &format!("claude-stream-{cabinet_for_stream}"),
                            build_stream_event(&shown),
                        );
                    }
                },
                |job_id| work.attach(job_id),
            )
            .await
    };

    // 🔴 Накопленный текст не выбрасывается ни отменой, ни сбоем связи. Прежде
    // ошибка прогона рушила всё через `?`, и работа, которую пользователь уже
    // читал на экране, пропадала целиком — включая случай серверного потолка,
    // ради которого правило и вводилось.
    if work.cancelled() {
        info!("Работа остановлена пользователем [{cabinet_id}]");
        // 🔴 Сигнал завершения шлётся и при отмене. Интерфейс держит признак
        // «остановлено» до него: без сигнала признак висит, и СЛЕДУЮЩИЙ ответ
        // съедается им — не попадает ни в чат, ни в историю. Отчёт при этом не
        // сохраняем: работы, которую пользователь остановил, в файлах быть не должно.
        if !suppress_done {
            let _ = app_handle.emit(
                &format!("claude-done-{cabinet_id}"),
                serde_json::json!({ "exit_code": 0, "cancelled": true }),
            );
        }
        return Ok((None, shown));
    }
    let state = match outcome {
        Ok(state) => state,
        Err(e) => {
            warn!("Облачное обращение не удалось [{cabinet_id}]: {e}");
            if shown.trim().is_empty() {
                anyhow::bail!("[TC-GW-NET] {}", e.user_text());
            }
            let text = format!("{shown}\n\n---\n**Ответ неполный.** {}", e.user_text());
            if !suppress_done {
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
            }
            return Ok((Some(label), text));
        }
    };

    if state.status == "cancelled" {
        // Пользователь остановил работу. Отчёт НЕ сохраняем и метку НЕ возвращаем:
        // следующий вопрос обязан начать новый диалог, а не продолжить отменённый.
        info!("Задание остановлено пользователем [{cabinet_id}]");
        if !suppress_done {
            let _ = app_handle.emit(
                &format!("claude-done-{cabinet_id}"),
                serde_json::json!({ "exit_code": 0, "cancelled": true }),
            );
        }
        return Ok((None, state.text));
    }
    if !state.is_success() {
        let (text, hidden) = state.failure_text();
        if let Some(internal) = hidden {
            warn!("шлюз: внутренняя диагностика узла (пользователю не показана): {internal}");
        }
        anyhow::bail!("[TC-GW-SRV] {text}");
    }

    let text = state.text.clone();
    info!("Ответ получен [{cabinet_id}]: {} байт, задание {}", text.len(), state.job_id);

    // Выгрузка ложится в рабочую папку — дальше продукт работает с ней как с
    // локальной. Не доехавший файл не рушит ответ, но и не молчит.
    let (saved, failed) = client.download_all(&state, &work_dir.join("exports")).await;
    for name in &saved {
        info!("Файл выгрузки получен [{cabinet_id}]: {name}");
    }
    for (name, why) in &failed {
        warn!("Файл «{name}» не доехал [{cabinet_id}]: {why}");
    }

    if !suppress_done {
        // Финальный текст в чат ДО готовности (порядок локального пути): иначе
        // интерфейс получил бы сигнал завершения раньше самого ответа.
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
        debug!("Автосохранение ответа пропущено [{cabinet_id}]");
    }

    Ok((Some(label), text))
}

/// Текущее время в том виде, в каком его пишет сервер.
///
/// Своя сборка вместо библиотеки дат: ради одной сверки тянуть зависимость в
/// продукт дороже, чем записать правило. Точность до секунды здесь избыточна,
/// а часовой пояс всегда всемирный — билет подписан именно так.
fn now_utc() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let (days, rest) = (secs / 86_400, secs % 86_400);
    let (hh, mm, ss) = (rest / 3600, (rest % 3600) / 60, rest % 60);

    // Дни от 1970-01-01 в календарную дату (алгоритм Хиннанта, без зависимостей).
    let z = days as i64 + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };

    format!("{y:04}-{m:02}-{d:02}T{hh:02}:{mm:02}:{ss:02}Z")
}

/// Короткая отметка времени для ключа отправки.
fn short_stamp() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("{:x}", (nanos & 0xFFFF_FFFF) as u32)
}

/// Зеркалит `claude::run_claude` при включённом облачном модуле.
/// `active_pids` — часть локального мира (управляемый процесс); облачный путь его
/// не использует, а вот модель теперь доезжает до сервера.
pub async fn run_claude_gateway(
    work_dir: &Path,
    prompt: &str,
    app_handle: tauri::AppHandle,
    cabinet_id: String,
    resume_session_id: Option<String>,
    suppress_export: bool,
    model: Option<String>,
) -> Result<(Option<String>, String)> {
    execute(work_dir, prompt, app_handle, cabinet_id, resume_session_id, model,
            suppress_export, false).await
}

/// Зеркалит `claude::run_claude_pipeline`. Фазы конвейера никогда не сообщают о
/// готовности и не пишут в выгрузку — финальный ответ строит пост-обработчик.
pub async fn run_claude_pipeline_gateway(
    work_dir: &Path,
    prompt: &str,
    app_handle: tauri::AppHandle,
    cabinet_id: String,
    resume_session_id: Option<String>,
) -> Result<(Option<String>, String)> {
    execute(work_dir, prompt, app_handle, cabinet_id, resume_session_id, None, true, true).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn session_label_has_expected_prefix_and_length() {
        let label = generate_session_label("econometrist");
        assert!(label.starts_with("tc-econometrist-"), "формат префикса: {label}");
        assert_eq!(label.len(), "tc-econometrist-".len() + 8, "8 знаков метки: {label}");
    }

    #[test]
    fn session_label_is_unique_across_calls() {
        let a = generate_session_label("econometrist");
        let b = generate_session_label("econometrist");
        assert_ne!(a, b, "две подряд метки не должны совпасть — сервер продолжит старый диалог");
    }

    #[test]
    fn result_event_parses_back_with_type_and_text() {
        let raw = build_result_event("Ответ советника.");
        let v: serde_json::Value = serde_json::from_str(&raw).expect("строка должна быть верным JSON");
        assert_eq!(v["type"], "result");
        assert_eq!(v["result"], "Ответ советника.");
    }

    #[test]
    fn result_event_escapes_quotes_and_newlines() {
        let raw = build_result_event("Строка с «кавычками», \"двойными\"\nи переносом");
        let v: serde_json::Value = serde_json::from_str(&raw).expect("экранирование сломано");
        assert_eq!(v["result"], "Строка с «кавычками», \"двойными\"\nи переносом");
    }

    #[test]
    fn stream_event_matches_what_the_interface_expects() {
        let raw = build_stream_event("Медиасплит по каналам");
        let v: serde_json::Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(v["type"], "assistant");
        assert_eq!(v["message"]["content"][0]["text"], "Медиасплит по каналам");
    }

    // ── Отмена ──────────────────────────────────────────────────────────────

    #[test]
    fn cancel_reaches_work_that_has_no_job_number_yet() {
        // 🔴 Найдено внешним аудитом: работа начинается задолго до появления
        // номера, и прежде отмена в этом окне докладывала «нечего
        // останавливать», а работа доходила до конца и сохраняла отчёт.
        let work = WorkGuard::new("econometrist");
        assert!(!work.cancelled());

        let mut registry = active_jobs().lock().unwrap();
        let works = registry.get_mut("econometrist").expect("работа обязана быть в реестре");
        for entry in works.values_mut() {
            assert!(entry.job_id.is_none());
            entry.cancelled = true;
        }
        drop(registry);

        assert!(work.cancelled(), "отмена не дошла до работы без номера");
    }

    #[test]
    fn work_leaves_no_trace_in_the_registry() {
        {
            let work = WorkGuard::new("advisor");
            work.attach("job-777");
            assert_eq!(active_jobs().lock().unwrap().get("advisor").map(|m| m.len()), Some(1));
        }
        assert!(
            active_jobs().lock().unwrap().get("advisor").is_none(),
            "отметка осталась — отмена доложит успех там, где никто не работает"
        );
    }

    // ── Вложения «Входящих» ─────────────────────────────────────────────────

    fn work_dir_with_inbox() -> tempfile::TempDir {
        let tmp = tempfile::tempdir().expect("временная папка");
        std::fs::create_dir_all(tmp.path().join("inbox")).expect("папка inbox");
        tmp
    }

    #[test]
    fn attachments_travel_with_the_job() {
        // 🔴 Прежде файлы пользователя не уезжали вовсе: кабинет-советник получал
        // один текст запроса и отвечал общими словами там, где ждали разбора цифр.
        let tmp = work_dir_with_inbox();
        let inbox = tmp.path().join("inbox");
        std::fs::write(inbox.join("вложение.csv"), "канал;бюджет\n".as_bytes()).unwrap();
        std::fs::write(inbox.join("бриф.docx"), [0u8, 1u8]).unwrap();

        let (files, skipped) = collect_inputs(tmp.path(), "econometrist");
        assert!(skipped.is_empty(), "пропускать нечего: {skipped:?}");
        let names: Vec<&str> = files.iter().map(|f| f.name.as_str()).collect();
        assert_eq!(names, vec!["бриф.docx", "вложение.csv"], "уехало не всё: {names:?}");
        assert_eq!(
            files[1].bytes,
            "канал;бюджет\n".as_bytes(),
            "файл обязан уехать содержимым, а не именем"
        );
    }

    #[test]
    fn oversized_attachment_is_reported_not_dropped_silently() {
        let tmp = work_dir_with_inbox();
        let inbox = tmp.path().join("inbox");
        std::fs::write(inbox.join("маленький.csv"), b"a,b\n").unwrap();
        std::fs::write(inbox.join("огромный.bin"), vec![7u8; INPUT_FILE_LIMIT + 1]).unwrap();

        let (files, skipped) = collect_inputs(tmp.path(), "econometrist");
        assert_eq!(files.len(), 1, "маленький файл обязан уехать: {files:?}");
        assert_eq!(skipped.len(), 1);
        assert!(
            skipped[0].reason.contains("огромный.bin"),
            "пользователь обязан узнать, какой файл не уехал: {}",
            skipped[0].reason
        );
        assert!(!skipped[0].action.is_empty(), "предупреждение обязано называть действие");
    }

    #[test]
    fn total_size_is_capped_across_files() {
        let tmp = work_dir_with_inbox();
        let inbox = tmp.path().join("inbox");
        let chunk = INPUTS_TOTAL_LIMIT / 3 + 1;
        for name in ["а.bin", "б.bin", "в.bin", "г.bin"] {
            std::fs::write(inbox.join(name), vec![1u8; chunk]).unwrap();
        }

        let (files, skipped) = collect_inputs(tmp.path(), "econometrist");
        assert!(files.len() < 4, "сумма вложений потолок не переросла: {} файлов", files.len());
        assert!(!skipped.is_empty(), "о неуехавшем обязано быть сказано");
    }

    #[test]
    fn empty_inbox_reports_nothing(
    ) {
        let tmp = work_dir_with_inbox();
        let (files, skipped) = collect_inputs(tmp.path(), "econometrist");
        assert!(files.is_empty());
        assert!(skipped.is_empty(), "пустые «Входящие» — сообщать не о чем: {skipped:?}");
    }

    #[test]
    fn missing_inbox_is_not_an_error() {
        let tmp = tempfile::tempdir().unwrap();
        let (files, skipped) = collect_inputs(tmp.path(), "econometrist");
        assert!(files.is_empty());
        assert!(skipped.is_empty(), "папки нет — это норма, а не сбой: {skipped:?}");
    }

    // Проверок на перевод отказов здесь намеренно нет: и таблица кодов, и разбор
    // «русский текст сервера против внутренней диагностики» живут в Core
    // (`JobState::failure_text`, `CloudError::user_text`) и проверяются там. Копия
    // проверок в продукте зеленела бы независимо от того, что показывает общий слой.
}
