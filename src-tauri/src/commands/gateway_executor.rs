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
    cabinets_mismatch_text, inputs_fingerprint, check_cabinets_version, decide_ticket, missing_exports_text,
    unconfirmed_cancel_text, CabinetsVersionCheck, CloudClient, CloudError, DeviceIdentity,
    IdentityStore, InputFile, JobRequest, JobState, TicketDecision, TicketProblem,
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

/// Что сказать человеку, если хоть одно вложение не доехало, — и говорить ли.
///
/// 🔴 Чистая функция намеренно. Решение «работать нельзя» иначе живёт внутри
/// `execute`, рядом с окном, сетью и билетом, и проверить его нечем: мутация
/// «недоехавшее пропускаем» пережила бы любой прогон. Здесь же она краснеет.
fn refusal_for_skipped(skipped: &[SkippedInput]) -> Option<String> {
    let first = skipped.first()?;
    let others = match skipped.len() {
        1 => String::new(),
        n => format!(" Не уехало файлов: {n}."),
    };
    Some(format!(
        "Работа не начата: {}.{others}\n\nЧто делать: {}",
        first.reason, first.action
    ))
}

/// Файл слишком велик сам по себе.
fn oversized_warning(name: &str) -> SkippedInput {
    SkippedInput {
        name: name.to_string(),
        reason: format!("файл «{name}» слишком велик"),
        action: "Уберите его из «Входящих» или замените файлом поменьше.".to_string(),
    }
}

/// Что лежит во «Входящих» — по метаданным, без чтения содержимого.
///
/// 🔴 Именно «без чтения» и есть смысл: сверять набор, читая тридцать мегабайт,
/// значило бы съесть ту экономию, ради которой сверка и делается.
fn inbox_signature(work_dir: &Path) -> Vec<(String, u64, u64)> {
    let inbox = work_dir.join("inbox");
    let Ok(entries) = std::fs::read_dir(&inbox) else {
        return Vec::new();
    };
    let mut items = Vec::new();
    for entry in entries.filter_map(|e| e.ok()).filter(|e| e.path().is_file()) {
        let Some(name) = entry.file_name().to_str().map(|s| s.to_string()) else {
            // Нечитаемое имя — повод пойти обычным путём: там оно будет названо
            // человеку, а здесь молчаливое совпадение отпечатков скрыло бы файл.
            return Vec::new();
        };
        let Ok(meta) = entry.metadata() else {
            return Vec::new();
        };
        // 🔴 Наносекунды, а не секунды: усечение до секунды даёт ложное «набор не
        // менялся» для правки в пределах той же секунды с тем же размером — и
        // работа пойдёт по ПРЕЖНЕЙ версии файла, выглядя законченной (INV-50).
        // Найдено внешним аудитом; сама точность бесплатна, `SystemTime` её несёт.
        let modified = meta
            .modified()
            .ok()
            .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
            .map(|d| d.as_nanos() as u64)
            .unwrap_or(0);
        items.push((name, meta.len(), modified));
    }
    items
}

/// Какой набор вложений уже уехал в этот диалог: метка диалога → отпечаток.
///
/// 🔴 Живёт в памяти процесса намеренно. После перезапуска программы отпечатка
/// нет, и файлы уедут заново — сторона безопасная. Помнить дольше, чем живёт
/// рабочая папка на сервере, значило бы однажды сказать «вложения уже там», когда
/// их там нет, и работа пошла бы по пустой папке.
fn sent_inputs() -> &'static std::sync::Mutex<std::collections::HashMap<String, String>> {
    static R: std::sync::OnceLock<
        std::sync::Mutex<std::collections::HashMap<String, String>>,
    > = std::sync::OnceLock::new();
    R.get_or_init(|| std::sync::Mutex::new(std::collections::HashMap::new()))
}

/// Судьба памяти о наборе вложений на выходе из работы.
///
/// 🔴 Страж, а не вызов в каждой ветке — и в этом вся суть правки. Прежде память
/// обновлялась ОДНИМ блоком в конце, то есть только при успехе: ни отмена, ни сбой
/// связи, ни отказ сервера её не трогали. Стоило сборщику простоя на узле убрать
/// рабочую папку, и сервер честно отвечал «файлы этого диалога не найдены на
/// сервере – отправьте их заново», а память оставалась прежней: следующий вопрос
/// уходил с тем же признаком и получал тот же отказ. Круг, из которого человек не
/// выходит сам — он делает ровно то, о чём просит текст.
///
/// Снятие происходит при разрушении стража, поэтому любая ветка выхода — включая
/// те, которых в коде ещё нет, — безопасна по умолчанию: набор уедет заново.
/// Лишняя выгрузка дешевле молчаливой работы по пустой папке (INV-50).
struct InputsMemory {
    label: String,
    settled: bool,
}

impl InputsMemory {
    fn new(label: &str) -> Self {
        Self { label: label.to_string(), settled: false }
    }

    /// Работа удалась и набор в этот раз уехал: помнить его отпечаток.
    fn remember(&mut self, fingerprint: String) {
        sent_inputs()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(self.label.clone(), fingerprint);
        self.settled = true;
    }

    /// Работа удалась, а набор не менялся: помнить прежнее.
    fn keep(&mut self) {
        self.settled = true;
    }
}

impl Drop for InputsMemory {
    fn drop(&mut self) {
        if !self.settled {
            sent_inputs()
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .remove(&self.label);
        }
    }
}

/// Повторить ли вопрос с пересылкой вложений.
///
/// 🔴 Решение отделено от места, где применяется: внутри работы его не показать
/// проверке — там нужны сеть, окно и сервер. Здесь правило видно целиком:
/// пересылаем ровно тогда, когда шли БЕЗ файлов и сервер сказал, что их у него
/// нет. На любой другой отказ пересылка не отвечает — гонять вложения на каждую
/// беду связи значило бы вернуть ту самую расточительность, ради ухода от
/// которой признак и вводился.
fn should_resend_inputs(went_without_files: bool, outcome: &Result<JobState, CloudError>) -> bool {
    went_without_files && matches!(outcome, Err(e) if e.is_resend_inputs())
}

/// Номер работы, снятие которой сервер НЕ подтвердил, — из отказа, который
/// программа исправляет сама.
///
/// 🔴 Без этого автоповтор глотал отказ целиком, а вместе с ним и номер:
/// осиротевшее задание остаётся на узле, занимает место среди одновременных, и
/// следующий вопрос человека упирается в потолок работ без объяснимой причины —
/// хотя не выполняется ничего. Отдельной функцией, чтобы решение проверялось
/// таблицей, а не только глазами в теле цикла.
fn stray_job_of(outcome: &Result<JobState, CloudError>) -> Option<String> {
    outcome.as_ref().err().and_then(|e| e.stray_job()).map(str::to_string)
}

/// Приписка к ответу, когда остановка не доехала до сервера.
///
/// 🔴 Пометка `cancel_unconfirmed` жила в состоянии задания с прошлого блока, а
/// текст к ней (`unconfirmed_cancel_text`) не звал никто: человек нажимал
/// «Остановить», работа могла остаться идти — и об этом ему не говорили вовсе.
fn cancel_notice(state: &JobState) -> Option<String> {
    state
        .cancel_unconfirmed()
        .then(|| unconfirmed_cancel_text(&state.job_id))
}

/// Что сделать с памятью набора после успешной работы.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum InputsVerdict {
    /// Набор не менялся — помнить прежнее.
    Keep,
    /// Набор уехал целиком — помнить его отпечаток.
    Remember,
    /// Помнить нечего: набор не уезжал или уехал не весь.
    Forget,
}

/// Запоминать ли набор этого вопроса как «уже на сервере».
///
/// Решение отделено от действия намеренно: иначе его нельзя показать проверке —
/// оно живёт внутри работы, которой нужны сеть, окно и сервер.
///
/// 🔴 `complete` — набор уехал ЦЕЛИКОМ, без пропущенных файлов. Прежде отпечаток
/// брался со всей папки, включая файл, который не уместился в общий потолок:
/// человек получал сообщение один раз, а работа шла по неполному набору весь
/// диалог — каждый следующий вопрос молча разбирал два файла из трёх. Теперь
/// неполный набор не запоминается: следующий вопрос перечитает папку и скажет о
/// пропуске снова. Экономия выгрузки при этом теряется ровно в том случае, когда
/// вложения и так не помещаются целиком, — то есть в уже аварийном.
fn decide_inputs_memory(unchanged: bool, sent_any: bool, complete: bool) -> InputsVerdict {
    if unchanged {
        return InputsVerdict::Keep;
    }
    if sent_any && complete {
        InputsVerdict::Remember
    } else {
        InputsVerdict::Forget
    }
}

/// Общий потолок вложений исчерпан: сам файл при этом может быть крошечным.
fn total_limit_warning(name: &str) -> SkippedInput {
    SkippedInput {
        name: name.to_string(),
        reason: format!(
            "файл «{name}» не уместился: вложения во «Входящих» в сумме слишком велики"
        ),
        action: "Уберите из «Входящих» лишние файлы – всего за раз уезжает до 48 МБ.".to_string(),
    }
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
    let mut names: Vec<String> = Vec::new();
    for entry in entries.filter_map(|e| e.ok()).filter(|e| e.path().is_file()) {
        match entry.file_name().to_str() {
            Some(name) => names.push(name.to_string()),
            None => {
                // 🔴 Прежде такое имя отсеивалось молча: ни файла, ни слова о нём.
                // Человек считал данные учтёнными, а разбор шёл без них.
                let shown = entry.file_name().to_string_lossy().to_string();
                warn!("Имя файла не читается [{cabinet_id}]: {shown}");
                skipped.push(SkippedInput {
                    name: shown.clone(),
                    reason: format!("имя файла «{shown}» записано в неизвестной кодировке"),
                    action: "Переименуйте файл во «Входящих» и добавьте его заново.".to_string(),
                });
            }
        }
    }
    names.sort();

    for name in names {
        let path = inbox.join(&name);
        // 🔴 Размер сверяется ДО чтения. Прежде файл читался целиком в память, и
        // только потом сравнивался с потолком: выгрузка на несколько гигабайт
        // роняла программу вместо того, чтобы вызвать предупреждение.
        let size = match std::fs::metadata(&path) {
            Ok(meta) => meta.len(),
            Err(e) => {
                warn!("Сведения о файле «{name}» недоступны [{cabinet_id}]: {e}");
                skipped.push(SkippedInput {
                    name: name.clone(),
                    reason: format!("файл «{name}» не удалось прочитать"),
                    action: "Проверьте файл во «Входящих» и добавьте его заново.".to_string(),
                });
                continue;
            }
        };
        // 🔴 Два разных случая — два разных текста. Прежде оба звучали как «файл
        // слишком велик», и при исчерпанном ОБЩЕМ потолке назывался последний по
        // обходу файл, хотя виноваты предыдущие: человек уменьшал стограммовую
        // таблицу, а мешали два двадцатичетырёхмегабайтных соседа.
        if size > INPUT_FILE_LIMIT as u64 {
            warn!("Файл «{name}» не уедет [{cabinet_id}]: {size} байт");
            skipped.push(oversized_warning(&name));
            continue;
        }
        if total as u64 + size > INPUTS_TOTAL_LIMIT as u64 {
            warn!("Файл «{name}» не уедет [{cabinet_id}]: общий потолок вложений исчерпан");
            skipped.push(total_limit_warning(&name));
            continue;
        }
        let bytes = match std::fs::read(&path) {
            Ok(bytes) => bytes,
            Err(e) => {
                warn!("Файл «{name}» не прочитан [{cabinet_id}]: {e}");
                skipped.push(SkippedInput {
                    name: name.clone(),
                    reason: format!("файл «{name}» не удалось прочитать"),
                    action: "Проверьте файл во «Входящих» и добавьте его заново.".to_string(),
                });
                continue;
            }
        };
        // Файл мог вырасти между сверкой и чтением: потолок держится по факту.
        if bytes.len() > INPUT_FILE_LIMIT {
            warn!("Файл «{name}» вырос между сверкой и чтением [{cabinet_id}]");
            skipped.push(oversized_warning(&name));
            continue;
        }
        if total + bytes.len() > INPUTS_TOTAL_LIMIT {
            warn!("Файл «{name}» вырос между сверкой и чтением [{cabinet_id}]: общий потолок");
            skipped.push(total_limit_warning(&name));
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
            // 🔴 Новый билет берётся ДО того, как убран старый: сохранение
            // перезаписывает файл, поэтому отдельное удаление ничего не решало,
            // а вредило. Прежде старый стирался первым, и любая неудача
            // пересборки оставляла программу вовсе без доступа — в том числе
            // когда «негоден» решили сбитые вперёд часы, а билет был настоящим.
            refresh_ticket(app_handle, &store).map_err(|e| clock_hint(e, problem))?
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

/// Дополнить отказ подсказкой про часы, если билет забракован по СРОКУ.
///
/// 🔴 Часы, сбитые ВПЕРЁД, делают годный билет «просроченным» для программы, и
/// человек начинает чинить лицензию – то есть не то. Про расхождение часов
/// говорит сервер (`request_time_skew`), но в этой ветке до сервера дело не
/// дошло: билет собрать не удалось, и без подсказки причина осталась бы
/// ненайденной. Обратный знак (часы в прошлом) закрыт отдельно отметкой
/// «время неизвестно».
fn clock_hint(error: anyhow::Error, problem: TicketProblem) -> anyhow::Error {
    if !matches!(problem, TicketProblem::Expired) {
        return error;
    }
    anyhow::anyhow!(
        "{error}\n\nЕсли лицензия действует, проверьте часы компьютера: при сбитой дате \
         программа считает срок вышедшим. Включите синхронизацию времени и повторите."
    )
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

/// Человек остановил работу до того, как задание ушло на сервер.
///
/// Отдельная функция, потому что точек сверки две и обе обязаны отвечать
/// одинаково: погасить признак работы в интерфейсе и вернуться без метки —
/// следующий вопрос начнёт новый диалог, а не продолжит несостоявшийся.
fn stopped_before_start(
    app_handle: &tauri::AppHandle,
    cabinet_id: &str,
    suppress_done: bool,
) -> Result<(Option<String>, String)> {
    info!("Работа остановлена до постановки задания [{cabinet_id}]");
    // Сигнал завершения обязателен и здесь: интерфейс держит признак «остановлено»
    // до него, и без сигнала СЛЕДУЮЩИЙ ответ был бы съеден этим признаком.
    if !suppress_done {
        let _ = app_handle.emit(
            &format!("claude-done-{cabinet_id}"),
            serde_json::json!({ "exit_code": 0, "cancelled": true }),
        );
    }
    Ok((None, String::new()))
}

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

    // Сверка методологии: серверный набор кабинетов обязан совпадать с тем, под
    // который выдана лицензия. Расхождение — видимое предупреждение, а не тихий
    // ответ по старой методологии.
    warn_on_cabinets_mismatch(&client, &app_handle, &cabinet_id).await;

    // 🔴 Первая сверка отмены — ДО чтения вложений. Прежде отмена не сверялась ни
    // разу до постановки задания: между нажатием «Остановить» и первой сверкой
    // внутри прогона успевали пройти запрос сведений о сервере, чтение до 48 МБ и
    // выгрузка их на сервер. Человек уже отказался от работы, а программа ещё
    // минуту гнала его файлы наверх.
    if work.cancelled() {
        return stopped_before_start(&app_handle, &cabinet_id, suppress_done);
    }

    // 🔴 Отпечаток набора считается ДО чтения файлов — в этом вся экономия.
    // Прежде все вложения уезжали на КАЖДЫЙ вопрос диалога: двадцать вопросов
    // при тридцати мегабайтах давали около шестисот мегабайт выгрузки. Теперь
    // папка сверяется по метаданным (имя, размер, время правки), и если она не
    // менялась, файлы не читаются и не отправляются вовсе — серверу уходит
    // признак «вложения этого диалога уже на месте».
    let signature = inbox_signature(work_dir);
    let unchanged = !signature.is_empty()
        && sent_inputs()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(&label)
            .is_some_and(|known| known == &inputs_fingerprint(&signature));

    // 🔴 Память о наборе с этого места под стражем: она переживёт только успешную
    // работу. Всякий иной выход — отказ, отмена, обрыв связи — снимает её, и
    // следующая попытка уедет с файлами.
    let mut inputs_memory = InputsMemory::new(&label);

    let effort = effort_for(&app_handle);

    // 🔴 Один повтор с файлами, и только он. Рабочую папку на узле убирает сборщик
    // простоя — по будничным причинам: диалог долго молчал, узел перезапустили.
    // Сервер тогда честно отвечает «файлы этого диалога не найдены», но человеку
    // от этого текста толку нет: файлы у него на месте, во «Входящих». Программа
    // разбирает причину машинно и отправляет их заново сама.
    let mut keep = unchanged;
    let mut shown = String::new();
    // Номер работы, снятие которой сервер не подтвердил при автоповторе. Живёт
    // ВНЕ цикла: сам повтор отказ выбрасывает, и рассказать о нём человеку можно
    // только в конце, вместе с ответом.
    let mut stray_job: Option<String> = None;
    let (inputs, skipped, outcome) = loop {
        let (inputs, skipped) = if keep {
            info!("Вложения диалога уже на сервере [{cabinet_id}]: файлы не перечитываются");
            (Vec::new(), Vec::new())
        } else {
            collect_inputs(work_dir, &cabinet_id)
        };
        // 🔴 Недоставленное вложение ПРЕКРАЩАЕТ работу — инвариант ADR-048, и он же
        // на сервере. Прежде файл за потолком просто пропускался: разбор шёл без
        // данных, которые человек считает учтёнными, и выдавался за законченный.
        // Тост о причине легко не заметить, а отчёт выглядит полноценным — это и есть
        // молчаливое расхождение, которое дороже честного отказа (INV-50).
        //
        // 🔴 Об одном событии человек узнаёт ОДИН раз. Прежде предупреждения
        // рассылались всплывающими ДО этого решения, и человек получал два сообщения
        // об одном и том же, причём всплывающее говорило «файл не уедет», хотя не
        // уезжала вся работа. Всплывающие остаются для случая, когда работа
        // продолжается, — и рассылаются только после того, как это решено.
        if let Some(text) = refusal_for_skipped(&skipped) {
            anyhow::bail!("[TC-GW-INPUT] {text}");
        }
        for item in &skipped {
            let _ = app_handle.emit(
                &format!("inbox-attachments-skipped-{cabinet_id}"),
                // 🔴 Отдельного поля с именем файла в событии НЕТ намеренно: имя уже
                // стоит внутри причины («файл «бюджет.csv» слишком велик»), а поле,
                // которого интерфейс не читает, — либо потерянные данные, либо
                // мёртвый груз. Паритет с Oracle, где так же убрано поле files.
                serde_json::json!({ "reason": item.reason, "action": item.action }),
            );
        }

        // 🔴 Вторая сверка — перед самой постановкой. Чтение файлов могло занять
        // заметное время, и отмена, пришедшая за это время, не должна порождать
        // задание на сервере: оно займёт место в реестре работ и слот лицензии, а
        // остановить его человеку уже нечем — он остановил всё раньше.
        if work.cancelled() {
            return stopped_before_start(&app_handle, &cabinet_id, suppress_done);
        }

        // 🔴 Запрос живёт ВНУТРИ блока: он держит ссылку на набор файлов, а набор
        // отдаётся наружу из цикла. Пока запрос жив, отдать его нельзя.
        let outcome = {
            let request = JobRequest {
                cabinet: &cabinet_id,
                prompt,
                model: model.as_deref(),
                effort: effort.as_deref(),
                session_key: Some(&label),
                // Ключ отправки уникален на попытку: повтор с ним не рождает второе
                // задание, и обрыв связи после постановки перестаёт быть потерянной
                // работой.
                idempotency_key: format!("{label}-{}", short_stamp()),
                inputs: &inputs,
                keep_inputs: keep,
            };
            let cabinet_for_stream = cabinet_id.clone();
            let handle_for_stream = app_handle.clone();
            let shown = &mut shown;
            client
                // 🔴 Признак отмены уходит В прогон, а не сверяется после него.
                // Прежде «Остановить» гасило индикатор, а рабочий поток висел в
                // ожидании до потолка Core — четверть часа, держа соединение и место
                // в реестре работ. Проверка после возврата отменой не была: возврата
                // всё это время и не происходило.
                .run_job_cancellable(
                    &request,
                    |piece| {
                        shown.push_str(piece);
                        if !suppress_done {
                            let _ = handle_for_stream.emit(
                                &format!("claude-stream-{cabinet_for_stream}"),
                                build_stream_event(shown),
                            );
                        }
                    },
                    |job_id| work.attach(job_id),
                    || work.cancelled(),
                )
                .await
        };

        // Повтор ровно один: второй заход идёт уже с файлами, и та же причина
        // прийти не может. Больше одного значило бы гонять вложения по кругу.
        if should_resend_inputs(keep, &outcome) {
            info!("Сервер не нашёл вложений диалога [{cabinet_id}]: отправляю их заново");
            // 🔴 Отказ программа исправляет сама, но одну его подробность глотать
            // нельзя: задание, снятие которого сервер не подтвердил, осталось на
            // узле и занимает место среди одновременных. Молчание здесь означает,
            // что человек упрётся в потолок работ без объяснимой причины.
            if let Some(id) = stray_job_of(&outcome) {
                warn!("Прежняя работа не снята сервером [{cabinet_id}]: {id}");
                stray_job = Some(id);
            }
            keep = false;
            shown.clear();
            // 🔴 Экран обязан забыть показанное ВМЕСТЕ с накопленным текстом.
            // Событие несёт весь ответ целиком, и интерфейс заменяет показанное,
            // — но только когда событие приходит. Если второй заход не отдаст ни
            // одного куска (человек остановил работу, сервер отказал сразу), на
            // экране остаётся абзац, которого нет ни в возврате, ни в истории:
            // видимое и сохранённое расходятся молча.
            if !suppress_done {
                let _ = app_handle.emit(
                    &format!("claude-stream-{cabinet_id}"),
                    build_stream_event(""),
                );
            }
            continue;
        }
        break (inputs, skipped, outcome);
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
        // 🔴 Остановка, которую сервер не подтвердил, обязана быть названа: работа
        // могла остаться идти и занимать место среди одновременных.
        let mut text = state.text.clone();
        if let Some(notice) = cancel_notice(&state) {
            warn!("Остановка не подтверждена сервером [{cabinet_id}]: {}", state.job_id);
            text.push_str(&notice);
        }
        return Ok((None, text));
    }
    if !state.is_success() {
        let (text, hidden) = state.failure_text();
        if let Some(internal) = hidden {
            warn!("шлюз: внутренняя диагностика узла (пользователю не показана): {internal}");
        }
        anyhow::bail!("[TC-GW-SRV] {text}");
    }

    // 🔴 Отпечаток запоминается ТОЛЬКО после успешной работы и только если файлы
    // в этот раз действительно уехали: запомнить раньше — значит однажды сказать
    // «вложения уже на сервере» про набор, который туда не доехал. И наоборот:
    // работа с ПУСТЫМ набором заставляет сервер очистить «Входящие», поэтому
    // память о прежнем наборе становится ложью — страж снимет её сам, ей просто
    // не подтверждают жизнь.
    // 🔴 Судить надо по ТОМУ заходу, который удался: после повтора с файлами
    // `keep` уже ложно, и память обязана обновиться отпечатком уехавшего набора,
    // а не сохранить прежний.
    match decide_inputs_memory(keep, !inputs.is_empty(), skipped.is_empty()) {
        InputsVerdict::Keep => inputs_memory.keep(),
        InputsVerdict::Remember => inputs_memory.remember(inputs_fingerprint(&signature)),
        InputsVerdict::Forget => {}
    }

    let mut text = state.text.clone();
    if state.status == "timeout" {
        // Неполнота обязана быть видна: молча выдать обрезанный отчёт за законченный
        // хуже, чем не выдать вовсе.
        text.push_str(
            "\n\n---\n**Ответ неполный.** Сервер не успел завершить работу за отведённое \
             время – выше то, что он успел подготовить.",
        );
    }
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
    // 🔴 Недоехавший файл больше не молчит. Прежде о нём знал только журнал:
    // человек видел полный ответ и признак готовности, а в папке отчётов лежала
    // половина выгрузки – и дальше работа шла с неполной как с полной. Текст
    // общий для линейки и живёт в Core.
    if let Some(notice) = missing_exports_text(&failed) {
        text.push_str(&notice);
    }
    // 🔴 Работа, оставшаяся на узле после автоповтора, называется здесь — это
    // единственное место, где о ней вообще можно сказать: сам отказ повтор уже
    // выбросил, а следующий вопрос упрётся в потолок работ без объяснимой
    // причины.
    if let Some(id) = &stray_job {
        text.push_str(&unconfirmed_cancel_text(id));
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
/// Отметка «время неизвестно»: заведомо позже любого срока билета.
///
/// Подставляется, когда часы машины сбиты в прошлое. Против любого `expires_at`
/// такое «сейчас» означает «срок вышел», то есть билет берётся заново — сторона
/// безопасная. Обратная подстановка (ноль, «1970-01-01») делала билет вечным.
const TIME_UNKNOWN: &str = "9999-12-31T23:59:59Z";

fn now_utc() -> String {
    // 🔴 Часы РАНЬШЕ 1970 года — это не «начало времён», а сбитые часы. Прежде
    // такой случай подставлял ноль, то есть «1970-01-01», и любой билет выходил
    // вечно годным: проверка срока молча отключалась ровно там, где она и нужна.
    let secs = match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(d) => d.as_secs(),
        Err(_) => return TIME_UNKNOWN.to_string(),
    };
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

/// Версия методологии, которую ожидает эта машина, — версия местного пака содержимого.
///
/// 🔴 Пока серверный набор кабинетов версионируется своей величиной (`cab-…`,
/// считается по содержимому набора), сверять её с версией пака нечем: это разные
/// пространства значений, и «расхождение» показывалось бы на каждом запросе,
/// ничего не означая. Такие пары считаем несравнимыми и молчим — ложная тревога
/// на каждом запросе хуже её отсутствия, потому что от неё перестают отличать
/// настоящую. Сверка включится сама, когда серверный набор начнёт нести версию
/// пака; и код сверки, и его проверки для этого уже есть в Core.
fn client_cabinets_version(app_handle: &tauri::AppHandle) -> Option<String> {
    app_handle
        .path()
        .app_config_dir()
        .ok()
        .and_then(|dir| crate::commands::content_updater::get_local_version(&dir))
}

/// Предупредить, если методология кабинетов на сервере разошлась с ожидаемой.
async fn warn_on_cabinets_mismatch(
    client: &CloudClient,
    app_handle: &tauri::AppHandle,
    cabinet_id: &str,
) {
    let meta = match client.meta().await {
        Ok(meta) => meta,
        Err(e) => {
            // Сведения не пришли — это не повод прекращать работу: сверка версий
            // полезна, но не является условием исполнения.
            debug!("Сведения о сервере не получены [{cabinet_id}]: {e}");
            return;
        }
    };
    let ours = client_cabinets_version(app_handle).unwrap_or_default();
    if meta.cabinets_version.starts_with("cab-") {
        debug!(
            "Версии набора несравнимы [{cabinet_id}]: сервер {}, программа «{ours}»",
            meta.cabinets_version
        );
        return;
    }
    let check = check_cabinets_version(&ours, &meta.cabinets_version);
    if let CabinetsVersionCheck::Differ { .. } = check {
        if let Some(text) = cabinets_mismatch_text(&check) {
            warn!("Расхождение версий кабинетов [{cabinet_id}]: {}", meta.cabinets_version);
            let _ = app_handle.emit(
                &format!("cabinets-version-mismatch-{cabinet_id}"),
                // 🔴 Версия набора в событие не кладётся: интерфейс её не читает и
                // читать не должен — «cab-1db3fe65d525» человеку ничего не говорит.
                // Для разбора жалоб она уже записана строкой выше в журнал.
                serde_json::json!({ "reason": text }),
            );
        }
    }
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
    // Проверка годности билета нужна только здесь: рабочий код принимает
    // решение через `decide_ticket`, и держать импорт наверху значило бы
    // сеять предупреждение о неиспользуемом в каждой сборке.
    use aurora_gateway::cloud::check_ticket;

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
    fn undelivered_attachment_stops_the_work() {
        // 🔴 Инвариант ADR-048: недоставленное вложение ПРЕКРАЩАЕТ работу.
        // Прежде файл за потолком просто пропускался, и разбор по неполным данным
        // выглядел законченным — это дороже честного отказа (INV-50).
        let refusal = refusal_for_skipped(&[SkippedInput {
            name: "бюджет.csv".to_string(),
            reason: "файл «бюджет.csv» слишком велик".to_string(),
            action: "Уберите его из «Входящих» или замените файлом поменьше.".to_string(),
        }])
        .expect("недоехавшее вложение обязано прекращать работу");
        assert!(refusal.contains("бюджет.csv"), "человек не узнает файл: {refusal}");
        assert!(refusal.contains("Что делать"), "отказ не говорит, что делать: {refusal}");
        assert!(!refusal.contains('—'), "короткое тире в клиентском тексте: {refusal}");
    }

    #[test]
    fn broken_clock_does_not_make_the_ticket_eternal() {
        // 🔴 Сбитые часы (время раньше 1970-го) прежде давали «1970-01-01», и
        // любой билет выходил вечно годным — проверка срока молча отключалась
        // ровно там, где она и нужна. Теперь подставляется отметка «время
        // неизвестно», и она обязана быть позже ЛЮБОГО срока.
        let live = serde_json::json!({
            "fingerprint_hash": "a1b2", "signature": "c2ln",
            "expires_at": "2099-01-01T00:00:00Z"
        });
        use base64::Engine as _;
        let encoded = base64::engine::general_purpose::STANDARD
            .encode(live.to_string().as_bytes());

        assert!(
            check_ticket(&encoded, &now_utc()).is_ok(),
            "при исправных часах годный билет обязан приниматься"
        );
        assert!(
            check_ticket(&encoded, TIME_UNKNOWN).is_err(),
            "при неизвестном времени билет принят — проверка срока отключена"
        );
    }

    #[test]
    fn clock_hint_added_only_for_expired_ticket() {
        // 🔴 Часы, сбитые ВПЕРЁД, делают годный билет «просроченным» для
        // программы, и человек начинает чинить лицензию — то есть не то.
        // Подсказка обязана появляться ТОЛЬКО при отказе по сроку: для прочих
        // причин («не читается», «нет отпечатка») она увела бы человека не туда.
        let hinted = clock_hint(anyhow::anyhow!("билет негоден"), TicketProblem::Expired);
        assert!(hinted.to_string().contains("часы"), "подсказка про часы потеряна: {hinted}");

        let other = clock_hint(anyhow::anyhow!("билет негоден"), TicketProblem::Unreadable);
        assert!(
            !other.to_string().contains("часы"),
            "подсказка про часы там, где срок ни при чём: {other}"
        );
    }

    #[test]
    fn everything_delivered_means_no_refusal() {
        // Обратная сторона: пустой перечень пропущенных не смеет останавливать
        // работу — иначе разбор не запустится вообще никогда.
        assert!(refusal_for_skipped(&[]).is_none());
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
    fn inbox_signature_sees_the_folder_without_reading_it() {
        // 🔴 Подпись набора решает, отправлять ли файлы заново. Пропустит
        // изменение — работа пойдёт по устаревшему набору, а выглядеть будет
        // законченной. Читать содержимое при этом нельзя: ради экономии всё и
        // затевалось.
        let tmp = work_dir_with_inbox();
        let inbox = tmp.path().join("inbox");
        std::fs::write(inbox.join("данные.csv"), b"a,b,c").unwrap();
        let first = inbox_signature(tmp.path());
        assert_eq!(first.len(), 1, "файл не попал в подпись: {first:?}");
        assert_eq!(first[0].1, 5, "размер в подписи не с диска");

        // Тот же состав — тот же отпечаток.
        assert_eq!(
            inputs_fingerprint(&first),
            inputs_fingerprint(&inbox_signature(tmp.path())),
            "подпись неустойчива: файлы уезжали бы на каждый вопрос"
        );

        std::fs::write(inbox.join("ещё.txt"), b"x").unwrap();
        assert_ne!(
            inputs_fingerprint(&first),
            inputs_fingerprint(&inbox_signature(tmp.path())),
            "добавленный файл не изменил подпись — он не уедет на сервер"
        );
    }

    #[test]
    fn missing_or_unreadable_inbox_gives_no_signature() {
        // Пустая подпись означает «идти обычным путём»: признак «вложения уже на
        // сервере» ставить не по чему, и работа не пойдёт по пустой папке.
        let tmp = tempfile::TempDir::new().unwrap();
        assert!(
            inbox_signature(tmp.path()).is_empty(),
            "папки «Входящих» нет, а подпись выдана"
        );
        let with_inbox = work_dir_with_inbox();
        assert!(
            inbox_signature(with_inbox.path()).is_empty(),
            "пустая папка обязана давать пустую подпись"
        );
    }

    #[test]
    fn the_pile_is_blamed_for_the_pile_not_the_last_file() {
        // 🔴 Прежде обе беды звучали одинаково: «файл «в.csv» слишком велик»
        // выдавалось и стобайтному файлу, не влезшему в остаток общего потолка.
        // Человек уменьшал его, а мешали два двадцатичетырёхмегабайтных соседа.
        let tmp = work_dir_with_inbox();
        let inbox = tmp.path().join("inbox");
        std::fs::write(inbox.join("а.bin"), vec![1u8; INPUT_FILE_LIMIT]).unwrap();
        std::fs::write(inbox.join("б.bin"), vec![1u8; INPUT_FILE_LIMIT]).unwrap();
        std::fs::write(inbox.join("в.csv"), vec![1u8; 100]).unwrap();

        let (_files, skipped) = collect_inputs(tmp.path(), "econometrist");
        let about_small = skipped
            .iter()
            .find(|w| w.reason.contains("в.csv"))
            .expect("о неуехавшем маленьком файле обязано быть сказано");
        assert!(
            !about_small.reason.contains("«в.csv» слишком велик"),
            "стобайтный файл назван слишком большим: {}",
            about_small.reason
        );
        assert!(
            about_small.reason.contains("в сумме"),
            "причина не названа: дело в общем объёме вложений: {}",
            about_small.reason
        );
        assert!(
            about_small.action.contains("лишние файлы"),
            "действие ведёт не туда – уменьшать надо не этот файл: {}",
            about_small.action
        );
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

    /// Что помнит процесс о наборе этой метки прямо сейчас.
    fn remembered(label: &str) -> Option<String> {
        sent_inputs()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(label)
            .cloned()
    }

    #[test]
    fn success_remembers_the_set_that_went_up() {
        let label = "тест-успех-помнит-набор";
        {
            let mut memory = InputsMemory::new(label);
            memory.remember("отпечаток-1".to_string());
        }
        assert_eq!(
            remembered(label).as_deref(),
            Some("отпечаток-1"),
            "успешная работа обязана запомнить уехавший набор — ради этого всё и делается",
        );
        sent_inputs().lock().unwrap_or_else(|e| e.into_inner()).remove(label);
    }

    #[test]
    fn any_failure_forgets_that_inputs_are_on_the_server() {
        let label = "тест-отказ-снимает-память";
        {
            let mut memory = InputsMemory::new(label);
            memory.remember("отпечаток-2".to_string());
        }
        assert!(remembered(label).is_some(), "предпосылка: набор уже уехал");

        // Следующий вопрос кончился неуспехом — любым: отказ сервера «файлы этого
        // диалога не найдены», обрыв связи, отмена. Страж разрушается без
        // подтверждения жизни.
        {
            let _memory = InputsMemory::new(label);
        }
        assert!(
            remembered(label).is_none(),
            "после неуспеха память обязана сняться: иначе следующий вопрос уйдёт с тем же \
             признаком, получит тот же отказ, и человек попадёт в круг, из которого сам не выйдет",
        );
    }

    #[test]
    fn resend_does_not_swallow_the_number_of_the_stray_job() {
        // 🔴 Автоповтор выбрасывает отказ целиком — и вместе с ним номер работы,
        // снятие которой сервер не подтвердил. Она осталась на узле и занимает
        // место среди одновременных: следующий вопрос человека упрётся в потолок
        // работ без объяснимой причины, хотя не выполняется ничего.
        let stray: Result<JobState, CloudError> =
            Err(CloudError::ResendInputs { stray_job: Some("job-77".to_string()) });
        assert_eq!(
            stray_job_of(&stray).as_deref(),
            Some("job-77"),
            "номер осиротевшей работы потерян — человеку сказать будет нечего",
        );

        // Работа успела закончиться сама: снимать было нечего, и говорить не о чем.
        let clean: Result<JobState, CloudError> =
            Err(CloudError::ResendInputs { stray_job: None });
        assert_eq!(stray_job_of(&clean), None);

        // Чужие исходы номера не выдумывают.
        let broken: Result<JobState, CloudError> = Err(CloudError::Connection("обрыв".into()));
        assert_eq!(stray_job_of(&broken), None);
        let done: Result<JobState, CloudError> = Ok(JobState::default());
        assert_eq!(stray_job_of(&done), None);
    }

    #[test]
    fn unconfirmed_stop_is_named_to_the_person() {
        // 🔴 Пометка о неподтверждённой остановке жила в состоянии задания, а
        // текст к ней не звал никто: человек нажимал «Остановить», работа могла
        // остаться идти — и об этом ему не говорили вовсе.
        let unconfirmed = JobState {
            job_id: "job-9".to_string(),
            status: "cancelled".to_string(),
            error_code: Some("cancel_unconfirmed".to_string()),
            ..JobState::default()
        };
        let notice = cancel_notice(&unconfirmed).expect("остановка не подтверждена, а человек не извещён");
        assert!(notice.contains("job-9"), "номер работы не назван: {notice}");

        // Обычная отмена подтверждена сервером — тревожить человека нечем.
        let plain = JobState {
            job_id: "job-9".to_string(),
            status: "cancelled".to_string(),
            ..JobState::default()
        };
        assert_eq!(cancel_notice(&plain), None);
    }

    #[test]
    fn resend_answers_only_the_missing_inputs_refusal() {
        let missing: Result<JobState, CloudError> = Err(CloudError::ResendInputs { stray_job: None });
        assert!(
            should_resend_inputs(true, &missing),
            "шли без файлов, сервер их не нашёл — единственный отказ, который программа \
             исправляет сама",
        );
        assert!(
            !should_resend_inputs(false, &missing),
            "файлы в этот раз уезжали: пересылать нечего, и повтор был бы вечным кругом",
        );

        let broken: Result<JobState, CloudError> = Err(CloudError::Connection("обрыв".into()));
        assert!(
            !should_resend_inputs(true, &broken),
            "обрыв связи пересылкой не лечится — вложения полетели бы наверх на каждую беду сети",
        );

        let done: Result<JobState, CloudError> = Ok(JobState::default());
        assert!(!should_resend_inputs(true, &done), "работа удалась — повторять нечего");
    }

    #[test]
    fn incomplete_set_is_never_remembered() {
        // Три файла, третий не уместился: работа продолжается, человеку сказано.
        assert_eq!(
            decide_inputs_memory(false, true, false),
            InputsVerdict::Forget,
            "неполный набор запоминать нельзя: иначе каждый следующий вопрос диалога молча \
             пойдёт по двум файлам из трёх, а сказано об этом было один раз",
        );
        assert_eq!(
            decide_inputs_memory(false, true, true),
            InputsVerdict::Remember,
            "полный набор уехал — ради этого экономия и заводилась",
        );
        assert_eq!(
            decide_inputs_memory(false, false, true),
            InputsVerdict::Forget,
            "ничего не уезжало — помнить нечего, и сервер очистил «Входящие»",
        );
        assert_eq!(
            decide_inputs_memory(true, false, true),
            InputsVerdict::Keep,
            "набор не менялся — прежний отпечаток остаётся в силе",
        );
    }

    #[test]
    fn unchanged_success_keeps_the_previous_memory() {
        let label = "тест-набор-не-менялся";
        {
            let mut memory = InputsMemory::new(label);
            memory.remember("отпечаток-3".to_string());
        }
        // Вопрос без правки вложений: файлы не читались и не уезжали, помнить
        // нужно прежнее — иначе следующий вопрос выгрузит всё заново.
        {
            let mut memory = InputsMemory::new(label);
            memory.keep();
        }
        assert_eq!(
            remembered(label).as_deref(),
            Some("отпечаток-3"),
            "работа по неизменившемуся набору обязана сохранить прежний отпечаток",
        );
        sent_inputs().lock().unwrap_or_else(|e| e.into_inner()).remove(label);
    }
}
