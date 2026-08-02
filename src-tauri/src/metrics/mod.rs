pub mod audit;
pub mod collector;
pub mod ratings;

use anyhow::Result;
use std::path::{Path, PathBuf};

/// Межпроцессный замок файлов состояния метрик ждёт ТЕМ ЖЕ циклом, что и всё прочее вокруг файлов
/// состояния: 5 попыток по 100 мс, не дольше полусекунды (`durable_store::STATE_RETRY_*`,
/// `session/history.rs::HISTORY_LOCK_*`). Константа общая намеренно: причина ожидания у всех одна —
/// файл ненадолго кем-то занят (второе окно, индексатор, антивирус), и она проходит за миллисекунды.
const STATE_LOCK_ATTEMPTS: u32 = crate::durable_store::STATE_RETRY_ATTEMPTS;
const STATE_LOCK_RETRY: std::time::Duration = crate::durable_store::STATE_RETRY_PAUSE;

/// Путь файла-замка для файла состояния метрик: `.<имя без расширения>.lock` РЯДОМ с данными
/// (`usage.json` → `.usage.lock`, `ratings.json` → `.ratings.lock`).
///
/// 🔴 Замок выводится ИЗ ПУТИ ФАЙЛА ДАННЫХ, а не из имени продукта, и это не косметика. У
/// Econometrica две редакции — облачная (`com.aurora.econometrica`) и локальная
/// (`com.aurora.econometrica.local`), и `durable_store::app_state_dir("metrics")` даёт каждой СВОЙ
/// каталог. Замок, выведенный от пути, автоматически оказывается свой у каждой редакции: общий
/// замок на обе заставлял бы независимые приложения ждать друг друга, а замок «где-то ещё» — не
/// защищал бы вовсе. Точка с ведущей — общая договорённость продукта о служебных файлах
/// (`.session-lock`, `.history-<кабинет>.lock`).
pub(crate) fn state_lock_path(data_path: &Path) -> PathBuf {
    let stem = data_path
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "state".to_string());
    data_path.with_file_name(format!(".{stem}.lock"))
}

/// Взять МЕЖПРОЦЕССНЫЙ замок на цикл «прочитал → изменил → записал» для файла состояния метрик.
///
/// 🔴 Внешний аудит 2026-07-30 (High, две находки — оценки и счётчики): контракт C4 применили
/// только к истории переписки, а два соседних цикла чтения-изменения-записи остались голыми.
/// Внутрипроцессного мьютекса мало: плагина единственного экземпляра у продукта нет, два клика по
/// ярлыку — это два процесса и два независимых мьютекса, оба читают N и оба пишут N+1.
///
/// Приём тот же, что у замка живой сессии и замка истории (`manager::open_session_lock`,
/// `share_mode(0)`, без внешних зависимостей) — одна реализация монопольного открытия на продукт,
/// чтобы вторая не разошлась с первой. Режим открытия задан дословно (`create(true)` +
/// `write(true)`, и НИКОГДА `create_new(true)`): операционная система освобождает при падении
/// процесса ДЕСКРИПТОР, а сам файл замка остаётся на диске, — с `create_new` первое же аварийное
/// завершение продукта заставило бы захват вечно падать с `AlreadyExists`.
///
/// 🔴 Не удалось за полсекунды → ОШИБКА, а не запись без замка: потеря одной новой оценки или
/// одного тика счётчика обратима, затирание накопленного другим окном — нет.
pub(crate) fn acquire_state_lock(data_path: &Path) -> Result<std::fs::File> {
    let lock_path = state_lock_path(data_path);
    let mut last_err: Option<std::io::Error> = None;
    for attempt in 0..STATE_LOCK_ATTEMPTS {
        match crate::session::manager::open_session_lock(&lock_path) {
            Ok(file) => return Ok(file),
            Err(e) => {
                last_err = Some(e);
                if attempt + 1 < STATE_LOCK_ATTEMPTS {
                    std::thread::sleep(STATE_LOCK_RETRY);
                }
            }
        }
    }
    let waited = STATE_LOCK_RETRY * (STATE_LOCK_ATTEMPTS - 1);
    anyhow::bail!(
        "замок {} занят дольше {:.1} с ({})",
        lock_path.display(),
        waited.as_secs_f32(),
        last_err
            .map(|e| e.to_string())
            .unwrap_or_else(|| "причина неизвестна".to_string())
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Замок обязан лежать РЯДОМ с файлом данных и называться по нему. Иначе счётчики и оценки
    /// делили бы один замок (лишняя сериализация), а главное — ДВЕ РЕДАКЦИИ Econometrica,
    /// у которых каталоги состояния разные, получили бы общий замок и ждали друг друга.
    #[test]
    fn state_lock_lives_next_to_data_and_is_separate_per_file_and_per_edition() {
        let cloud = Path::new("X:").join("com.aurora.econometrica").join("metrics");
        let local = Path::new("X:").join("com.aurora.econometrica.local").join("metrics");

        let usage = state_lock_path(&cloud.join("usage.json"));
        let ratings = state_lock_path(&cloud.join("ratings.json"));

        assert_eq!(usage.parent(), Some(cloud.as_path()), "замок обязан лежать рядом с данными");
        assert_eq!(usage.file_name().unwrap().to_string_lossy(), ".usage.lock");
        assert_eq!(ratings.file_name().unwrap().to_string_lossy(), ".ratings.lock");
        assert_ne!(usage, ratings, "у счётчиков и оценок обязаны быть РАЗНЫЕ замки");
        assert_ne!(
            usage,
            state_lock_path(&local.join("usage.json")),
            "облачная и локальная редакции — отдельные приложения со своими файлами состояния: \
             общий замок заставил бы их ждать друг друга без причины"
        );
    }
}
