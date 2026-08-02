use anyhow::{Context, Result};
use log::{debug, warn};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

/// 🔴 Внешний аудит 2026-07-30 (High): сериализует конкурентные `rate_response` ВНУТРИ процесса —
/// без этого две оценки подряд (клиент быстро жмёт «палец» на двух ответах) читают один и тот же
/// список из N штук и обе пишут N+1: одна оценка молча теряется. Тот же корень и тот же приём, что
/// у истории переписки (`session/history.rs::WRITE_LOCK`) — цикл чтения-изменения-записи обязан
/// быть неделимым.
static WRITE_LOCK: std::sync::LazyLock<std::sync::Mutex<()>> =
    std::sync::LazyLock::new(|| std::sync::Mutex::new(()));

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResponseRating {
    pub cabinet_id: String,
    pub command_slug: Option<String>,
    pub timestamp: String,
    pub rating: i8, // -1 (thumbs down) or 1 (thumbs up)
    pub response_time_secs: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CabinetRatingSummary {
    pub total_ratings: u64,
    pub positive: u64,
    pub negative: u64,
    pub satisfaction_pct: f64,
}

fn ratings_path() -> Result<PathBuf> {
    // CPD-30: per-app каталог с одноразовым переносом legacy AIAgency\metrics — тот же подкаталог,
    // что и usage.json (collector.rs), см. durable_store (повторный вызов app_state_dir("metrics")
    // дёшев — маркер уже стоит).
    Ok(crate::durable_store::app_state_dir("metrics")?.join("ratings.json"))
}

/// Чтение оценок ПЕРЕД ЗАПИСЬЮ: отказ прерывает `rate_response`, с повторами.
///
/// 🔴 Внешний аудит 2026-07-29 (High): битый JSON уходит в карантин, а не молча в `vec![]`.
/// 🔴 Батч C (C1): отказ ЧТЕНИЯ больше не равен пустоте — за этим чтением немедленно следует
/// запись того же файла, и пустой список поверх нечитаемого стёр бы все оценки клиента.
fn load_ratings_for_update(path: &std::path::Path) -> Result<Vec<ResponseRating>> {
    Ok(crate::durable_store::load_json_for_update(path)?.into_value().unwrap_or_default())
}

/// Чтение оценок ДЛЯ ПОКАЗА: без повторов, отказ гасит вызывающий (`get_cabinet_ratings`).
fn load_ratings_at(path: &std::path::Path) -> Result<Vec<ResponseRating>> {
    Ok(crate::durable_store::load_json(path)?.into_value().unwrap_or_default())
}

fn save_ratings_at(path: &std::path::Path, ratings: &[ResponseRating]) -> Result<()> {
    let json = serde_json::to_string_pretty(ratings)?;
    // 🔴 Внешний аудит 2026-07-29 (High): атомарная запись (tmp + rename) вместо прямой —
    // см. durable_store::write_atomic (донор).
    crate::durable_store::write_atomic(path, json.as_bytes()).context("Failed to write ratings")?;
    Ok(())
}

pub fn rate_response(rating: ResponseRating) -> Result<()> {
    let path = ratings_path()?;
    rate_response_at(&path, rating)
}

/// Цикл «прочитал → добавил → записал» под ЯВНЫМ путём — по той же причине, что и у счётчиков
/// (поправка M04): отказ чтения обязан прервать запись, иначе поверх нечитаемого файла лягут
/// ОДНА новая оценка и пустота вместо всех прежних.
///
/// 🔴 Внешний аудит 2026-07-30 (High), находка 1: этот цикл был вообще НЕ сериализован — ни
/// мьютексом внутри процесса, ни замком между процессами, — хотя это ровно тот же
/// read-modify-write, из-за которого правили историю переписки. Оценка клиента терялась без следа
/// и без сообщения. Теперь тот же контракт C4, что у истории: файловый замок + мьютекс на цикл.
fn rate_response_at(path: &std::path::Path, rating: ResponseRating) -> Result<()> {
    // 🔴 Порядок захвата ЕДИНЫЙ во всём продукте (замок → мьютекс, поправка F-16): файловый замок
    // ждём СНАРУЖИ мьютекса, иначе ожидание чужого процесса заморозило бы все оценки этого. При
    // едином порядке взаимной блокировки быть не может.
    let file_lock = crate::metrics::acquire_state_lock(path)?;
    let _guard = WRITE_LOCK.lock().unwrap_or_else(|e| e.into_inner());

    let mut ratings = load_ratings_for_update(path)?;
    debug!("Rating saved: cabinet={}, rating={}", rating.cabinet_id, rating.rating);
    ratings.push(rating);
    // Cap at 2000 ratings
    if ratings.len() > 2000 {
        ratings = ratings.split_off(ratings.len() - 2000);
    }
    save_ratings_at(path, &ratings)?;
    drop(file_lock);
    Ok(())
}

/// 🔴 C1, вторая сторона того же чтения: здесь оценки нужны ТОЛЬКО для показа, записи за этим не
/// следует. Отказ чтения не роняет экран — warn и нули. Молчаливой потери не возникает: запись
/// идёт исключительно через `rate_response`, а он на отказе прерывается.
pub fn get_cabinet_ratings(cabinet_id: &str) -> Result<CabinetRatingSummary> {
    let path = ratings_path()?;
    let ratings = load_ratings_at(&path).unwrap_or_else(|e| {
        warn!("Оценки не прочитаны, показываю нули (файл НЕ тронут): {e:#}");
        Vec::new()
    });
    let cabinet_ratings: Vec<_> = ratings.iter()
        .filter(|r| r.cabinet_id == cabinet_id)
        .collect();

    let total = cabinet_ratings.len() as u64;
    let positive = cabinet_ratings.iter().filter(|r| r.rating > 0).count() as u64;
    let negative = cabinet_ratings.iter().filter(|r| r.rating < 0).count() as u64;
    let satisfaction_pct = if total > 0 {
        (positive as f64 / total as f64) * 100.0
    } else {
        0.0
    };

    Ok(CabinetRatingSummary {
        total_ratings: total,
        positive,
        negative,
        satisfaction_pct,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn thumbs(rating: i8, at: &str) -> ResponseRating {
        ResponseRating {
            cabinet_id: "econometrist".to_string(),
            command_slug: None,
            timestamp: at.to_string(),
            rating,
            response_time_secs: None,
        }
    }

    /// 🔴 C1 на стороне оценок: на нечитаемом файле цикл «прочитал → добавил → записал» обязан
    /// вернуть ошибку и НЕ тронуть файл. Иначе поверх нечитаемых данных легли бы одна новая
    /// оценка и пустота вместо всех прежних.
    ///
    /// 🔴 Проверяется ПРИЧИНА отказа, а не сам факт. Ограничься сторож `is_err()` — он был бы
    /// ложно-зелёным: монопольно занятый файл валит и запись тоже, поэтому ошибка приходила бы
    /// даже со снятой защитой чтения, и мутация «read → unwrap_or_default» его не роняла бы.
    #[cfg(windows)]
    #[test]
    fn rating_read_before_write_refuses_when_file_cannot_be_read() {
        use std::os::windows::fs::OpenOptionsExt;

        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("ratings.json");
        let original = r#"[{"cabinet_id":"econometrist","command_slug":null,"timestamp":"2026-07-30T10:00:00Z","rating":1,"response_time_secs":null}]"#;
        std::fs::write(&path, original).unwrap();

        let held = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .share_mode(0)
            .open(&path)
            .unwrap();

        let err = rate_response_at(&path, thumbs(-1, "2026-07-30T11:00:00Z")).expect_err(
            "нечитаемый файл оценок обязан дать ошибку: запись поверх него уничтожила бы все \
             прежние оценки клиента, оставив одну новую",
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
            "файл оценок обязан остаться нетронутым"
        );
    }

    /// Негативный контроль: на читаемом файле оценка добавляется к прежним, а не заменяет их.
    #[test]
    fn rating_is_appended_to_existing_ones_when_file_is_readable() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("ratings.json");

        rate_response_at(&path, thumbs(1, "2026-07-30T10:00:00Z")).unwrap();
        rate_response_at(&path, thumbs(-1, "2026-07-30T11:00:00Z")).unwrap();

        let saved = load_ratings_at(&path).unwrap();
        assert_eq!(saved.len(), 2, "вторая оценка обязана ДОБАВИТЬСЯ, а не затереть первую");
        assert_eq!(saved[0].rating, 1);
        assert_eq!(saved[1].rating, -1);
    }

    /// 🔴 Сторож находки 1 (High, 2026-07-30): цикл «прочитал → добавил → записал» обязан быть
    /// НЕДЕЛИМЫМ. Без сериализации потоки читают один и тот же список из N оценок и все пишут N+1 —
    /// в файле остаётся горстка вместо всех, и клиент об этом не узнаёт.
    ///
    /// Инвариант сформулирован как у истории переписки: НИ ОДНА принятая оценка не теряется, а
    /// отказ по занятому замку виден и повторяем — поток ведёт себя как интерфейс, повторяя
    /// отправку. Залпа из десятка оценок в продукте не бывает (клиент жмёт «палец» руками), залп
    /// здесь — только чтобы гонка проявилась гарантированно, а не по удаче.
    #[test]
    fn concurrent_ratings_do_not_lose_any_of_them() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("ratings.json");

        const THREADS: usize = 12;
        /// Сколько раз поток повторяет отправку, получив отказ по занятому замку.
        const RETRIES: usize = 40;

        let barrier = std::sync::Arc::new(std::sync::Barrier::new(THREADS));
        let handles: Vec<_> = (0..THREADS)
            .map(|i| {
                let barrier = barrier.clone();
                let path = path.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    let mut last: Option<String> = None;
                    for _ in 0..RETRIES {
                        match rate_response_at(
                            &path,
                            thumbs(if i % 2 == 0 { 1 } else { -1 }, &format!("ts-{i}")),
                        ) {
                            Ok(()) => return,
                            Err(e) => last = Some(format!("{e:#}")),
                        }
                    }
                    panic!(
                        "оценка ts-{i} не сохранена за {RETRIES} повторов — замок не освобождается \
                         вовсе, это уже не конкуренция: {}",
                        last.unwrap_or_default()
                    );
                })
            })
            .collect();
        for h in handles {
            h.join().unwrap();
        }

        let saved = load_ratings_at(&path).expect("после конкурентных записей файл читается");
        assert_eq!(
            saved.len(),
            THREADS,
            "конкурентные оценки не имеют права теряться: каждая либо записана, либо отклонена с \
             ошибкой и повторена — молча пропасть не может"
        );
        let mut seen: Vec<&str> = saved.iter().map(|r| r.timestamp.as_str()).collect();
        seen.sort();
        seen.dedup();
        assert_eq!(
            seen.len(),
            THREADS,
            "каждая из {THREADS} оценок обязана попасть в файл РОВНО один раз — повтор после отказа \
             не имеет права породить дубль"
        );
    }

    /// 🔴 Сторож находки 1, вторая сторона: замок оценок занят ДРУГИМ владельцем (второе окно
    /// продукта) — запись возвращает ошибку, а файл остаётся байт в байт прежним. Замок берётся из
    /// того же процесса другим дескриптором: для `share_mode(0)` это неотличимо от чужого процесса.
    ///
    /// 🔴 Сверяется ПРИЧИНА отказа (речь о замке), а не голый `is_err()`: без этого сторож остался
    /// бы зелёным и при полностью снятой защите — тогда отказ приходил бы откуда угодно позже. И
    /// проверяется, что отказ наступает по ИСЧЕРПАНИИ повторов, а не мгновенно: реальный конфликт
    /// длится единицы миллисекунд и обязан разрешаться ожиданием.
    #[cfg(windows)]
    #[test]
    fn rating_refuses_when_lock_is_held_by_another_owner() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("ratings.json");
        rate_response_at(&path, thumbs(1, "2026-07-30T10:00:00Z")).unwrap();
        let before = std::fs::read_to_string(&path).unwrap();

        let held = crate::session::manager::open_session_lock(&crate::metrics::state_lock_path(&path))
            .unwrap();

        let started = std::time::Instant::now();
        let outcome = rate_response_at(&path, thumbs(-1, "2026-07-30T11:00:00Z"));
        let waited = started.elapsed();

        let err = outcome.expect_err(
            "занятый замок обязан дать ОШИБКУ, а не запись мимо блокировки: она уничтожила бы \
             оценки, добавленные другим окном",
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
            "файл оценок обязан остаться байт в байт прежним — вторая запись не состоялась"
        );

        drop(held);
        rate_response_at(&path, thumbs(-1, "2026-07-30T11:00:00Z"))
            .expect("после освобождения замка запись обязана пройти");
        assert_eq!(load_ratings_at(&path).unwrap().len(), 2);
    }

    #[test]
    fn ratings_default_state() {
        let summary = CabinetRatingSummary {
            total_ratings: 0,
            positive: 0,
            negative: 0,
            satisfaction_pct: 0.0,
        };

        assert_eq!(summary.total_ratings, 0);
        assert_eq!(summary.positive, 0);
        assert_eq!(summary.negative, 0);
        assert!((summary.satisfaction_pct - 0.0).abs() < f64::EPSILON);
    }
}
