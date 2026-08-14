//! Возврат наследования прав доступа на каталоге сессий — лечение следа, оставленного прежними
//! версиями (хвост CPD-77).
//!
//! Что было. До правки `ea560be` продукт на каждом старте порождал
//! `icacls <каталог сессий> /inheritance:r /grant:r <ДОМЕН\пользователь>:(OI)(CI)F`.
//! `/inheritance:r` снимает с каталога наследование от родителя, а `/grant:r` ЗАМЕНЯЕТ список
//! прав целиком. В итоге на каталоге оставался ровно один элемент — текущий пользователь, а
//! SYSTEM и «Администраторы», приходившие по наследству из профиля, молча исчезали. Замер на
//! живой машине: `EVO-X1\ackol:(OI)(CI)(F)` против эталонных трёх элементов у соседнего каталога.
//!
//! Почему удаления вызова мало. Права — durable-состояние файловой системы: у всех, кто хоть раз
//! запускал прежнюю версию, каталог остался урезанным и сам не починится. Служебное копирование,
//! поиск и проверка антивирусом такой каталог обходят стороной, а администратор машины доступа к
//! нему не имеет.
//!
//! Почему системный вызов, а не возврат `icacls`. Порождение процесса, переставляющего права
//! прямо перед тем, как приложение начнёт писать и шифровать в этом каталоге, и есть тот образец
//! поведения, из-за которого 11.08.2026 Kaspersky снял оболочку продукта с диска у пользователя
//! (PDM:Trojan.Win32.Generic). Лечение обязано обойтись без порождения процессов.
//!
//! 🔴 Набор флагов проверен живым пробником на реальных каталогах 14.08.2026, а не выведен из
//! чтения документации, — два «очевидных» варианта оказались негодны:
//! - только `UNPROTECTED_DACL_SECURITY_INFORMATION` с пустым указателем на список → вызов
//!   возвращает отказ 5 (доступ запрещён) и не делает ничего, хотя вызывающий — владелец каталога;
//! - `DACL_SECURITY_INFORMATION | UNPROTECTED_DACL_SECURITY_INFORMATION` с пустым указателем на
//!   список → вызов УСПЕШЕН и ставит пустой (NULL) список прав, то есть «доступ разрешён всем»,
//!   а защита при этом остаётся включённой. Для каталога с расшифрованными данными клиента это
//!   было бы хуже исходной поломки.
//!
//! Рабочий набор — `DACL_SECURITY_INFORMATION | UNPROTECTED_DACL_SECURITY_INFORMATION` вместе с
//! ТЕМ ЖЕ списком прав, который только что прочитан с каталога: явные элементы остаются дословно,
//! флаг защиты снимается, и Windows сама возвращает унаследованные элементы от родителя, а заодно
//! раздаёт их существующим вложенным каталогам и файлам.

use std::path::{Component, Path};

/// Состояние списка прав каталога — ровно то, что нужно для решения «чинить или нет».
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DaclState {
    /// Наследование от родителя снято (`SE_DACL_PROTECTED`) — это и есть след прежних версий.
    Protected,
    /// Наследование включено — каталог здоров, трогать нечего.
    Inherited,
    /// Состояние прочитать не удалось (нет прав на чтение, каталог исчез, ошибка системы).
    Unreadable,
}

/// Чем закончилась попытка. Возвращается наружу только ради тестов и журнала: вызывающий код
/// продолжает работу при ЛЮБОМ исходе.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    /// Не Windows — на других целях прав в этом смысле нет.
    NotWindows,
    /// Путь не прошёл проверку «это наш каталог сессий внутри каталога приложения».
    Rejected,
    /// Каталога нет на диске.
    Missing,
    /// Состояние прочитать не удалось — не чиним (чинить вслепую нельзя).
    Unreadable,
    /// Наследование и так включено — не делаем ничего (обычный случай нового клиента).
    AlreadyInherited,
    /// Наследование возвращено.
    Restored,
    /// Починка не удалась (обычно нехватка прав) — код ошибки Windows.
    Failed(u32),
}

/// Решение по прочитанному состоянию. Чиним ТОЛЬКО при подтверждённой защите: непрочитанное
/// состояние — не повод трогать чужие права.
pub fn needs_restore(state: DaclState) -> bool {
    matches!(state, DaclState::Protected)
}

/// `child` лежит СТРОГО внутри `parent` (сам `parent` — не считается).
///
/// Сравнение покомпонентное и без учёта регистра: на Windows `C:\Users\X\AppData\Local` и
/// `C:\Users\x\appdata\local` — один каталог, а строковый `starts_with` этого не знает.
/// Компоненты `..` и `.` в любом из путей — сразу отказ: по дереву вверх не ходим.
pub fn is_inside(child: &Path, parent: &Path) -> bool {
    let norm = |p: &Path| -> Option<Vec<String>> {
        let mut out = Vec::new();
        for c in p.components() {
            match c {
                Component::ParentDir | Component::CurDir => return None,
                other => out.push(other.as_os_str().to_string_lossy().to_lowercase()),
            }
        }
        if out.is_empty() {
            None
        } else {
            Some(out)
        }
    };
    let (Some(child), Some(parent)) = (norm(child), norm(parent)) else {
        return false;
    };
    child.len() > parent.len() && child[..parent.len()] == parent[..]
}

/// Путь годится для починки: он лежит строго внутри каталога приложения и называется ровно так,
/// как называется подкаталог сессий. Обе проверки нужны, чтобы правка физически не могла
/// дотянуться ни до родителя, ни до чужого каталога, даже если путь однажды начнут строить иначе.
pub fn is_safe_target(dir: &Path, app_dir: &Path, expected_leaf: &str) -> bool {
    if !is_inside(dir, app_dir) {
        return false;
    }
    match dir.file_name() {
        Some(name) => name.to_string_lossy().eq_ignore_ascii_case(expected_leaf),
        None => false,
    }
}

#[cfg(windows)]
mod sys {
    //! Системная часть: чтение управляющего слова дескриптора и снятие флага защиты списка.

    use std::os::windows::ffi::OsStrExt;
    use std::path::Path;
    use std::ptr;

    use windows_sys::Win32::Foundation::{GetLastError, LocalFree, ERROR_SUCCESS};
    use windows_sys::Win32::Security::Authorization::{
        GetNamedSecurityInfoW, SetNamedSecurityInfoW, SE_FILE_OBJECT,
    };
    use windows_sys::Win32::Security::{
        GetSecurityDescriptorControl, ACL, DACL_SECURITY_INFORMATION,
        PROTECTED_DACL_SECURITY_INFORMATION, PSECURITY_DESCRIPTOR, SE_DACL_PROTECTED,
        UNPROTECTED_DACL_SECURITY_INFORMATION,
    };

    use super::DaclState;

    fn wide(path: &Path) -> Vec<u16> {
        path.as_os_str().encode_wide().chain(Some(0)).collect()
    }

    /// Прочитать, снято ли наследование. Дескриптор, который выдаёт система, освобождаем сами —
    /// иначе каждый старт продукта подтекал бы на размер дескриптора.
    pub fn read_dacl_state(dir: &Path) -> DaclState {
        let path = wide(dir);
        let mut descriptor: PSECURITY_DESCRIPTOR = ptr::null_mut();
        let rc = unsafe {
            GetNamedSecurityInfoW(
                path.as_ptr(),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                ptr::null_mut(),
                ptr::null_mut(),
                &mut descriptor,
            )
        };
        if rc != ERROR_SUCCESS {
            log::warn!(
                "Права каталога сессий {} не прочитаны (код {rc}) — наследование не проверяем",
                dir.display()
            );
            return DaclState::Unreadable;
        }
        let mut control: u16 = 0;
        let mut revision: u32 = 0;
        let ok = unsafe { GetSecurityDescriptorControl(descriptor, &mut control, &mut revision) };
        let err = if ok == 0 { unsafe { GetLastError() } } else { 0 };
        unsafe { LocalFree(descriptor as _) };
        if ok == 0 {
            log::warn!(
                "Управляющее слово прав каталога сессий {} не прочитано (код {err})",
                dir.display()
            );
            return DaclState::Unreadable;
        }
        if control & SE_DACL_PROTECTED != 0 {
            DaclState::Protected
        } else {
            DaclState::Inherited
        }
    }

    /// Переставить флаг защиты списка прав, оставив сам список дословно прежним.
    ///
    /// Список НЕ конструируется заново: он читается с каталога и передаётся обратно тем же
    /// указателем. Это и есть требование «не добавлять и не удалять явные элементы» — и
    /// одновременно единственный набор аргументов, который на живой проверке отработал верно
    /// (см. шапку модуля про два негодных варианта).
    fn set_dacl_protection(dir: &Path, protect: bool) -> Result<(), u32> {
        let path = wide(dir);
        let mut descriptor: PSECURITY_DESCRIPTOR = ptr::null_mut();
        let mut dacl: *mut ACL = ptr::null_mut();
        let rc = unsafe {
            GetNamedSecurityInfoW(
                path.as_ptr(),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                &mut dacl,
                ptr::null_mut(),
                &mut descriptor,
            )
        };
        if rc != ERROR_SUCCESS {
            return Err(rc);
        }
        // 🔴 Пустого списка прав быть не должно, но если система вернула именно его, чинить
        // нельзя: тот же вызов с пустым указателем ставит каталогу «доступ разрешён всем»
        // (проверено пробником). Каталог с расшифрованными данными клиента открытым не делаем —
        // выходим с ошибкой, дальше её подхватит журнал.
        if dacl.is_null() {
            unsafe { LocalFree(descriptor as _) };
            return Err(ERROR_INVALID_ACL);
        }
        let flag = if protect {
            PROTECTED_DACL_SECURITY_INFORMATION
        } else {
            UNPROTECTED_DACL_SECURITY_INFORMATION
        };
        let rc = unsafe {
            SetNamedSecurityInfoW(
                path.as_ptr(),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION | flag,
                ptr::null_mut(),
                ptr::null_mut(),
                dacl,
                ptr::null(),
            )
        };
        // `dacl` указывает ВНУТРЬ дескриптора, поэтому освобождается он ровно один раз и только
        // после того, как система дочитала список.
        unsafe { LocalFree(descriptor as _) };
        if rc == ERROR_SUCCESS {
            Ok(())
        } else {
            Err(rc)
        }
    }

    /// `ERROR_INVALID_ACL` — списка прав на каталоге нет вовсе.
    const ERROR_INVALID_ACL: u32 = 1336;

    pub(super) fn restore(dir: &Path) -> Result<(), u32> {
        set_dacl_protection(dir, false)
    }

    /// Только для теста: воспроизвести поломку, которую оставляли прежние версии.
    #[cfg(test)]
    pub(super) fn protect(dir: &Path) -> Result<(), u32> {
        set_dacl_protection(dir, true)
    }
}

#[cfg(windows)]
pub use sys::read_dacl_state;

/// Вернуть наследование прав каталогу сессий, если и только если прежние версии его сняли.
///
/// Контракт вызывающего: ни один исход не влияет на запуск приложения. Нехватка прав (каталог
/// сменил владельца, политика машины запрещает менять права) — обычная ситуация: пишем в журнал
/// и работаем дальше.
///
/// Отдельного файла-маркера «уже чинили» нет намеренно: признаком служит сама файловая система —
/// после успешной починки наследование включено, и следующий запуск уходит по ветке
/// `AlreadyInherited`, не доходя до записи прав. Маркер мог бы разойтись с реальностью, состояние
/// каталога разойтись с собой не может.
#[cfg(windows)]
pub fn restore_inheritance(
    dir: &Path,
    app_dir: &Path,
    local_app_data: &Path,
    expected_leaf: &str,
) -> Outcome {
    if !is_safe_target(dir, app_dir, expected_leaf) || !is_inside(app_dir, local_app_data) {
        log::warn!(
            "Каталог {} не опознан как каталог сессий продукта внутри {} — права не трогаем",
            dir.display(),
            local_app_data.display()
        );
        return Outcome::Rejected;
    }
    if !dir.is_dir() {
        return Outcome::Missing;
    }
    let state = read_dacl_state(dir);
    if !needs_restore(state) {
        return match state {
            DaclState::Unreadable => Outcome::Unreadable,
            _ => Outcome::AlreadyInherited,
        };
    }
    match sys::restore(dir) {
        Ok(()) => {
            log::info!(
                "Каталогу сессий {} возвращено наследование прав: прежние версии сняли его вместе \
                 с доступом SYSTEM и Администраторов",
                dir.display()
            );
            Outcome::Restored
        }
        Err(code) => {
            log::warn!(
                "Наследование прав каталога сессий {} вернуть не удалось (код {code}) — \
                 приложение продолжает работу, каталог останется с урезанными правами",
                dir.display()
            );
            Outcome::Failed(code)
        }
    }
}

/// Не-Windows: прав в этом смысле нет, делать нечего. Продукт поставляется только под Windows,
/// ветка нужна, чтобы крейт собирался на других целях.
#[cfg(not(windows))]
pub fn restore_inheritance(
    _dir: &Path,
    _app_dir: &Path,
    _local_app_data: &Path,
    _expected_leaf: &str,
) -> Outcome {
    Outcome::NotWindows
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    // ── Чистая логика решения: никаких системных вызовов ──────────────────────────────────

    #[test]
    fn protected_dir_is_repaired_and_healthy_one_is_left_alone() {
        assert!(needs_restore(DaclState::Protected), "снятое наследование обязано чиниться");
        assert!(
            !needs_restore(DaclState::Inherited),
            "здоровый каталог трогать нельзя — это и есть идемпотентность"
        );
        assert!(
            !needs_restore(DaclState::Unreadable),
            "непрочитанное состояние — не повод переписывать права вслепую"
        );
    }

    #[test]
    fn only_the_products_own_sessions_dir_passes_the_guard() {
        let app = PathBuf::from(r"C:\Users\u\AppData\Local\com.aurora.econometrica");
        let sessions = app.join("sessions");

        assert!(is_safe_target(&sessions, &app, "sessions"));
        // Регистр на Windows незначим — путь из переменной среды может прийти в любом.
        assert!(is_safe_target(
            &PathBuf::from(r"c:\users\u\appdata\local\COM.AURORA.ECONOMETRICA\Sessions"),
            &app,
            "sessions"
        ));

        assert!(!is_safe_target(&app, &app, "sessions"), "сам каталог приложения — не цель");
        assert!(
            !is_safe_target(app.parent().unwrap(), &app, "sessions"),
            "родителя не трогаем никогда"
        );
        assert!(
            !is_safe_target(&app.join("history"), &app, "sessions"),
            "соседний каталог состояния — не цель"
        );
        assert!(
            !is_safe_target(&PathBuf::from(r"C:\Windows\System32"), &app, "sessions"),
            "чужой каталог не проходит"
        );
        assert!(
            !is_safe_target(&app.join("..").join("sessions"), &app, "sessions"),
            "путь с переходом вверх отвергается целиком"
        );
    }

    #[test]
    fn app_dir_must_itself_live_under_local_app_data() {
        let local = PathBuf::from(r"C:\Users\u\AppData\Local");
        assert!(is_inside(&local.join("com.aurora.econometrica"), &local));
        assert!(!is_inside(&local, &local), "сам каталог — не «внутри себя»");
        assert!(
            !is_inside(&PathBuf::from(r"C:\ProgramData\com.aurora.econometrica"), &local),
            "каталог вне профиля пользователя не проходит"
        );
        assert!(
            !is_inside(&PathBuf::from(r"C:\Users\u\AppData\Local\..\Roaming\x"), &local),
            "«..» в середине пути — отказ"
        );
    }

    // ── Честная проверка на настоящем каталоге ────────────────────────────────────────────

    /// Полный круг на реальном каталоге: воспроизводим поломку прежних версий, чиним, читаем
    /// состояние обратно. Никаких заглушек — те же системные вызовы, что у клиента.
    ///
    /// Прав администратора тест не требует: владелец каталога всегда имеет `WRITE_DAC`.
    #[cfg(windows)]
    #[test]
    fn real_directory_loses_and_regains_inheritance() {
        let dir = std::env::temp_dir().join(format!(
            "aurora-acl-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&dir).expect("временный каталог не создан");
        let app_dir = dir.parent().unwrap().to_path_buf();
        let leaf = dir.file_name().unwrap().to_string_lossy().to_string();
        let local = app_dir.parent().expect("у временного каталога есть родитель").to_path_buf();

        // Свежий каталог наследует права — чинить нечего, вызов обязан быть пустым.
        assert_eq!(read_dacl_state(&dir), DaclState::Inherited);
        assert_eq!(
            restore_inheritance(&dir, &app_dir, &local, &leaf),
            Outcome::AlreadyInherited
        );

        // Воспроизводим ровно то, что оставляли прежние версии.
        sys::protect(&dir).expect("защиту списка прав поставить не удалось");
        assert_eq!(read_dacl_state(&dir), DaclState::Protected);

        assert_eq!(restore_inheritance(&dir, &app_dir, &local, &leaf), Outcome::Restored);
        assert_eq!(
            read_dacl_state(&dir),
            DaclState::Inherited,
            "после починки наследование обязано быть включено"
        );

        // Второй заход по тому же каталогу уже ничего не делает.
        assert_eq!(
            restore_inheritance(&dir, &app_dir, &local, &leaf),
            Outcome::AlreadyInherited
        );

        let _ = std::fs::remove_dir_all(&dir);
    }
}
