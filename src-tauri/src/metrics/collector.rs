use anyhow::{Context, Result};
use log::{debug, info, warn};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Mutex;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UsageMetrics {
    pub total_sessions: u64,
    pub total_messages: u64,
    pub total_exports: u64,
    pub command_counts: HashMap<String, u32>,
    pub cabinets_used: Vec<String>,
    pub avg_response_time_secs: f64,
    pub first_use: Option<String>,
    pub last_use: Option<String>,
    /// Internal: accumulated response times for averaging
    #[serde(default)]
    response_time_sum_secs: f64,
    #[serde(default)]
    response_time_count: u64,
}

impl Default for UsageMetrics {
    fn default() -> Self {
        Self {
            total_sessions: 0,
            total_messages: 0,
            total_exports: 0,
            command_counts: HashMap::new(),
            cabinets_used: Vec::new(),
            avg_response_time_secs: 0.0,
            first_use: None,
            last_use: None,
            response_time_sum_secs: 0.0,
            response_time_count: 0,
        }
    }
}

fn metrics_path() -> Result<PathBuf> {
    // CPD-30: per-app каталог с одноразовым переносом legacy AIAgency\metrics — см. durable_store.
    Ok(crate::durable_store::app_state_dir("metrics")?.join("usage.json"))
}

fn now_iso() -> String {
    chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string()
}

/// Внутрипроцессная сериализация цикла изменения счётчиков + СНИМОК последнего известного
/// состояния.
///
/// 🔴 Внешний аудит 2026-07-30 (High), находка 2 — читать внимательно, здесь была потеря данных
/// клиента. Значение в этом кэше НЕ ЯВЛЯЕТСЯ и не имеет права стать источником для ЗАПИСИ.
/// Раньше файл читался ОДИН раз за процесс (`if guard.is_none()`), а дальше на диск летело
/// закэшированное: окно A закэшировало 42, клиент в окне B довёл счётчик до 100, окно A записало
/// любую метрику — и на диске оказывалось 43, вся работа клиента во втором окне откатывалась.
/// Тем же корнем защита C1 (отказ чтения прерывает запись) работала только на ПЕРВОМ вызове.
/// Теперь единственный источник для записи — ДИСК, перечитываемый под замком на каждом цикле
/// (`with_metrics_at`), а здесь остаётся снимок «что мы записали последним»: он годится только
/// для показа и сбрасывается при `reset_metrics`. Сам мьютекс продолжает делать полезное — он
/// сериализует цикл внутри процесса (межпроцессная сторона — файловый замок).
static METRICS: std::sync::LazyLock<Mutex<Option<UsageMetrics>>> =
    std::sync::LazyLock::new(|| Mutex::new(None));

fn with_metrics<F, R>(f: F) -> Result<R>
where
    F: FnOnce(&mut UsageMetrics) -> R,
{
    let path = metrics_path()?;
    with_metrics_at(&path, f)
}

/// Цикл «прочитал → изменил → записал» под ЯВНЫМ путём.
///
/// 🔴 Батч C, поправка 2 внешнего аудита к контракту (M04): у счётчиков СВОЯ регрессия, отдельная
/// от истории. Раньше ошибка чтения уходила наверх и сохранение не выполнялось; после введения
/// обёртки, глотающей отказ, поверх нечитаемого файла писались бы НУЛИ — накопленные счётчики
/// клиента обнулялись бы молча, тем же корнем, что и переписка. Путь вынесен под явный ровно
/// затем, чтобы это можно было доказать сторожем, не трогая профиль пользователя.
/// 🔴 Внешний аудит 2026-07-30 (High), находка 2: тот же контракт C4, что у истории переписки, —
/// цикл сериализован мьютексом внутри процесса и файловым замком между процессами, а ЗНАЧЕНИЕ
/// перечитывается с диска на КАЖДОМ цикле. Прежний `if guard.is_none()` читал файл один раз за
/// процесс: дальше писалось закэшированное (откат чужой работы, см. докстринг `METRICS`), а
/// проверка C1 «отказ чтения прерывает запись» срабатывала только на первом вызове.
fn with_metrics_at<F, R>(path: &std::path::Path, f: F) -> Result<R>
where
    F: FnOnce(&mut UsageMetrics) -> R,
{
    // Порядок захвата ЕДИНЫЙ во всём продукте (замок → мьютекс, поправка F-16): файловый замок
    // ждём СНАРУЖИ мьютекса, чтобы ожидание чужого процесса не морозило этот.
    let file_lock = crate::metrics::acquire_state_lock(path)?;
    let mut guard = METRICS.lock().unwrap_or_else(|e| e.into_inner());

    // 🔴 Источник для записи — ДИСК, а не кэш, и перечитывается он под замком КАЖДЫЙ раз: только
    // так вклад другого окна доживает до записи, а отказ чтения (C1) прерывает КАЖДЫЙ цикл, а не
    // один первый.
    let mut metrics = load_metrics_for_update(path)?;
    let result = f(&mut metrics);
    save_metrics_at(path, &metrics)?;
    // Снимок обновляется ТОЛЬКО после успешной записи — иначе в памяти осело бы то, чего на диске
    // нет.
    *guard = Some(metrics);
    drop(file_lock);
    Ok(result)
}

/// Чтение метрик ПЕРЕД ЗАПИСЬЮ: отказ чтения возвращается ошибкой, с повторами.
///
/// 🔴 Внешний аудит 2026-07-29 (High): битый JSON уходит в карантин, а не молча в `default()`.
/// 🔴 Батч C (C1): отказ ЧТЕНИЯ (файл занят, нет прав) больше не приравнивается к пустоте. Через
/// эту функцию читает `with_metrics_at`, за которым немедленно следует ЗАПИСЬ того же файла, —
/// значит отказ обязан прервать цикл, иначе накопленная статистика клиента затирается нулями.
/// `Absent`/`Quarantined` — законные пустоты.
fn load_metrics_for_update(path: &std::path::Path) -> Result<UsageMetrics> {
    Ok(crate::durable_store::load_json_for_update(path)?.into_value().unwrap_or_default())
}

/// Чтение метрик ДЛЯ ПОКАЗА: тоже строгое (отказ — это `Err`), но без повторов — за ним не
/// следует запись, и лишняя задержка экрана статистики никого не спасает. Отказ гасит вызывающий.
fn load_metrics_at(path: &std::path::Path) -> Result<UsageMetrics> {
    Ok(crate::durable_store::load_json(path)?.into_value().unwrap_or_default())
}

fn save_metrics_at(path: &std::path::Path, metrics: &UsageMetrics) -> Result<()> {
    let json = serde_json::to_string_pretty(metrics)?;
    // 🔴 Внешний аудит 2026-07-29 (High): атомарная запись (tmp + rename) вместо прямой —
    // см. durable_store::write_atomic (донор).
    crate::durable_store::write_atomic(path, json.as_bytes()).context("Failed to write metrics")?;
    Ok(())
}

/// Record a new session open
pub fn record_session(cabinet_id: &str) -> Result<()> {
    with_metrics(|m| {
        m.total_sessions += 1;
        m.last_use = Some(now_iso());
        if m.first_use.is_none() {
            m.first_use = Some(now_iso());
        }
        if !m.cabinets_used.contains(&cabinet_id.to_string()) {
            m.cabinets_used.push(cabinet_id.to_string());
        }
        debug!("Metrics: session recorded for {cabinet_id}, total={}", m.total_sessions);
    })?;
    Ok(())
}

/// Record a message sent
pub fn record_message(command_slug: Option<&str>) -> Result<()> {
    with_metrics(|m| {
        m.total_messages += 1;
        m.last_use = Some(now_iso());
        if let Some(slug) = command_slug {
            *m.command_counts.entry(slug.to_string()).or_insert(0) += 1;
        }
    })?;
    Ok(())
}

/// Record response time
pub fn record_response_time(seconds: f64) -> Result<()> {
    with_metrics(|m| {
        m.response_time_sum_secs += seconds;
        m.response_time_count += 1;
        m.avg_response_time_secs = m.response_time_sum_secs / m.response_time_count as f64;
    })?;
    Ok(())
}

/// Record an export generated
pub fn record_export() -> Result<()> {
    with_metrics(|m| {
        m.total_exports += 1;
    })?;
    Ok(())
}

/// Get current metrics
///
/// 🔴 C1, вторая сторона того же чтения: здесь метрики нужны ТОЛЬКО для показа, записи за этим
/// не следует. Поэтому отказ чтения не роняет экран статистики — warn и нули. Молчаливой потери
/// не возникает: запись идёт исключительно через `with_metrics`, а он на отказе прерывается.
pub fn get_metrics() -> Result<UsageMetrics> {
    let path = metrics_path()?;
    if !path.exists() {
        return Ok(UsageMetrics::default());
    }
    Ok(load_metrics_at(&path).unwrap_or_else(|e| {
        warn!("Метрики не прочитаны, показываю нули (файл НЕ тронут): {e:#}");
        UsageMetrics::default()
    }))
}

/// Reset all metrics
pub fn reset_metrics() -> Result<()> {
    let path = metrics_path()?;
    if path.exists() {
        std::fs::remove_file(&path)?;
    }
    let mut guard = METRICS.lock().unwrap_or_else(|e| e.into_inner());
    *guard = None;
    info!("Metrics reset");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 🔴 C1 на стороне счётчиков: чтение ПЕРЕД ЗАПИСЬЮ обязано вернуть ошибку на нечитаемом
    /// файле, а не нули. `with_metrics_at` применяет к результату `?`, поэтому отказ здесь
    /// останавливает и запись — накопленная статистика клиента не затирается. Тест ведёт ядро под
    /// явным путём: живой профиль разработчика не трогается.
    ///
    /// 🔴 Проверяется ПРИЧИНА отказа, а не сам факт: монопольно занятый файл валит и запись тоже,
    /// поэтому `is_err()` был бы зелёным и со снятой защитой чтения (тот же класс ложно-зелёного
    /// сторожа, что ловим у продуктов). Отказ обязан прийти ИЗ ЧТЕНИЯ.
    #[cfg(windows)]
    #[test]
    fn metrics_read_before_write_refuses_when_file_cannot_be_read() {
        use std::os::windows::fs::OpenOptionsExt;

        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("usage.json");
        let original = r#"{"total_sessions":42,"total_messages":100,"total_exports":5,
            "command_counts":{},"cabinets_used":[],"avg_response_time_secs":1.5,
            "first_use":null,"last_use":null}"#;
        std::fs::write(&path, original).unwrap();

        let held = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .share_mode(0)
            .open(&path)
            .unwrap();

        let err = load_metrics_for_update(&path).expect_err(
            "нечитаемый файл счётчиков обязан дать ошибку: нули поверх него уничтожили бы всю \
             накопленную статистику клиента",
        );
        let text = format!("{err:#}");
        assert!(
            text.contains("не удалось прочитать"),
            "отказ обязан прийти из ЧТЕНИЯ (иначе сторож зелёный по неверной причине): {text}"
        );

        drop(held);
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            original,
            "файл счётчиков обязан остаться нетронутым"
        );
    }

    /// Негативный контроль к сторожу выше: на ЧИТАЕМОМ файле цикл проходит и счётчик растёт.
    /// Без него «отказ прерывает запись» удовлетворялся бы отказом всегда.
    #[test]
    fn metrics_cycle_writes_when_file_is_readable() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("usage.json");

        // Сверяется не абсолютное значение, а ПРИРОСТ — тест не зависит от того, что делали
        // соседние тесты. (До правки 2026-07-30 это было обязательным: цикл писал закэшированное
        // на процесс значение. Теперь значение читается с диска в своей временной папке, но
        // проверка приростом оставлена — она измеряет ровно то, ради чего написана.)
        let before = with_metrics_at(&path, |m| m.total_exports).unwrap();
        with_metrics_at(&path, |m| m.total_exports += 1).unwrap();
        let after = with_metrics_at(&path, |m| m.total_exports).unwrap();

        assert_eq!(after, before + 1, "на читаемом файле цикл обязан записывать изменения");
        assert!(path.exists(), "файл счётчиков обязан появиться на диске");
    }

    /// 🔴 Сторож находки 2 (High, 2026-07-30): кэш НЕ ЯВЛЯЕТСЯ источником для записи. Сценарий
    /// дословно тот, что теряет данные клиента: окно A выполнило цикл (прежний код ровно здесь
    /// читал файл первый и последний раз), окно B довело счётчики на диске до своих значений,
    /// окно A записало ещё одну метрику. Итог обязан содержать ОБА вклада; прежний код записал бы
    /// закэшированное и откатил бы всю работу второго окна.
    #[test]
    fn metrics_cycle_rereads_from_disk_and_does_not_roll_back_another_window() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("usage.json");

        with_metrics_at(&path, |m| m.total_exports += 1).unwrap();

        // Второе окно — другой процесс: оно пишет на ДИСК, мимо кэша первого.
        let mut from_other_window = UsageMetrics::default();
        from_other_window.total_messages = 100;
        from_other_window.total_exports = 7;
        save_metrics_at(&path, &from_other_window).unwrap();

        with_metrics_at(&path, |m| m.total_exports += 1).unwrap();

        let on_disk = load_metrics_at(&path).unwrap();
        assert_eq!(
            on_disk.total_messages, 100,
            "вклад второго окна обязан дожить до записи: запись закэшированного откатывает всю \
             статистику, накопленную клиентом в другом окне"
        );
        assert_eq!(
            on_disk.total_exports, 8,
            "изменение обязано лечь ПОВЕРХ прочитанного с диска (7 + 1), а не поверх кэша"
        );
    }

    /// 🔴 Сторож находки 2, вторая сторона: защита C1 (отказ чтения прерывает запись) обязана
    /// работать на КАЖДОМ цикле, а не только на первом. Прежний код после первого вызова файл не
    /// читал вовсе, поэтому проверять было нечего.
    ///
    /// 🔴 Сверяется ПРИЧИНА отказа, и это здесь принципиально: монопольно занятый файл валит и
    /// запись тоже, поэтому голый `is_err()` был бы зелёным и с прежним кодом — ошибка пришла бы
    /// от замены файла («не заменить …»), а не от чтения. Вопрос-детектор: «покраснел бы сторож,
    /// если бы правки не было?» — только с этой проверкой.
    #[cfg(windows)]
    #[test]
    fn metrics_cycle_refuses_on_unreadable_file_even_after_the_first_cycle() {
        use std::os::windows::fs::OpenOptionsExt;

        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("usage.json");

        // Первый цикл проходит и наполняет кэш — именно после него прежний код переставал читать.
        with_metrics_at(&path, |m| m.total_exports += 1).unwrap();
        let before = std::fs::read_to_string(&path).unwrap();

        let held = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .share_mode(0)
            .open(&path)
            .unwrap();

        let err = with_metrics_at(&path, |m| m.total_exports += 1).expect_err(
            "нечитаемый файл счётчиков обязан прервать ЛЮБОЙ цикл: запись поверх него уничтожила \
             бы накопленную статистику клиента",
        );
        let text = format!("{err:#}");
        assert!(
            text.contains("не удалось прочитать"),
            "отказ обязан прийти из ЧТЕНИЯ этого цикла, а не позже от замены занятого файла: {text}"
        );

        drop(held);
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            before,
            "файл счётчиков обязан остаться нетронутым"
        );
    }

    /// 🔴 Сторож находки 2, межпроцессная сторона: замок счётчиков занят ДРУГИМ владельцем (второе
    /// окно продукта) — цикл возвращает ошибку, а файл остаётся байт в байт прежним. Замок берётся
    /// из того же процесса другим дескриптором: для `share_mode(0)` это неотличимо от чужого
    /// процесса. Сверяется ПРИЧИНА (речь о замке) и то, что отказ наступает по исчерпании
    /// повторов, а не мгновенно.
    #[cfg(windows)]
    #[test]
    fn metrics_cycle_refuses_when_lock_is_held_by_another_owner() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("usage.json");
        with_metrics_at(&path, |m| m.total_exports += 1).unwrap();
        let before = std::fs::read_to_string(&path).unwrap();

        let held = crate::session::manager::open_session_lock(&crate::metrics::state_lock_path(&path))
            .unwrap();

        let started = std::time::Instant::now();
        let outcome = with_metrics_at(&path, |m| m.total_exports += 1);
        let waited = started.elapsed();

        let err = outcome.expect_err(
            "занятый замок обязан дать ОШИБКУ, а не запись мимо блокировки: она откатила бы \
             счётчики, накопленные другим окном",
        );
        let text = format!("{err:#}");
        assert!(
            text.contains("замок") && text.contains("занят"),
            "отказ обязан прийти ИМЕННО от замка (иначе сторож зелёный по неверной причине): {text}"
        );
        assert!(
            waited >= crate::durable_store::STATE_RETRY_PAUSE
                * (crate::durable_store::STATE_RETRY_ATTEMPTS - 1),
            "отказ обязан наступать по исчерпании повторов, а не мгновенно. Ждали {waited:?}"
        );
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            before,
            "файл счётчиков обязан остаться байт в байт прежним — запись не состоялась"
        );

        drop(held);
        with_metrics_at(&path, |m| m.total_exports += 1)
            .expect("после освобождения замка цикл обязан пройти");
    }

    #[test]
    fn metrics_serialize_deserialize() {
        let mut original = UsageMetrics::default();
        original.total_sessions = 42;
        original.total_messages = 100;
        original.total_exports = 5;
        original.command_counts.insert("ask".to_string(), 10);
        original.cabinets_used.push("cabinet-a".to_string());
        original.avg_response_time_secs = 1.5;
        original.first_use = Some("2026-01-01T00:00:00".to_string());
        original.last_use = Some("2026-03-25T12:00:00".to_string());

        let json = serde_json::to_string(&original).expect("serialize failed");
        let restored: UsageMetrics = serde_json::from_str(&json).expect("deserialize failed");

        assert_eq!(restored.total_sessions, original.total_sessions);
        assert_eq!(restored.total_messages, original.total_messages);
        assert_eq!(restored.total_exports, original.total_exports);
        assert_eq!(restored.command_counts, original.command_counts);
        assert_eq!(restored.cabinets_used, original.cabinets_used);
        assert!((restored.avg_response_time_secs - original.avg_response_time_secs).abs() < f64::EPSILON);
        assert_eq!(restored.first_use, original.first_use);
        assert_eq!(restored.last_use, original.last_use);
    }
}
