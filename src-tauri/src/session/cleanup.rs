use anyhow::Result;
use log::{info, warn};
use std::path::Path;

use super::manager::{open_session_lock, secure_delete_dir, WipeOutcome, SESSION_LOCK_FILE};

/// Clean up any leftover session directories from previous runs (crash recovery).
///
/// CPD-30: per-app каталог (см. durable_store) — тот же вызов, что SessionManager::new()
/// (session/manager.rs), иначе очистка на старте не находила бы то, что создал менеджер.
pub fn cleanup_stale_sessions() -> Result<()> {
    sweep_dir(&crate::durable_store::app_state_dir(crate::durable_store::SESSIONS_SUB)?)?;
    Ok(())
}

/// Итог одного прохода очистки — чтобы вызывающий (и тесты) видел не только «упало/не упало».
#[derive(Debug, Default, PartialEq, Eq)]
pub(crate) struct SweepSummary {
    /// Осиротевшие каталоги, снесённые затирающим удалением.
    pub removed: usize,
    /// Каталоги живых сессий (замок занят) — пропущены нетронутыми.
    pub alive: usize,
    /// Записи, которые не удалось прочитать или снести — обход при этом продолжился.
    pub failed: usize,
    /// 🔴 Поправка M20: каталоги, снесённые БЕЗ полного затирания. Их содержимое (расшифрованные
    /// файлы кабинета) восстановимо с диска, и это обязано быть видно в итоге прохода, а не
    /// пропадать в тишине «удалено успешно».
    pub wiped_incompletely: usize,
}

/// Признак ЖИВОЙ сессии: файл-замок внутри каталога открыт монопольно её владельцем.
///
/// 🔴 Батч C (C2, Critical): раньше очистка сносила ВСЕ поддиректории `sessions/` безусловно
/// (`let _ = std::fs::remove_dir_all(entry.path())`). Плагина единственного экземпляра в продукте
/// нет — второй клик по ярлыку (обычное дело, когда окно свёрнуто) запускает второй процесс, и тот
/// первым же действием сносил каталог ЖИВОЙ сессии первого окна: у пользователя посреди работы
/// исчезали расшифрованные файлы кабинета.
///
/// Владелец держит `.session-lock` открытым с `share_mode(0)` всё время жизни сессии
/// (см. `manager::create_locked_session_dir`). Пробуем открыть так же монопольно:
/// - получилось → владельца нет, сессия осиротела (аварийное завершение) → сносим;
/// - не получилось → файл занят живым владельцем → не трогаем.
///
/// 🔴 Каталог БЕЗ файла-замка — сессия предыдущей версии продукта: считается осиротевшей и
/// сносится, поведение для старых установок не меняется.
fn session_is_live(session_dir: &Path) -> bool {
    let lock_path = session_dir.join(SESSION_LOCK_FILE);
    if !lock_path.exists() {
        return false;
    }
    match open_session_lock(&lock_path) {
        Ok(file) => {
            drop(file); // замок свободен — владельца нет; закрываем сразу, чтобы не мешать удалению
            false
        }
        Err(e) => {
            // Каталог пропускаем в любом случае: снести расшифрованные файлы работающего окна
            // дороже, чем оставить осиротевший до следующего запуска. Но ПРИЧИНУ различаем.
            match classify_lock_refusal(&e) {
                LockRefusal::LiveOwner => info!(
                    "Очистка сессий: {} пропущен как живой (замок держит владелец: {e})",
                    session_dir.display()
                ),
                LockRefusal::Unreadable => warn!(
                    "Очистка сессий: {} пропущен, но замок недоступен НЕ из-за живого владельца \
                     ({e}) — если причина постоянная (сбиты права, файл держит служба), каталог с \
                     расшифрованными файлами клиента пролежит здесь бессрочно",
                    session_dir.display()
                ),
            }
            true
        }
    }
}

/// Код ошибки Windows «отказ разделения доступа» (ERROR_SHARING_VIOLATION): файл открыт кем-то
/// монопольно. Именно так выглядит ЖИВАЯ сессия со стороны очистки.
const ERROR_SHARING_VIOLATION: i32 = 32;

/// Почему живой владелец распознаётся по КОДУ ОС, а не по `ErrorKind`.
///
/// 🔴 Зонд на живой машине (2026-07-30): монопольно занятый файл на Windows отдаёт
/// `kind = Uncategorized`, `raw_os_error = Some(32)` — а вовсе не `PermissionDenied`, как
/// подсказывает интуиция и как было записано в первой редакции контракта. Проверка по
/// `ErrorKind::PermissionDenied` увела бы ЖИВУЮ сессию в ветку «прочие ошибки» и клеила бы `warn`
/// на каждый запуск, ровно наоборот замыслу. Сторож
/// `real_held_lock_is_classified_as_live_owner` берёт настоящий замок и сверяет отнесение с
/// поведением системы, а не с ожиданием разработчика.
#[derive(Debug, PartialEq, Eq)]
pub(crate) enum LockRefusal {
    /// Файл занят монопольно — владелец жив, каталог трогать нельзя (это норма, `info`).
    LiveOwner,
    /// Прочая причина (сбиты права, файл держит служба, сломана ФС). Каталог тоже пропускаем, но
    /// это НЕ признак жизни: при постоянной причине он не будет снесён никогда, и расшифрованные
    /// файлы клиента останутся на диске бессрочно — такое обязано быть видно (`warn`).
    Unreadable,
}

pub(crate) fn classify_lock_refusal(e: &std::io::Error) -> LockRefusal {
    if e.raw_os_error() == Some(ERROR_SHARING_VIOLATION) {
        LockRefusal::LiveOwner
    } else {
        LockRefusal::Unreadable
    }
}

/// Ядро очистки — тестируемое, принимает путь явно (не зависит от глобальных
/// LOCALAPPDATA/BASE_DIR, см. тот же приём в `durable_store::migrate_into`).
fn sweep_dir(sessions_dir: &Path) -> Result<SweepSummary> {
    let mut summary = SweepSummary::default();
    if !sessions_dir.exists() {
        return Ok(summary);
    }

    for entry in std::fs::read_dir(sessions_dir)? {
        // 🔴 Батч C (C2 п.4): ошибка ОДНОЙ записи не прекращает весь обход. Раньше здесь стояли
        // `?`, и первая же нечитаемая запись оставляла остальные осиротевшие сессии с
        // расшифрованными данными лежать на диске — молча, потому что вызов в `lib.rs` обёрнут
        // в `let _ =`.
        let entry = match entry {
            Ok(e) => e,
            Err(e) => {
                warn!("Очистка сессий: не прочитана запись каталога {}: {e}", sessions_dir.display());
                summary.failed += 1;
                continue;
            }
        };
        match entry.file_type() {
            Ok(ft) if ft.is_dir() => {}
            Ok(_) => continue, // файлы верхнего уровня очистку не касаются
            Err(e) => {
                warn!("Очистка сессий: не определён тип {}: {e}", entry.path().display());
                summary.failed += 1;
                continue;
            }
        }

        let path = entry.path();
        if session_is_live(&path) {
            summary.alive += 1;
            continue;
        }

        // 🔴 Батч C (C2 п.3): затирающее удаление вместо `remove_dir_all` — тем же путём, что и
        // штатное закрытие кабинета (`manager::close_session`). Очистке есть что удалять ровно
        // после аварийного завершения, то есть каталог заведомо содержит расшифрованные файлы
        // клиента. Результат больше не глотается `let _ =`: занятый индексатором или антивирусом
        // файл виден в журнале, а не теряется молча.
        match secure_delete_dir(&path) {
            Ok(wipe) => {
                summary.removed += 1;
                if wipe == WipeOutcome::Incomplete {
                    summary.wiped_incompletely += 1;
                }
            }
            Err(e) => {
                warn!("Очистка сессий: не снесён осиротевший каталог {}: {e}", path.display());
                summary.failed += 1;
            }
        }
    }

    info!(
        "Очистка сессий в {}: снесено {}, живых пропущено {}, с ошибкой {}, затёрто неполно {}",
        sessions_dir.display(),
        summary.removed,
        summary.alive,
        summary.failed,
        summary.wiped_incompletely
    );
    Ok(summary)
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::manager::create_locked_session_dir;

    /// Очистка обязана найти и снести оставшийся с прошлого запуска каталог сессии.
    #[test]
    fn sweeps_leftover_session_directories() {
        let tmp = tempfile::tempdir().unwrap();
        let sessions_dir = tmp.path().join("sessions");
        let stale = sessions_dir.join("econometrist_ab12cd34");
        std::fs::create_dir_all(&stale).unwrap();
        std::fs::write(stale.join("workspace_marker.txt"), "leftover").unwrap();

        sweep_dir(&sessions_dir).unwrap();

        assert!(!stale.exists(), "оставшийся с прошлого запуска каталог сессии обязан быть снесён");
        assert!(
            sessions_dir.exists(),
            "сам каталог sessions/ остаётся — сносится только его содержимое-директории"
        );
    }

    /// Файлы верхнего уровня (не директории) очистка не трогает — сессии всегда директории,
    /// случайный файл рядом (если появится) не должен исчезнуть молча.
    #[test]
    fn does_not_touch_top_level_files() {
        let tmp = tempfile::tempdir().unwrap();
        let sessions_dir = tmp.path().join("sessions");
        std::fs::create_dir_all(&sessions_dir).unwrap();
        std::fs::write(sessions_dir.join("stray.txt"), "not a session dir").unwrap();

        sweep_dir(&sessions_dir).unwrap();

        assert!(
            sessions_dir.join("stray.txt").exists(),
            "файлы верхнего уровня очистка трогать не должна"
        );
    }

    /// Несуществующий каталог — не ошибка (первый запуск продукта, sessions/ ещё не создан).
    #[test]
    fn missing_dir_is_noop() {
        let tmp = tempfile::tempdir().unwrap();
        let sessions_dir = tmp.path().join("does-not-exist");
        sweep_dir(&sessions_dir).unwrap();
    }

    /// 🔴 Главный сторож C2 (Critical): очистка обязана РАЗЛИЧАТЬ живую сессию и осиротевшую.
    /// Сценарий из жизни: пользователь работает в открытом кабинете и кликает ярлык второй раз —
    /// второй процесс запускает очистку, и она не имеет права трогать каталог первого окна.
    /// Проверяются все три случая сразу:
    /// - замок ДЕРЖИТСЯ владельцем → каталог переживает очистку вместе с расшифрованными файлами;
    /// - замок был, но отпущен (владелец завершился) → каталог осиротел, сносится;
    /// - замка нет вовсе (сессия предыдущей версии продукта) → сносится, как и раньше.
    ///
    /// Только Windows: монопольное открытие даёт `share_mode(0)`, на других целях (крейт лишь
    /// компилируется под них, поставки нет) признака занятости файла нет — см. `open_session_lock`.
    #[cfg(windows)]
    #[test]
    fn held_lock_marks_session_live_released_and_missing_lock_are_swept() {
        let tmp = tempfile::tempdir().unwrap();
        let sessions_dir = tmp.path().join("sessions");

        let live = sessions_dir.join("econometrist_live0001");
        let released = sessions_dir.join("econometrist_rel00002");
        let legacy = sessions_dir.join("econometrist_old00003");
        for dir in [&live, &released, &legacy] {
            std::fs::create_dir_all(dir).unwrap();
            std::fs::write(dir.join("CLAUDE.md"), "расшифрованный файл кабинета").unwrap();
        }

        // Живая сессия: владелец держит замок открытым всё время очистки.
        let held = open_session_lock(&live.join(SESSION_LOCK_FILE)).unwrap();
        // Осиротевшая: замок был взят и отпущен — файл остался, хендла нет.
        drop(open_session_lock(&released.join(SESSION_LOCK_FILE)).unwrap());
        // `legacy` — вообще без файла-замка.

        let summary = sweep_dir(&sessions_dir).unwrap();

        assert!(
            live.join("CLAUDE.md").exists(),
            "каталог живой сессии (замок занят) обязан пережить очистку вместе с содержимым — \
             иначе у работающего окна исчезают расшифрованные файлы"
        );
        assert!(
            !released.exists(),
            "каталог с ОТПУЩЕННЫМ замком осиротел (владелец завершился) и обязан быть снесён"
        );
        assert!(
            !legacy.exists(),
            "каталог без файла-замка (сессия предыдущей версии продукта) обязан сноситься, как и раньше"
        );
        assert_eq!(
            summary,
            SweepSummary { removed: 2, alive: 1, failed: 0, wiped_incompletely: 0 },
            "итог прохода: два осиротевших снесены, один живой пропущен, ошибок нет"
        );

        drop(held); // отпускаем, чтобы tempdir удалился без остатка
    }

    /// 🔴 Сторож C2 п.4: ошибка на ОДНОЙ записи не имеет права прекращать весь обход — иначе
    /// остальные осиротевшие сессии с расшифрованными данными остаются на диске, причём молча
    /// (вызов в `lib.rs` обёрнут в `let _ =`).
    /// Отказ смоделирован занятым файлом внутри среднего каталога (так ведёт себя файл,
    /// захваченный индексатором или антивирусом), осиротевшие соседи стоят по обе стороны от
    /// него — независимо от порядка обхода один из них идёт ПОСЛЕ отказавшего.
    #[cfg(windows)]
    #[test]
    fn failure_on_one_entry_does_not_abort_the_rest_of_the_sweep() {
        let tmp = tempfile::tempdir().unwrap();
        let sessions_dir = tmp.path().join("sessions");

        let first = sessions_dir.join("a_orphan");
        let stuck = sessions_dir.join("b_stuck");
        let last = sessions_dir.join("c_orphan");
        for dir in [&first, &stuck, &last] {
            std::fs::create_dir_all(dir).unwrap();
            std::fs::write(dir.join("CLAUDE.md"), "расшифрованный файл кабинета").unwrap();
        }
        // Файл в среднем каталоге занят посторонним держателем — затирающее удаление на нём
        // споткнётся. Замка `.session-lock` в каталоге нет, то есть он считается осиротевшим и
        // очистка честно пытается его снести.
        let busy = open_session_lock(&stuck.join("busy.bin")).unwrap();

        let summary = sweep_dir(&sessions_dir).unwrap();

        assert!(!first.exists(), "осиротевший каталог ДО отказавшего обязан быть снесён");
        assert!(
            !last.exists(),
            "осиротевший каталог ПОСЛЕ отказавшего обязан быть снесён — обход не прекращается на \
             первой ошибке"
        );
        assert!(stuck.exists(), "каталог с занятым файлом снести не удалось — он остаётся на месте");
        assert_eq!(
            summary,
            SweepSummary { removed: 2, alive: 0, failed: 1, wiped_incompletely: 0 },
            "итог прохода: два снесены, один с ошибкой; ошибка учтена, а не потеряна"
        );

        drop(busy);
    }

    /// 🔴 Сторож C2 п.3: осиротевший каталог сносится ЗАТИРАЮЩИМ удалением, а не
    /// `remove_dir_all`. Проверяется не «файла нет» (это верно и для обычного удаления), а то,
    /// что содержимое было перезаписано нулями ДО удаления: снимок берётся через посторонний
    /// дескриптор, открытый на чтение и разделяющий доступ, — он переживает удаление имени и
    /// показывает, что лежало в блоках файла на момент сноса.
    #[cfg(windows)]
    #[test]
    fn orphan_directory_is_zero_wiped_not_just_unlinked() {
        use std::io::{Read, Seek};
        use std::os::windows::fs::OpenOptionsExt;

        let tmp = tempfile::tempdir().unwrap();
        let sessions_dir = tmp.path().join("sessions");
        let orphan = sessions_dir.join("econometrist_orphan1");
        std::fs::create_dir_all(&orphan).unwrap();
        let secret = orphan.join("CLAUDE.md");
        std::fs::write(&secret, "СЕКРЕТ КАБИНЕТА").unwrap();

        // FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE = 7: наблюдатель не мешает ни
        // затиранию, ни удалению — он только смотрит на содержимое блоков.
        let mut observer = std::fs::OpenOptions::new()
            .read(true)
            .share_mode(7)
            .open(&secret)
            .unwrap();

        let summary = sweep_dir(&sessions_dir).unwrap();
        assert_eq!(summary.removed, 1, "осиротевший каталог обязан быть снесён");
        assert_eq!(
            summary.wiped_incompletely, 0,
            "затирание обязано пройти полностью: файл открыт с разделением доступа и не мешает"
        );

        observer.seek(std::io::SeekFrom::Start(0)).unwrap();
        let mut seen = Vec::new();
        observer.read_to_end(&mut seen).unwrap();
        assert!(
            !String::from_utf8_lossy(&seen).contains("СЕКРЕТ"),
            "содержимое обязано быть затёрто нулями ДО удаления: подмена secure_delete_dir на \
             remove_dir_all оставляет данные клиента восстановимыми с диска. Прочитано: {:?}",
            String::from_utf8_lossy(&seen)
        );
    }

    /// 🔴 Поправка M20: затирание, которое НЕ удалось, перестаёт быть тишиной. Файл держит
    /// посторонний с доступом на запись и без её разделения — перезаписать его нельзя, а удалить
    /// (доступ на удаление разделён) можно. Проход обязан пройти до конца, снести каталог и
    /// ЗАЯВИТЬ, что затирание неполное.
    #[cfg(windows)]
    #[test]
    fn wipe_that_could_not_be_performed_is_reported_not_silently_skipped() {
        use std::os::windows::fs::OpenOptionsExt;

        let tmp = tempfile::tempdir().unwrap();
        let sessions_dir = tmp.path().join("sessions");
        let orphan = sessions_dir.join("econometrist_orphan2");
        std::fs::create_dir_all(&orphan).unwrap();
        let secret = orphan.join("CLAUDE.md");
        std::fs::write(&secret, "СЕКРЕТ КАБИНЕТА").unwrap();

        // Открыт на ЗАПИСЬ, разделяются только чтение (1) и удаление (4) = 5. Чужое открытие на
        // запись отказывает (затирание невозможно), а `remove_file` проходит.
        let held = std::fs::OpenOptions::new()
            .write(true)
            .share_mode(5)
            .open(&secret)
            .unwrap();

        let summary = sweep_dir(&sessions_dir).unwrap();

        assert_eq!(
            summary.wiped_incompletely, 1,
            "невозможность затереть обязана попасть в итог прохода: иначе продукт молча сообщает \
             об успешной очистке, а расшифрованные файлы клиента восстановимы с диска"
        );
        assert_eq!(summary.removed, 1, "каталог при этом всё равно обязан быть снесён");
        assert_eq!(summary.failed, 0, "неполное затирание — это не отказ удаления");

        drop(held);
    }

    /// 🔴 Поправка M21: между созданием каталога сессии и взятием замка не должно быть окна.
    /// Первый каталог создан общей функцией `create_locked_session_dir` (создание + замок одним
    /// вызовом) — очистка, запущенная сразу после, обязана признать его живым. Второй каталог
    /// создан «в два шага» — ровно то состояние, в котором каталог застаёт очистка, если замок
    /// берут отдельным вызовом позже: он выглядит осиротевшим и сносится вместе с содержимым.
    /// Негативный контроль здесь обязателен: без него тест был бы зелёным и при полном
    /// отсутствии различения.
    #[cfg(windows)]
    #[test]
    fn session_dir_is_protected_from_the_moment_it_is_created() {
        let tmp = tempfile::tempdir().unwrap();
        let sessions_dir = tmp.path().join("sessions");

        let locked_at_once = sessions_dir.join("econometrist_atomic1");
        let lock = create_locked_session_dir(&locked_at_once)
            .unwrap()
            .expect("замок каталога сессии обязан браться при его создании");
        // Содержимое появляется ПОСЛЕ замка — так и работает распаковка vault'а.
        std::fs::write(locked_at_once.join("CLAUDE.md"), "расшифрованный файл кабинета").unwrap();

        // Окно старого порядка: каталог уже есть, замка ещё нет.
        let window = sessions_dir.join("econometrist_window1");
        std::fs::create_dir_all(&window).unwrap();
        std::fs::write(window.join("CLAUDE.md"), "расшифрованный файл кабинета").unwrap();

        let summary = sweep_dir(&sessions_dir).unwrap();

        assert!(
            locked_at_once.join("CLAUDE.md").exists(),
            "каталог, созданный ВМЕСТЕ с замком, очистка чужого экземпляра трогать не имеет права"
        );
        assert!(
            !window.exists(),
            "негативный контроль: каталог без замка выглядит осиротевшим и сносится — ровно это \
             и происходило бы в окне между созданием каталога и взятием замка"
        );
        assert_eq!(summary.alive, 1, "живым обязан считаться ровно один каталог");

        drop(lock);
    }

    /// 🔴 Батч C, C2 п.5: ЛЮБАЯ неудача открытия замка считалась «сессия живая», и при постоянной
    /// причине (сбиты права, файл держит служба) каталог с расшифрованными файлами не был бы
    /// снесён НИКОГДА, а в журнал шло бы спокойное `info`.
    /// Отнесение проверяется на НАСТОЯЩЕМ занятом замке, а не на выдуманной ошибке: именно так
    /// зонд опроверг первую редакцию контракта, где живую сессию предлагалось узнавать по
    /// `ErrorKind::PermissionDenied`.
    #[cfg(windows)]
    #[test]
    fn real_held_lock_is_classified_as_live_owner() {
        let tmp = tempfile::tempdir().unwrap();
        let lock_path = tmp.path().join(SESSION_LOCK_FILE);
        let held = open_session_lock(&lock_path).unwrap();

        let refusal = open_session_lock(&lock_path)
            .expect_err("второй монопольный захват того же файла обязан отказать");

        assert_eq!(
            classify_lock_refusal(&refusal),
            LockRefusal::LiveOwner,
            "занятый живым владельцем замок обязан относиться к живой сессии; система вернула \
             kind={:?}, raw_os_error={:?} — если код изменился, менять надо ЗДЕСЬ, а не гадать",
            refusal.kind(),
            refusal.raw_os_error()
        );
        drop(held);
    }

    /// Обратная сторона: отказ по ПРОЧЕЙ причине (нет прав — код 5, или ошибка без кода ОС)
    /// обязан относиться к «недоступен», иначе бессрочно лежащие расшифрованные файлы не будут
    /// видны в журнале.
    #[test]
    fn other_failures_are_classified_as_unreadable_not_as_a_live_session() {
        assert_eq!(
            classify_lock_refusal(&std::io::Error::from_raw_os_error(5)),
            LockRefusal::Unreadable,
            "«доступ запрещён» (код 5) — это сбитые права, а не живая сессия"
        );
        assert_eq!(
            classify_lock_refusal(&std::io::Error::new(
                std::io::ErrorKind::PermissionDenied,
                "ошибка без кода операционной системы"
            )),
            LockRefusal::Unreadable,
            "ErrorKind::PermissionDenied сам по себе живой сессией НЕ является — на Windows её \
             признак это код 32, а не вид ошибки"
        );
    }
}
