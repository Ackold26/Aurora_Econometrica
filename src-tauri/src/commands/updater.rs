use anyhow::Result;
use log::info;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use tauri::Emitter;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

use crate::errors::{coded_err, ErrorCode};

/// Метка «эту деталь отказа написали для клиента, показывайте её вместо общего
/// текста по коду».
///
/// 🔴 Зачем метка, а не догадка по языку (внешний аудит s43, находка H-1). Один код
/// покрывает 4–8 разных причин, и общий текст по коду называет человеку ОДНУ из них —
/// не ту. Самый дорогой случай: клиент отказал в правах администратора, а на экране
/// читает про нехватку места на диске и антивирус, и ходит по кругу. Значит деталь
/// иногда обязана побеждать таблицу — но только когда она написана для человека.
///
/// Признак «в детали есть кириллица» для этого не годится, проверено по всем веткам
/// файла: `Загрузка обновления уже идёт`, `Частичный файл не соответствует
/// серверному — начинаем заново`, `Ответ на докачку противоречив — начинаем заново` —
/// русские, но служебные; «Не удалось загрузить обновление за 5 попыток … {last_err}»
/// и текст про несовпавшую сумму — русские, но с английским хвостом и шестнадцатеричным
/// мусором внутри. Догадка провела бы всё это на блокирующий экран. Поэтому признак
/// явный и ставится там же, где пишется текст.
///
/// Формат строки отказа: `[UP-004] [клиенту] текст для человека`. Разбирает метку
/// `describeUpdateError` (`src/lib/updateErrorText.js`), стык держит сторож
/// `src/lib/updateErrorText.guard.test.js` — он читает ЭТОТ файл и требует, чтобы
/// каждая помеченная деталь доезжала до экрана дословно и подчинялась правилам
/// клиентского текста (без длинного тире, без латиницы кроме адреса поддержки).
pub(crate) const USER_TEXT_MARK: &str = "[клиенту]";

/// Деталь отказа, написанная для клиента: она победит общий текст по коду.
/// Для служебных деталей (английских, с путями и кодами состояния) остаётся
/// обычный `coded_err` — их человеку показывать нельзя.
fn user_err(code: ErrorCode, human: &str) -> anyhow::Error {
    coded_err(code, &format!("{USER_TEXT_MARK} {human}"))
}

/// То же, но для отказов, у которых кода нет и не должно быть: человеку текст
/// нужен, а поддержке код ничего не сказал бы (см. «обновление не требуется»
/// в обёртке `download_update`).
pub(crate) fn user_text(human: &str) -> String {
    format!("{USER_TEXT_MARK} {human}")
}

fn update_base_url() -> String {
    "https://ackold26.github.io/rosst-updates".to_string()
}

fn supabase_update_url() -> String {
    "https://quzhkfvglqmppxcrindh.supabase.co/functions/v1/app-update".to_string()
}

/// Публичный anon-ключ проекта: платформа Supabase требует его на каждом вызове
/// Edge Function (гейт `verify_jwt`), иначе шлюз отвечает 401
/// `UNAUTHORIZED_NO_AUTH_HEADER` ДО входа в код функции. Без него канал
/// обновлений через Supabase мёртв при живом сервере (у клиента это выглядело
/// как бесконечный UP005 → запасной GitHub Pages на каждом старте).
/// Ключ публичный по устройству (он и так уезжает в браузерные клиенты),
/// доступ ограничивают RLS и логика функции.
fn supabase_anon_key() -> String {
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InF1emhrZnZnbHFtcHB4Y3JpbmRoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ4OTc4MjMsImV4cCI6MjA5MDQ3MzgyM30.UJ8BfkwJnK6pl5KctO8YRI0PIxdTUN85jw5IvjUpGHI".to_string()
}

/// Хосты, с которых мы публикуем установщики: Supabase Storage (текущий прод),
/// GitHub Releases и GitHub Pages (fallback). Схема обязана быть https.
/// Основную защиту даёт то, что download_url приходит из серверного манифеста
/// (см. tauri-обёртку download_update), а не с фронта; это - defense-in-depth:
/// даже подменённый манифест не отправит загрузку на посторонний хост.
fn is_trusted_update_url(raw: &str) -> bool {
    let parsed = match reqwest::Url::parse(raw) {
        Ok(u) => u,
        Err(_) => return false,
    };
    if parsed.scheme() != "https" {
        return false;
    }
    let host = match parsed.host_str() {
        Some(h) => h.to_ascii_lowercase(),
        None => return false,
    };
    // Суффикс с ведущей точкой = сам домен или любой его поддомен;
    // без точки = только точное совпадение хоста.
    const TRUSTED: [&str; 4] = [".supabase.co", ".github.io", ".githubusercontent.com", "github.com"];
    TRUSTED.iter().any(|t| match t.strip_prefix('.') {
        Some(bare) => host == bare || host.ends_with(t),
        None => host == *t,
    })
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VersionInfo {
    pub version: String,
    pub download_url: String,
    #[serde(default)]
    pub release_notes: String,
    #[serde(default)]
    pub mandatory: bool,
    #[serde(default)]
    pub checksum: String,
    #[serde(default)]
    pub min_version: String,
}

/// Check for updates via Supabase Edge Function.
///
/// 🔴 Все отказы здесь несут код (внешний аудит s43, находка H-2). Прежде сетевые
/// шли голым `?`: строка приезжала на фронт без кода, и человек читал запасной текст
/// «напишите в поддержку» вместо «проверьте подключение к интернету». Отказ этой
/// ветки обычно съедается запасным каналом GitHub Pages, но код нужен и здесь —
/// он уходит в журнал, по которому поддержка разбирает обращение.
async fn check_supabase(product: &str) -> Result<VersionInfo> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| coded_err(ErrorCode::UP001, &format!("Failed to build HTTP client: {e}")))?;

    let anon_key = supabase_anon_key();
    let resp = client
        .post(supabase_update_url())
        .header("Authorization", format!("Bearer {}", anon_key))
        .header("apikey", &anon_key)
        .json(&serde_json::json!({ "product": product }))
        .send()
        .await
        .map_err(|e| coded_err(ErrorCode::UP001, &format!("Supabase update request failed: {e}")))?;

    if !resp.status().is_success() {
        return Err(coded_err(ErrorCode::UP001, &format!("Supabase /app-update returned {}", resp.status())));
    }

    resp.json()
        .await
        .map_err(|e| coded_err(ErrorCode::UP005, &format!("Supabase manifest is not readable: {e}")))
}

/// Check for updates via GitHub Pages manifest (fallback).
///
/// Коды: UP-001 — до сервера не достучались или он ответил не тем (человеку это
/// читается как «проверьте подключение»); UP-005 — достучались, но манифест не
/// разбирается (человеку это читается как «поправим на своей стороне»).
async fn check_github_pages(product: &str) -> Result<VersionInfo> {
    let url = format!("{}/{}/latest.json", update_base_url(), product);

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| coded_err(ErrorCode::UP001, &format!("Failed to build HTTP client: {e}")))?;

    let resp = client
        .get(&url)
        .send()
        .await
        .map_err(|e| coded_err(ErrorCode::UP001, &format!("Update request failed: {e}")))?;

    if !resp.status().is_success() {
        return Err(coded_err(ErrorCode::UP001, &format!("Update server returned {}", resp.status())));
    }

    // Единственное место, где рождается UP-005: манифест пришёл, но разобрать его
    // нельзя (внешний аудит s43, находка L-1 — прежде ветка UP-005 была недостижима,
    // а текст для неё на фронте уже был написан). Разбор номера версии (`is_newer`)
    // отказать не может: он падает на значения по умолчанию.
    resp.json()
        .await
        .map_err(|e| coded_err(ErrorCode::UP005, &format!("Update manifest is not readable: {e}")))
}

/// Product-ключ канала обновлений.
///
/// D2 (2026-07-03, двухредакционная упаковка): локальная редакция
/// (`--no-default-features`, identifier com.aurora.econometrica.local)
/// обязана получать ТОЛЬКО локальные сборки — общий канал затянул бы
/// облачный exe поверх локального (в нём живёт Claude-канал → нарушение
/// «0 egress»). Суффикс «-local» разводит манифесты:
///   облачная:  aurora-econometrica-gui/latest.json
///   локальная: aurora-econometrica-gui-local/latest.json
/// Публикация локального манифеста — регламент aurora-release-update.
///
/// 🔴 Тонкая редакция СВОЕГО канала больше не имеет (ADR-049 §2). Прежде она уезжала
/// в `…-thin`: это было отдельное приложение с отдельным идентификатором, и смешивать
/// манифесты было нельзя. После слияния поставка одна, а режим (свой Claude Code или
/// шлюз Авроры) выбирается во время работы — второй канал разделял бы то, что уже не
/// разделено, и первым же выпуском развёл бы клиентов по двум веткам обновлений.
/// Заводить его допустимо было только до первого выпуска тонкой редакции; она не
/// выпускалась ни разу, поэтому переселять некого.
///
/// 🔴 А вот локальная редакция канал СОХРАНЯЕТ и сливаться не должна (§7): её гарантия
/// держится на том, что кода обращения к модели в бинаре физически нет. Увести её в
/// общий канал значит однажды прислать клиенту, купившему отсутствие обращений к
/// модели, сборку, которая их делает.
pub fn update_product_key() -> String {
    if cfg!(feature = "cloud_advisors") {
        env!("CARGO_PKG_NAME").to_string()
    } else {
        format!("{}-local", env!("CARGO_PKG_NAME"))
    }
}

/// Check if a newer version is available.
/// Tries Supabase first, falls back to GitHub Pages.
/// Returns `Some(VersionInfo)` if update available, `None` if current.
pub async fn check_for_updates(current_version: &str) -> Result<Option<VersionInfo>> {
    let product = &update_product_key();

    let info = match check_supabase(product).await {
        Ok(info) => info,
        Err(e) => {
            info!("UP005: Supabase update check failed ({}), falling back to GitHub Pages", e);
            check_github_pages(product).await?
        }
    };

    if is_newer(&info.version, current_version) {
        Ok(Some(info))
    } else {
        Ok(None)
    }
}

/// Загрузки установщика, идущие прямо сейчас — по пути частичного файла.
/// Две параллельные загрузки в один и тот же файл писали бы друг поверх друга.
fn in_flight_downloads() -> &'static Mutex<std::collections::HashSet<PathBuf>> {
    static SET: OnceLock<Mutex<std::collections::HashSet<PathBuf>>> = OnceLock::new();
    SET.get_or_init(|| Mutex::new(std::collections::HashSet::new()))
}

struct InFlightGuard(PathBuf);

impl Drop for InFlightGuard {
    fn drop(&mut self) {
        let mut set = in_flight_downloads().lock().unwrap_or_else(|e| e.into_inner());
        set.remove(&self.0);
    }
}

/// Скачать установщик во временную папку, сообщая о ходе загрузки.
///
/// С докачкой: байты пишутся в постоянный файл `.part`, привязанный к адресу
/// загрузки, поэтому оборванное соединение продолжается с последнего байта
/// (HTTP Range), а не начинает 245 МБ заново. До 5 попыток с паузой.
///
/// Порт обкатанного загрузчика Oracle (`21487b8`, `891a80f`, M1/M2/M6/M7 аудита
/// пути доставки). Причина порта — разбор отказа у клиента 2026-07-26: общий
/// таймаут в 600 с на 245 МБ требует скорости от 400 КБ/с, а измеренная скорость
/// у клиента была около 10 КБ/с, то есть обновление не могло установиться
/// физически, сколько бы раз он ни пробовал.
pub async fn download_update(url: &str, app_handle: &tauri::AppHandle) -> Result<PathBuf> {
    // SEC-04 defense-in-depth: качаем только с доверенных хостов публикации.
    if !is_trusted_update_url(url) {
        return Err(coded_err(ErrorCode::UP002, "Update URL is not from a trusted host"));
    }

    // Постоянная папка (не случайная временная): повтор и перезапуск приложения
    // должны находить недокачанный файл на месте.
    let temp_dir_path = std::env::temp_dir().join("aurora-update");
    std::fs::create_dir_all(&temp_dir_path)
        .map_err(|e| coded_err(ErrorCode::UP002, &format!("Failed to create temp dir: {e}")))?;

    // Extract filename from URL — sanitize to a bare basename with a strict
    // whitelist: a manifest-controlled download_url must never place the .exe
    // outside temp (Windows `\`, drive letters, `..`), because apply_update
    // runs it elevated and the checksum comes from the same manifest — so it
    // is no barrier. (Backport of Oracle 891a80f.)
    let raw = url.rsplit(['/', '\\']).next().unwrap_or("");
    let filename = if !raw.is_empty()
        && raw.ends_with(".exe")
        && raw.bytes().all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
    {
        raw
    } else {
        "update-setup.exe"
    };
    let dest_path = temp_dir_path.join(filename);

    // Имя частичного файла привязано к хешу адреса: новая версия никогда не
    // допишется поверх байтов предыдущей.
    let url_hash = hex::encode(sha2::Sha256::digest(url.as_bytes()));
    let part_path = temp_dir_path.join(format!("{}.{}.part", filename, &url_hash[..16]));

    {
        let mut set = in_flight_downloads().lock().unwrap_or_else(|e| e.into_inner());
        if !set.insert(part_path.clone()) {
            // Текст для человека: общий по коду сказал бы «связь прервалась», хотя
            // связь цела и файл в этот самый момент качается — человек нажал бы
            // «Повторить» ещё раз и получил бы то же самое.
            return Err(user_err(
                ErrorCode::UP002,
                "Обновление уже скачивается – подождите, пока полоса дойдёт до конца. Нажимать «Повторить» ещё раз не нужно.",
            ));
        }
    }
    let _in_flight_guard = InFlightGuard(part_path.clone());

    // Общего дедлайна нет намеренно: медленная загрузка в сотни мегабайт не
    // должна обрываться на середине. Зависание ловится таймаутом тишины сокета.
    // SEC-04: reqwest по умолчанию следует до 10 редиректов БЕЗ повторной проверки
    // хоста. Валидация исходного url недостаточна: open-redirect на доверенном
    // хосте или подменённый Location увели бы загрузку на посторонний сервер.
    // checksum-gate ниже это отклонил бы, но слой доверенного хоста должен быть
    // полным - re-валидируем КАЖДЫЙ хоп (github.com → githubusercontent.com при
    // релизах остаётся легитимным, оба в allowlist).
    let client = reqwest::Client::builder()
        .connect_timeout(std::time::Duration::from_secs(30))
        .read_timeout(std::time::Duration::from_secs(60))
        .redirect(reqwest::redirect::Policy::custom(|attempt| {
            if is_trusted_update_url(attempt.url().as_str()) {
                attempt.follow()
            } else {
                attempt.error("update redirect to an untrusted host")
            }
        }))
        .build()
        .map_err(|e| coded_err(ErrorCode::UP002, &format!("Failed to build HTTP client: {e}")))?;

    const MAX_ATTEMPTS: u32 = 5;
    let mut last_err = String::new();

    for attempt in 1..=MAX_ATTEMPTS {
        match download_attempt(&client, url, &part_path, app_handle).await {
            Ok(downloaded) => {
                let _ = std::fs::remove_file(&dest_path);
                if let Err(rename_err) = std::fs::rename(&part_path, &dest_path) {
                    // На Windows переименование может не пройти даже после удаления
                    // выше (файл на миг занят проверкой антивируса). Копирование не
                    // требует атомарности и обычно проходит; если и оно упало —
                    // отдаём исходную ошибку.
                    std::fs::copy(&part_path, &dest_path)
                        .and_then(|_| std::fs::remove_file(&part_path))
                        .map_err(|copy_err| coded_err(ErrorCode::UP002, &format!(
                            "Failed to finalize download: {rename_err} (copy fallback also failed: {copy_err})"
                        )))?;
                }
                info!("Update downloaded: {} ({} bytes, attempt {})", dest_path.display(), downloaded, attempt);
                return Ok(dest_path);
            }
            Err(e) => {
                last_err = e.to_string();
                info!("UP002: попытка {attempt}/{MAX_ATTEMPTS} не удалась ({last_err}) — продолжим с недокачанного места");
                if attempt < MAX_ATTEMPTS {
                    tokio::time::sleep(std::time::Duration::from_secs(2 * attempt as u64)).await;
                }
            }
        }
    }

    Err(coded_err(ErrorCode::UP002, &format!(
        "Не удалось загрузить обновление за {MAX_ATTEMPTS} попыток (проверьте подключение к интернету): {last_err}"
    )))
}

/// Продолженной (206) загрузке можно верить, только если сервер сообщил полный
/// размер и он не меньше уже лежащего на диске. Вынесено отдельной функцией,
/// чтобы проверялась сама логика, а не только обвязка вокруг сети.
fn validate_resume_total(content_range_total: Option<u64>, existing: u64) -> Option<u64> {
    content_range_total.filter(|&total| total >= existing)
}

/// Одна попытка: докачивает в `part_path` через HTTP Range, если там уже есть байты.
/// Возвращает итоговый объём на диске, когда файл получен целиком.
async fn download_attempt(
    client: &reqwest::Client,
    url: &str,
    part_path: &std::path::Path,
    app_handle: &tauri::AppHandle,
) -> Result<u64> {
    let existing: u64 = std::fs::metadata(part_path).map(|m| m.len()).unwrap_or(0);

    let mut req = client.get(url);
    if existing > 0 {
        req = req.header(reqwest::header::RANGE, format!("bytes={existing}-"));
    }
    let resp = req.send().await
        .map_err(|e| coded_err(ErrorCode::UP002, &format!("Download failed: {e}")))?;

    let status = resp.status();
    if !status.is_success() {
        // 416 означает «запрошенный диапазон вне файла»: частичный файл уже
        // полон либо больше исходного. Оставить его — значит получать 416 на
        // каждой из пяти попыток и не докачать никогда (находка аудита H-3).
        // Сбрасываем, следующая попытка скачает начисто.
        if status == reqwest::StatusCode::RANGE_NOT_SATISFIABLE {
            let _ = tokio::fs::remove_file(part_path).await;
            return Err(coded_err(ErrorCode::UP002, "Частичный файл не соответствует серверному — начинаем заново"));
        }
        return Err(coded_err(ErrorCode::UP002, &format!("Download returned {status}")));
    }

    // 206 — сервер принял Range, дописываем; 200 — отдаёт файл целиком, начинаем заново.
    let resumed = status == reqwest::StatusCode::PARTIAL_CONTENT && existing > 0;
    let content_range_total = if resumed {
        resp.headers().get(reqwest::header::CONTENT_RANGE)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.rsplit('/').next())
            .and_then(|v| v.parse::<u64>().ok())
    } else {
        None
    };
    // Ответ 206 без внятного полного размера (или с размером меньше уже
    // скачанного) доверия не заслуживает: сломанный посредник дал бы ход
    // загрузки больше 100% и провёл бы усечённый файл мимо проверки ниже.
    // Сбрасываем частичный файл, чтобы следующая попытка скачала начисто.
    if resumed && validate_resume_total(content_range_total, existing).is_none() {
        let _ = tokio::fs::remove_file(part_path).await;
        return Err(coded_err(ErrorCode::UP002, "Ответ на докачку противоречив — начинаем заново"));
    }
    let (mut file, mut downloaded, total_size) = if resumed {
        let total = content_range_total.expect("проверено выше: Some(total) при total >= existing");
        let file = tokio::fs::OpenOptions::new().append(true).open(part_path).await?;
        info!("Докачка обновления с байта {existing} из {total}");
        (file, existing, total)
    } else {
        let file = tokio::fs::File::create(part_path).await?;
        (file, 0u64, resp.content_length().unwrap_or(0))
    };

    use tokio::io::AsyncWriteExt;
    use futures_util::StreamExt;
    let mut stream = resp.bytes_stream();

    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|e| coded_err(ErrorCode::UP002, &format!("Download stream error: {e}")))?;
        file.write_all(&chunk).await?;
        downloaded += chunk.len() as u64;

        // Emit progress
        let progress = if total_size > 0 { (downloaded as f64 / total_size as f64 * 100.0) as u32 } else { 0 };
        let _ = app_handle.emit("update-progress", serde_json::json!({
            "downloaded": downloaded,
            "total": total_size,
            "percent": progress
        }));
    }
    file.flush().await?;

    // Поток может закончиться «чисто», не отдав всех байтов (посредник, сброс
    // соединения): считаем это обрывом, иначе установили бы усечённый файл.
    if total_size == 0 {
        log::warn!("Загрузка завершилась без известного размера — усечение поймает только проверка контрольной суммы");
    } else if downloaded < total_size {
        return Err(coded_err(ErrorCode::UP002, &format!("Download incomplete: {downloaded}/{total_size} bytes")));
    }

    Ok(downloaded)
}

// SEC-03/04: реестр установщиков, прошедших проверку контрольной суммы в этом сеансе.
// apply_update запускает файл с повышением прав, поэтому обязан принимать ТОЛЬКО
// путь, скачанный и верифицированный здесь же, а не любой существующий .exe,
// переданный с фронта. Ключ - канонизированный путь (устраняет .. и симлинки),
// значение - SHA-256 верифицированного содержимого: apply пере-хеширует файл и
// сверяет с этим хешем, закрывая TOCTOU (подмена содержимого между verify и apply).
fn verified_installers() -> &'static Mutex<HashMap<PathBuf, String>> {
    static REG: OnceLock<Mutex<HashMap<PathBuf, String>>> = OnceLock::new();
    REG.get_or_init(|| Mutex::new(HashMap::new()))
}

fn mark_verified(path: &std::path::Path, hash: &str) {
    if let Ok(canon) = path.canonicalize() {
        // LOW: восстановление отравленного mutex (into_inner), иначе одна паника в
        // критической секции навсегда заблокировала бы обновления до рестарта.
        // Секция тривиальна (insert), инвариантов при панике не нарушает.
        let mut reg = verified_installers()
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        reg.insert(canon, hash.to_ascii_lowercase());
    }
}

/// Путь верифицирован в этом сеансе И его ТЕКУЩЕЕ содержимое совпадает с хешем,
/// зафиксированным при verify_checksum. Пере-хеширование здесь (не только сверка
/// пути) закрывает TOCTOU: между verify и apply содержимое по verified-пути могло
/// быть подменено локальным процессом → запуск elevated разрешаем, только если
/// байты те же, что прошли проверку контрольной суммы.
fn is_verified(path: &std::path::Path) -> bool {
    let canon = match path.canonicalize() {
        Ok(c) => c,
        Err(_) => return false, // не можем канонизировать - fail closed
    };
    let expected = {
        let reg = verified_installers()
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        match reg.get(&canon) {
            Some(h) => h.clone(),
            None => return false, // путь не верифицирован в этом сеансе
        }
    };
    // Пере-хешируем СЕЙЧАС, непосредственно перед решением о запуске.
    let data = match std::fs::read(&canon) {
        Ok(d) => d,
        Err(_) => return false, // файл исчез/недоступен - fail closed
    };
    let actual = hex::encode(sha2::Sha256::digest(&data));
    actual == expected
}

/// Verify SHA256 checksum of a downloaded file.
///
/// B2/B3 (2026-07-03): сообщения по-русски — уходят в errorMsg блокирующего оверлея
/// обновления, клиент должен понимать, что делать.
/// 🔴 Уточнение после внешнего аудита s43 (H-1): «по-русски» само по себе на экран
/// больше не проводит — туда доезжает деталь, помеченная `user_err`. Текст про
/// отсутствующую сумму помечен: общий текст по коду UP-003 зовёт нажать «Повторить»,
/// а повторы здесь не помогут никогда — суммы в манифесте от них не прибавится.
/// Текст про несовпавшую сумму намеренно НЕ помечен: он несёт шестнадцатеричные
/// обрывки хешей, человеку на экран им не место — там лучше общий текст по коду.
pub fn verify_checksum(file_path: &std::path::Path, expected: &str) -> Result<()> {
    if expected.is_empty() {
        return Err(user_err(
            ErrorCode::UP003,
            "Обновление опубликовано без контрольной суммы, поэтому проверить его целостность нельзя – непроверенный файл программа не установит. Повторная попытка тут не поможет: напишите нам на support@auroraai.pro, и мы поправим это на своей стороне.",
        ));
    }

    // Strip "sha256:" prefix if present
    let expected_hash = expected.strip_prefix("sha256:").unwrap_or(expected);

    let data = std::fs::read(file_path)?;
    let hash = sha2::Sha256::digest(&data);
    let actual = hex::encode(hash);

    if actual != expected_hash.to_lowercase() {
        return Err(coded_err(ErrorCode::UP003, &format!(
            "Файл обновления повреждён при загрузке (контрольная сумма не совпала: ожидалась {}…, получена {}…). Повторите загрузку.",
            &expected_hash[..12.min(expected_hash.len())],
            &actual[..12]
        )));
    }

    info!("Checksum verified: {}", &actual[..16]);
    // SEC-03/04: фиксируем путь + верифицированный хеш; apply пере-хеширует и сверит.
    mark_verified(file_path, &actual);
    Ok(())
}

/// Проверки формы + gate происхождения БЕЗ побочных эффектов (без запуска/exit).
/// Вынесено из apply_update, чтобы позитивный путь (verified → разрешён) был покрыт
/// юнит-тестом: apply_update завершает процесс (process::exit) и напрямую не тестируем.
fn ensure_launchable(installer_path: &std::path::Path) -> Result<()> {
    if !installer_path.exists() {
        // Текст для человека: общий по коду UP-004 говорит про нехватку места и
        // защитное средство, а файла просто нет — его нужно скачать заново.
        return Err(user_err(ErrorCode::UP004, &format!(
            "Скачанный файл обновления не найден на диске: {}. Возможно, его убрало защитное средство или очистка временных файлов – нажмите «Повторить», файл будет скачан заново.",
            installer_path.display()
        )));
    }

    // SEC-02 defense-in-depth: refuse paths that could break out of the
    // PowerShell single-quoted string in unanticipated ways. The double-up
    // escape below handles regular single quotes, but a non-absolute path,
    // wrong extension, or embedded control character signals an upstream
    // bug we should fail closed on.
    if !installer_path.is_absolute() {
        return Err(coded_err(ErrorCode::UP004, &format!(
            "Installer path must be absolute: {}", installer_path.display()
        )));
    }
    if installer_path.extension().and_then(|s| s.to_str()).map(|s| s.to_ascii_lowercase()) != Some("exe".to_string()) {
        return Err(coded_err(ErrorCode::UP004, &format!(
            "Installer must be .exe: {}", installer_path.display()
        )));
    }
    let path_str_validate = installer_path.to_string_lossy();
    if path_str_validate.chars().any(|c| c.is_control()) {
        return Err(coded_err(ErrorCode::UP004, "Installer path contains control characters"));
    }

    // SEC-03/04 gate: путь обязан быть результатом успешного verify_checksum в этом
    // сеансе И его содержимое не изменилось с момента проверки (is_verified пере-
    // хеширует). Проверки формы выше (absolute/.exe/no-control) не гарантируют
    // происхождение: без gate любой существующий .exe валидной формы можно было бы
    // запустить elevated, вызвав apply_update с фронта минуя download+verify.
    if !is_verified(installer_path) {
        return Err(coded_err(
            ErrorCode::UP004,
            "Installer did not pass checksum verification - refusing to launch",
        ));
    }
    Ok(())
}

/// Доступен ли каталог на запись — проверяется ФАКТИЧЕСКОЙ попыткой создать в нём
/// временный файл (создали → удалили). Разбор строки пути («начинается с Program
/// Files») здесь не годится: это гадание, а у части клиентов права на каталог
/// программы выданы политикой, и повышение им не нужно.
fn dir_is_writable(dir: &std::path::Path) -> bool {
    let probe = dir.join(format!(".aurora-update-probe-{}.tmp", std::process::id()));
    match std::fs::File::create(&probe) {
        Ok(_) => {
            let _ = std::fs::remove_file(&probe);
            true
        }
        Err(_) => false,
    }
}

/// Нужно ли повышение прав, чтобы установщик смог перезаписать нашу копию.
///
/// CPD-116: после перехода на установку в профиль пользователя
/// (`installMode: currentUser` → `%LOCALAPPDATA%\Optimizer MMM`) каталог программы
/// доступен на запись, и обновление проходит без прав администратора. Но у клиента,
/// поставившего программу по-старому, файлы лежат в `Program Files` — там без прав
/// обновление просто не встанет, поэтому прежний путь остаётся запасным.
fn needs_elevation(install_dir: &std::path::Path) -> bool {
    !dir_is_writable(install_dir)
}

/// Команда PowerShell, запускающая установщик.
///
/// Оба пути обязаны сохранять:
/// - CPD-83: флаги `/S` (тихо) и `/R` (перезапуск после установки) — без `/R`
///   программа после тихого обновления сама не стартует;
/// - CPD-51: `-ErrorAction Stop` + `catch { exit 1 }` — блокирующий `.status()`
///   вызывающей стороны читает отказ (в том числе отказ от повышения прав) как
///   ошибку, движок при этом остаётся жив.
///
/// Различие ровно одно: с повышением — `-Verb RunAs` (окно контроля учётных записей
/// на защищённом рабочем столе), без повышения — обычный запуск скрытым окном.
fn installer_launch_command(installer_str: &str, elevate: bool) -> String {
    let launch_mode = if elevate {
        "-Verb RunAs"
    } else {
        "-WindowStyle Hidden"
    };
    format!(
        "try {{ Start-Process -FilePath '{}' -ArgumentList '/S','/R' {} -ErrorAction Stop }} catch {{ exit 1 }}",
        installer_str, launch_mode
    )
}

/// Launch the installer silently and exit the current process.
///
/// Phase 3.1 (2026-05-23): stop sidecar before launching installer.
/// Without this, `econometrica-sidecar.exe` holds `.pyd` file locks → NSIS
/// "Error opening file for writing" → installer skips locked files silently →
/// frontend new + sidecar old → silent functional gaps (memory: install-lock-issue).
/// NSIS PREINSTALL hook (installer_hooks.nsh) is the safety net for cases where
/// this Rust path is bypassed (manual installer run, watchdog respawn race).
///
/// Phase 3.1 audit fix (2026-05-23): launch ordering changed to launch-then-shutdown.
/// Previous order (shutdown-then-launch с .spawn()) had UAC-denial regression — если
/// user clicks UAC «No», PowerShell .spawn() returns Ok (PS process started OK),
/// installer never elevated, но sidecar already killed → app в dead state. Fix:
/// PowerShell .status() blocking с -ErrorAction Stop catches UAC denial → return Err
/// → app stays functional → NSIS PREINSTALL hook fires later для actual sidecar kill
/// когда installer actually extracts.
pub fn apply_update(installer_path: &std::path::Path) -> Result<()> {
    ensure_launchable(installer_path)?;

    info!("Applying update: {}", installer_path.display());

    // CPD-116: повышение прав запрашиваем не всегда, а только если наш каталог
    // недоступен на запись (прежняя машинная установка в Program Files). Решение
    // принимается фактической пробой записи, не разбором строки пути. Если каталог
    // определить не удалось — идём прежним путём с повышением: это безопасный отказ,
    // он совпадает с поведением до правки.
    // CPD-83/CPD-51 (флаги '/S','/R' и обработка отказа блокирующим .status() с
    // -ErrorAction Stop) сохранены в ОБЕИХ ветках — см. installer_launch_command.
    let elevate = match std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.to_path_buf())) {
        Some(install_dir) => {
            let needed = needs_elevation(&install_dir);
            info!(
                "Install dir {} writable: {} → elevation: {}",
                install_dir.display(),
                !needed,
                needed
            );
            needed
        }
        None => {
            info!("Install dir undetectable → falling back to elevated launch");
            true
        }
    };

    // Block until PowerShell confirms the installer process actually spawned (в ветке
    // с повышением — что UAC подтверждён). PS exits 1 если UAC denied OR Start-Process
    // fails for any other reason → we return Err, sidecar stays alive, app functional.
    let installer_str = installer_path.display().to_string().replace('\'', "''");
    let mut ps_cmd = std::process::Command::new("powershell");
    ps_cmd.args([
        "-NoProfile", "-Command",
        &installer_launch_command(&installer_str, elevate),
    ]);
    #[cfg(windows)]
    ps_cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW - hides PS host console, UAC prompt (separate secure desktop) still shows
    let ps_status = ps_cmd
        .status()
        .map_err(|e| coded_err(ErrorCode::UP004, &format!("Failed to launch PowerShell: {e}")))?;

    if !ps_status.success() {
        // Текст зависит от ветки: в прежнем пути отказ почти всегда означает отказ от
        // повышения прав, в новом — прав никто не спрашивал, и подсказка про них сбила
        // бы человека с толку.
        return Err(user_err(
            ErrorCode::UP004,
            if elevate {
                "Установщик не запустился: запрос прав администратора не подтверждён. Программа продолжает работать – нажмите «Повторить» и в системном окне с вопросом о разрешении выберите «Да»."
            } else {
                "Установщик не запустился. Программа продолжает работать – нажмите «Повторить», а если не поможет, закройте лишние программы и попробуйте ещё раз."
            },
        ));
    }

    info!("Installer launched successfully; stopping sidecar to release file locks");

    // PS confirmed: installer process spawned with elevation, actively extracting in background.
    // NSIS PREINSTALL hook will kill sidecar via taskkill when extraction begins — этот
    // Rust call редundant но defense-in-depth: closes race window между installer process
    // creation и NSIS PREINSTALL execution, particularly если watchdog respawn happens.
    // stop_sidecar idempotent — no-op if NSIS already killed it.
    crate::econ_sidecar::stop_sidecar();

    // Brief pause so UI can show "Installing..." state before exit
    std::thread::sleep(std::time::Duration::from_secs(2));

    // Exit current process to allow installer to replace files
    std::process::exit(0);
}

/// Check if an update is required based on server response (v2 online path).
/// Returns VersionInfo built from the online auth data.
///
/// B3-аудит (2026-07-03): фронт эту команду НЕ вызывает — путь обязательного
/// обновления идёт через heartbeat → checkFullUpdate → `check_update` (полный
/// манифест С checksum). Мост оставлен для back-compat; НЕ строить на нём
/// установку: собранный здесь VersionInfo имеет ПУСТОЙ checksum → строгий
/// verify_checksum откажет (защита от непроверенных установок).
pub fn check_server_update(
    current_version: &str,
    app_min_version: &str,
    update_url: Option<&str>,
) -> Option<VersionInfo> {
    if !is_newer(app_min_version, current_version) {
        return None;
    }

    Some(VersionInfo {
        version: app_min_version.to_string(),
        download_url: update_url.unwrap_or("").to_string(),
        release_notes: String::new(),
        mandatory: true,
        checksum: String::new(),
        min_version: String::new(),
    })
}

/// Semver comparison с учётом prerelease: returns true if `remote` > `current`.
///
/// Старая версия делала `split('.').filter_map(parse::<u32>)` и МОЛЧА отбрасывала
/// хвост `0-rc11` → "2.1.0-rc11" и "2.1.0-rc10" оба сводились к `[2,1]` → считались
/// равными → rc→rc авто-апдейт НИКОГДА не срабатывал (баг найден на rc10→rc11,
/// 2026-06-13). Теперь база и prerelease сравниваются раздельно:
///   - stable (без `-`) ранжируется ВЫШЕ любого prerelease той же базы (rank = u32::MAX);
///   - `rc11` > `rc10` (числовой хвост тега, не лексический — иначе "rc2" > "rc10");
///   - база ("2.1.0") доминирует над prerelease-рангом.
pub(crate) fn is_newer(remote: &str, current: &str) -> bool {
    fn parse(v: &str) -> (Vec<u32>, u32) {
        let v = v.trim_start_matches('v');
        let (base, pre_rank) = match v.split_once('-') {
            Some((b, tag)) => {
                // rc11 → 11, beta3 → 3, без цифр → 0. Всегда < u32::MAX (= release).
                let n = tag
                    .chars()
                    .filter(|c| c.is_ascii_digit())
                    .collect::<String>()
                    .parse()
                    .unwrap_or(0);
                (b, n)
            }
            None => (v, u32::MAX), // нет prerelease = stable релиз
        };
        let nums = base.split('.').filter_map(|s| s.parse().ok()).collect();
        (nums, pre_rank)
    }
    parse(remote) > parse(current)
}

use sha2::Digest;

#[cfg(test)]
mod tests {
    use super::*;

    /// Ответ 206 с отсутствующим, неразбираемым или меньшим, чем уже скачано,
    /// полным размером не должен использоваться для докачки.
    #[test]
    fn resume_rejects_inconsistent_content_range() {
        assert_eq!(validate_resume_total(None, 100), None, "полный размер не сообщён — докачке верить нельзя");
        assert_eq!(validate_resume_total(Some(50), 100), None, "полный размер меньше уже скачанного — сломанный посредник");
        assert_eq!(validate_resume_total(Some(100), 100), Some(100), "на грани, но допустимо");
        assert_eq!(validate_resume_total(Some(200), 100), Some(200), "обычная докачка");
    }

    /// Слот параллельной загрузки освобождается при выходе из области видимости —
    /// иначе после одной неудачной попытки все следующие получали бы отказ.
    #[test]
    fn in_flight_slot_is_released() {
        let part = std::path::PathBuf::from("D:/tmp/aurora-test.part");
        {
            let mut set = in_flight_downloads().lock().unwrap_or_else(|e| e.into_inner());
            assert!(set.insert(part.clone()));
        }
        let _guard = InFlightGuard(part.clone());
        drop(_guard);
        let set = in_flight_downloads().lock().unwrap_or_else(|e| e.into_inner());
        assert!(!set.contains(&part), "после освобождения слот должен быть свободен");
    }

    #[test]
    fn version_comparison() {
        assert!(is_newer("0.2.0", "0.1.0"));
        assert!(is_newer("1.0.0", "0.9.9"));
        assert!(is_newer("v0.1.1", "0.1.0"));
        assert!(!is_newer("0.1.0", "0.1.0"));
        assert!(!is_newer("0.0.9", "0.1.0"));
    }

    #[test]
    fn version_not_newer_than_self() {
        // Одинаковая версия НЕ является более новой
        assert!(!is_newer("0.2.0", "0.2.0"));
        assert!(!is_newer("1.0.0", "1.0.0"));
        assert!(!is_newer("v0.0.1", "0.0.1"));
    }

    /// Каналов ДВА, а не три (ADR-049 §2 и §7): обычная и тонкая поставки слились в
    /// одну и уезжают по базовому ключу, локальная (без `cloud_advisors`) сохраняет
    /// свой «-local». Клиенту локальной редакции никогда не должен приехать exe, в
    /// котором обращение к модели возможно, — на этом держится её обещание.
    ///
    /// 🔴 Проверка на «-thin» стоит в ОБЕИХ ветках, а не только там, где признак
    /// сегодня выключен: вернись суффикс под каким-нибудь условием — тест обязан
    /// покраснеть в любой сборке, а не в той единственной, где условие истинно.
    #[test]
    fn update_channel_matches_edition() {
        let key = update_product_key();
        assert!(!key.ends_with("-thin"), "тонкая редакция своего канала больше не имеет: {key}");
        if cfg!(feature = "cloud_advisors") {
            assert_eq!(key, env!("CARGO_PKG_NAME"));
            assert!(!key.ends_with("-local"));
        } else {
            assert_eq!(
                key,
                format!("{}-local", env!("CARGO_PKG_NAME")),
                "локальная редакция не сливается и сохраняет свой канал (ADR-049 §7)",
            );
        }
    }

    // ── B3 (2026-07-03): ворота установки — verify_checksum ──────────────────

    fn tmp_file_with(content: &[u8]) -> std::path::PathBuf {
        let p = std::env::temp_dir().join(format!(
            "aurora-test-upd-{}.bin",
            uuid::Uuid::new_v4().simple()
        ));
        std::fs::write(&p, content).unwrap();
        p
    }

    /// Корректная сумма проходит; форма с префиксом sha256: (как в живом
    /// манифесте GitHub Pages/Supabase) — тоже.
    #[test]
    fn checksum_valid_passes_with_and_without_prefix() {
        let p = tmp_file_with(b"aurora update payload");
        let hash = hex::encode(sha2::Sha256::digest(b"aurora update payload"));
        verify_checksum(&p, &hash).expect("голый hex должен проходить");
        verify_checksum(&p, &format!("sha256:{hash}")).expect("sha256:-префикс должен проходить");
        // Регистр не важен: expected нормализуется to_lowercase (манифест мог отдать верхний).
        verify_checksum(&p, &hash.to_uppercase())
            .expect("верхний регистр ожидаемой суммы должен нормализоваться и проходить");
        let _ = std::fs::remove_file(&p);
    }

    /// Повреждённый файл (сумма не совпала) → отказ UP-003 с русским сообщением.
    #[test]
    fn checksum_mismatch_rejected_up003() {
        let p = tmp_file_with(b"corrupted download");
        let wrong = hex::encode(sha2::Sha256::digest(b"original payload"));
        let err = verify_checksum(&p, &wrong).expect_err("несовпадение суммы обязано отклоняться");
        let msg = err.to_string();
        assert!(msg.contains("UP-003"), "Ожидался код UP-003: {msg}");
        assert!(msg.contains("повреждён"), "Сообщение должно быть понятным по-русски: {msg}");
        let _ = std::fs::remove_file(&p);
    }

    /// Пустая сумма в манифесте → отказ от установки непроверенного файла
    /// (строгие ворота: обязательное обновление без checksum НЕ ставится).
    #[test]
    fn checksum_empty_refused() {
        let p = tmp_file_with(b"whatever");
        let err = verify_checksum(&p, "").expect_err("пустая сумма обязана отклоняться");
        let msg = err.to_string();
        assert!(msg.contains("контрольной суммы"), "Русское сообщение: {msg}");
        // Внешний аудит s43 (H-1): текст обязан доехать до человека ДОСЛОВНО, а не
        // подмениться общим по коду UP-003 («нажмите Повторить» здесь не помогает
        // никогда). Метка — договор с `describeUpdateError` на фронте.
        assert!(msg.contains(USER_TEXT_MARK), "текст написан для клиента и обязан быть помечен: {msg}");
        assert!(msg.contains("support@auroraai.pro"), "человеку нужен адрес, куда писать: {msg}");
        let _ = std::fs::remove_file(&p);
    }

    /// 🔴 Формат строки отказа — договор с фронтом (внешний аудит s43, H-1).
    ///
    /// `describeUpdateError` выбирает между деталью и общим текстом по коду ровно по
    /// этой метке. Смени здесь порядок или пробел — и самый дорогой отказ (отказ в
    /// правах администратора) снова начнёт показываться как «нехватка места на диске»,
    /// причём молча: Rust соберётся, фронт соберётся, сломается только экран клиента.
    #[test]
    fn user_err_marks_client_facing_detail() {
        assert_eq!(
            user_err(ErrorCode::UP004, "Установщик не запустился.").to_string(),
            "[UP-004] [клиенту] Установщик не запустился.",
        );
        assert_eq!(user_text("Обновление не требуется."), "[клиенту] Обновление не требуется.");
        // Служебная деталь метки НЕ несёт — её человеку показывать нельзя.
        assert_eq!(
            coded_err(ErrorCode::UP004, "Installer must be .exe").to_string(),
            "[UP-004] Installer must be .exe",
        );
    }

    /// Манифест без поля контрольной суммы разбирается, а не отваливается.
    ///
    /// Это последнее недоказанное звено сценария «обновление опубликовано без
    /// контрольной суммы»: остальное уже закрыто — текст проверен выше
    /// (`checksum_empty_refused`), а его дословный приезд на экран держит сторож
    /// `src/lib/updateErrorText.guard.test.js`. Недоставало ровно одного: что
    /// манифест БЕЗ поля вообще разбирается. Снимите `#[serde(default)]` с поля —
    /// и разбор упадёт раньше проверки, человек получит UP-005 про «неожиданный вид
    /// сведений» вместо внятного «напишите нам, поправим на своей стороне», причём
    /// починка H-1 в этой ветке умрёт молча.
    ///
    /// Тест написан вместо живой пробы (план проб s44, проба 3): подменять боевой
    /// манифест на сервере обновлений ради одного поля незачем и рискованно.
    #[test]
    fn manifest_without_checksum_parses_to_empty() {
        let info: VersionInfo = serde_json::from_str(
            r#"{"version":"2.5.3","download_url":"https://example.invalid/setup.exe"}"#,
        )
        .expect("манифест без необязательных полей обязан разбираться");
        assert_eq!(info.checksum, "", "отсутствующее поле даёт пустую строку, а не отказ разбора");

        // И пустая сумма ведёт ровно в помеченную ветку, текст которой проверен выше.
        let p = tmp_file_with(b"unverified installer");
        let err = verify_checksum(&p, &info.checksum).expect_err("непроверенный файл ставить нельзя");
        assert!(err.to_string().contains(USER_TEXT_MARK), "{err}");
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn version_comparison_prerelease() {
        // rc → rc одной базы: раньше оба сводились к [2,1] и считались равными (баг rc10→rc11).
        assert!(is_newer("2.1.0-rc11", "2.1.0-rc10"));
        assert!(!is_newer("2.1.0-rc10", "2.1.0-rc11"));
        assert!(!is_newer("2.1.0-rc11", "2.1.0-rc11"));
        // числовой хвост, не лексический: rc2 < rc10
        assert!(!is_newer("2.1.0-rc2", "2.1.0-rc10"));
        assert!(is_newer("2.1.0-rc10", "2.1.0-rc2"));
        // stable > любой prerelease той же базы; prerelease < stable
        assert!(is_newer("2.1.0", "2.1.0-rc11"));
        assert!(!is_newer("2.1.0-rc11", "2.1.0"));
        // числовая база доминирует над prerelease-рангом
        assert!(is_newer("2.2.0-rc1", "2.1.0-rc11"));
        assert!(is_newer("2.1.0-rc1", "2.0.0"));
    }

    // SEC-03: apply_update обязан отклонять .exe, не прошедший verify_checksum,
    // ДО запуска процесса - иначе с фронта можно запустить любой существующий exe.
    #[test]
    fn apply_update_refuses_unverified_installer() {
        let dir = tempfile::tempdir().unwrap();
        let exe = dir.path().join("evil.exe"); // валидная форма, существует, НЕ верифицирован
        std::fs::write(&exe, b"MZfake").unwrap();
        let abs = exe.canonicalize().unwrap();
        let res = apply_update(&abs);
        assert!(res.is_err(), "неверифицированный установщик должен быть отклонён");
        let msg = format!("{:?}", res.unwrap_err());
        assert!(
            msg.contains("verification") || msg.contains("verif"),
            "причина отказа должна упоминать верификацию: {msg}"
        );
    }

    #[test]
    fn verify_checksum_marks_path_verified() {
        use sha2::Digest;
        let dir = tempfile::tempdir().unwrap();
        let f = dir.path().join("inst.exe");
        let data = b"installer-payload";
        std::fs::write(&f, data).unwrap();
        assert!(!is_verified(&f), "до verify путь не должен быть верифицирован");
        let hash = hex::encode(sha2::Sha256::digest(data));
        verify_checksum(&f, &hash).unwrap();
        assert!(is_verified(&f), "после verify_checksum путь должен быть в реестре");
    }

    #[test]
    fn failed_verify_does_not_mark_verified() {
        let dir = tempfile::tempdir().unwrap();
        let f = dir.path().join("inst.exe");
        std::fs::write(&f, b"data").unwrap();
        assert!(verify_checksum(&f, "sha256:deadbeef").is_err());
        assert!(!is_verified(&f), "провал verify не должен помечать путь верифицированным");
    }

    // HIGH TOCTOU (attack-test): файл верифицирован, затем подменён по ТОМУ ЖЕ
    // пути до apply. Реестр path-only пропустил бы подменённый payload (gate
    // проверял лишь наличие пути). После фикса gate пере-хеширует содержимое и
    // отклоняет несоответствие серверному хешу. На старом коде тест ПАДАЕТ.
    #[test]
    fn apply_refuses_file_swapped_after_verify() {
        use sha2::Digest;
        let dir = tempfile::tempdir().unwrap();
        let f = dir.path().join("inst.exe");
        let good = b"legit-installer-payload";
        std::fs::write(&f, good).unwrap();
        let hash = hex::encode(sha2::Sha256::digest(good));
        verify_checksum(&f, &hash).unwrap();
        assert!(is_verified(&f), "честный файл после verify проходит gate");
        // Локальный процесс без админ-прав подменяет содержимое по verified-пути.
        std::fs::write(&f, b"EVIL-payload-that-would-run-elevated").unwrap();
        assert!(
            !is_verified(&f),
            "TOCTOU: подменённый после verify файл обязан быть отклонён"
        );
    }

    // Дыра покрытия закрыта: позитивный путь (verified → разрешён) тестируется через
    // ensure_launchable без запуска процесса (apply_update завершает раннер exit(0)).
    #[test]
    fn ensure_launchable_accepts_verified_installer() {
        use sha2::Digest;
        let dir = tempfile::tempdir().unwrap();
        let f = dir.path().join("inst.exe");
        let data = b"installer-payload";
        std::fs::write(&f, data).unwrap();
        let abs = f.canonicalize().unwrap();
        assert!(ensure_launchable(&abs).is_err(), "до verify запуск запрещён");
        verify_checksum(&abs, &hex::encode(sha2::Sha256::digest(data))).unwrap();
        assert!(
            ensure_launchable(&abs).is_ok(),
            "верифицированный неизменённый .exe допускается к запуску"
        );
    }

    // CPD-116: обновление без прав администратора. Каталог программы доступен на запись
    // (пользовательская установка в %LOCALAPPDATA%) → установщик запускается обычным
    // способом, окна повышения прав нет вовсе.
    #[test]
    fn writable_install_dir_launches_without_elevation() {
        let dir = tempfile::tempdir().unwrap();
        assert!(
            dir_is_writable(dir.path()),
            "свежий временный каталог обязан быть доступен на запись"
        );
        assert!(
            !needs_elevation(dir.path()),
            "каталог доступен на запись — повышение прав не требуется"
        );
    }

    // Вторая половина той же ветки, отдельным тестом: решение «не повышать» обязано
    // доходить до самой команды запуска, иначе окно контроля учётных записей всё равно
    // появится. Тихо, без окна, без повышения.
    #[test]
    fn launch_command_without_elevation_has_no_runas() {
        let cmd = installer_launch_command("C:\\tmp\\setup.exe", false);
        assert!(
            !cmd.contains("RunAs"),
            "в ветке без повышения прав не должно быть -Verb RunAs: {cmd}"
        );
        assert!(
            cmd.contains("-WindowStyle Hidden"),
            "запуск без повышения прав обязан быть без видимого окна: {cmd}"
        );
    }

    // Обратная ветка: прежний клиент в Program Files. Каталог на запись недоступен →
    // сохраняется прежний путь с повышением прав, иначе обновление просто не встанет.
    #[test]
    fn unwritable_install_dir_keeps_elevation() {
        let dir = tempfile::tempdir().unwrap();
        // Несуществующий подкаталог — гарантированно недоступен на запись, и проверка
        // не зависит от прав запускающего (под администратором Program Files писуем).
        let missing = dir.path().join("no-such-dir");
        assert!(
            !dir_is_writable(&missing),
            "несуществующий каталог не может быть доступен на запись"
        );
        assert!(
            needs_elevation(&missing),
            "каталог недоступен на запись — обязано остаться повышение прав"
        );
        let cmd = installer_launch_command("C:\\tmp\\setup.exe", true);
        assert!(
            cmd.contains("-Verb RunAs"),
            "ветка с повышением прав обязана сохранить -Verb RunAs: {cmd}"
        );
    }

    // CPD-83 (флаги тихого запуска) и CPD-51 (отказ ловится блокирующим .status()
    // с -ErrorAction Stop) обязаны пережить разделение на две ветки.
    #[test]
    fn both_launch_paths_keep_silent_flags_and_error_stop() {
        for elevate in [false, true] {
            let cmd = installer_launch_command("C:\\tmp\\setup.exe", elevate);
            assert!(
                cmd.contains("'/S','/R'"),
                "CPD-83: флаги '/S','/R' обязательны (elevate={elevate}): {cmd}"
            );
            assert!(
                cmd.contains("-ErrorAction Stop"),
                "CPD-51: -ErrorAction Stop обязателен (elevate={elevate}): {cmd}"
            );
            assert!(
                cmd.contains("catch") && cmd.contains("exit 1"),
                "провал запуска обязан давать код возврата 1 (elevate={elevate}): {cmd}"
            );
        }
    }

    // SEC-04 defense-in-depth: доменная валидация download_url (к «checksum из манифеста»).
    #[test]
    fn rejects_untrusted_download_url() {
        // Легитимные источники публикации не ломаются:
        assert!(is_trusted_update_url(
            "https://quzhkfvglqmppxcrindh.supabase.co/storage/v1/object/public/updates/aurora-legal/x.exe"
        ));
        assert!(is_trusted_update_url(
            "https://github.com/Ackold26/rosst-updates/releases/download/v0.8.10/x.exe"
        ));
        assert!(is_trusted_update_url(
            "https://ackold26.github.io/rosst-updates/aurora-legal/x.exe"
        ));
        // Векторы атаки отклонены:
        assert!(!is_trusted_update_url("http://attacker.example/evil.exe")); // не https
        assert!(!is_trusted_update_url("https://github.com.attacker.example/evil.exe")); // подставной хост
        assert!(!is_trusted_update_url("https://evilsupabase.co/evil.exe")); // не поддомен supabase.co
        assert!(!is_trusted_update_url("file:///C:/Windows/evil.exe")); // не https
        assert!(!is_trusted_update_url("not even a url"));
    }
}
