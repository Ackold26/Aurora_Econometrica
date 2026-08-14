//! Sidecar runtime - shared foundation для port discovery, version handshake,
//! per-user process isolation, state file management.
//!
//! **Canonical файл** для всех 10 Aurora-продуктов. Sync через sync_variants.py.
//!
//! # Архитектура
//!
//! На multi-user RDP-серверах TCP-порты - глобальный ресурс ОС. Захардкоженный
//! `:7430` → конфликт между пользователями: первый занимает, остальные переиспользуют
//! чужой sidecar → 404/500, смешивание контекстов.
//!
//! Решение:
//! 1. **Deterministic port** по хешу SID пользователя (stable, race-free).
//! 2. **Fallback на `bind(0)`** если preferred port занят (zombie от той же сессии).
//! 3. **State file** `%LOCALAPPDATA%\<identifier>\sidecar.json` - per-user gauranteed
//!    (НЕ `%APPDATA%` - тот роумит в AD-доменах).
//! 4. **Handshake `/health`** - {product, version, session_id} проверяется перед
//!    использованием. Mismatch → force kill + respawn.
//! 5. **Process owner detection** через WinAPI (OpenProcessToken + LookupAccountSidW),
//!    не `tasklist /V` - encoding hell на локализованной Windows.
//! 6. **Kill-switch** env `AURORA_SIDECAR_LEGACY_PORT=1` → bypass discovery,
//!    fallback на hardcoded port. Safety valve для прод-отката без rebuild.
//!
//! # Usage
//!
//! ```ignore
//! use crate::sidecar_runtime::{SidecarConfig, allocate_port, write_state_file};
//!
//! const CFG: SidecarConfig = SidecarConfig {
//!     product_id: "com.aurora.econometrica",
//!     version: env!("CARGO_PKG_VERSION"),
//!     legacy_port: 7430,
//!     identifier_dir: "com.aurora.econometrica",
//!     process_exe_hint: "econometrica-sidecar",
//! };
//!
//! let port = allocate_port(&CFG)?;
//! // spawn sidecar с аргументом port ...
//! write_state_file(&CFG, port, child.id(), &session_id)?;
//! ```

use std::net::TcpListener;
use std::path::PathBuf;
use std::time::Duration;

use chrono::{DateTime, Utc};
use log::{debug, info, warn};
use serde::{Deserialize, Serialize};

// ── Configuration ────────────────────────────────────────────────────────────

/// Per-product конфигурация sidecar. Задаётся как const в каждом продукте.
#[derive(Clone, Copy)]
pub struct SidecarConfig {
    /// Обратный domain ID, должен совпадать с `tauri.conf.json::identifier`.
    /// Пример: `"com.aurora.econometrica"`.
    pub product_id: &'static str,

    /// Версия продукта, читается Rust-side из `env!("CARGO_PKG_VERSION")`
    /// и передаётся в Python-sidecar через env `AURORA_PRODUCT_VERSION`.
    pub version: &'static str,

    /// Hardcoded port для legacy fallback (kill-switch) и для back-compat
    /// с pre-v1.0.9 бинарниками. Также база для user_scoped_port().
    pub legacy_port: u16,

    /// Имя поддиректории в `%LOCALAPPDATA%` для state file + logs.
    /// Пример: `"com.aurora.econometrica"`.
    pub identifier_dir: &'static str,

    /// Подстрока для определения «наш» ли процесс (case-insensitive).
    /// Пример: `"econometrica-sidecar"` или `"rag-server"`.
    pub process_exe_hint: &'static str,

    /// Дополнительные допустимые имена образа — ТОЛЬКО для продуктов, чей движок
    /// действительно запускается сторонним интерпретатором (например, dev-режим
    /// через `python server.py`).
    ///
    /// 🔴 Раньше `python`/`pythonw` принимались безусловно для ЛЮБОГО продукта, вне
    /// зависимости от того, python-овый ли у него движок. Это делало проверку имени
    /// образа почти бессодержательной: под неё подпадал любой Jupyter, Anaconda,
    /// языковой модуль редактора и движок соседнего продукта Aurora. Теперь список
    /// задаёт сам продукт и, как правило, он пуст в релизной сборке.
    pub extra_image_hints: &'static [&'static str],
}

// ── Types ────────────────────────────────────────────────────────────────────

/// Содержимое state file `%LOCALAPPDATA%\<identifier>\sidecar.json`.
/// Записывается Rust после успешного handshake на cold start.
/// Читается Rust при reconnect - если handshake подтверждает session_id,
/// переиспользуется; иначе считается stale → respawn.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SidecarState {
    pub port: u16,
    pub pid: u32,
    pub session_id: String,
    pub product: String,
    pub version: String,
    pub user: String,
    pub started_at: String,

    /// Полный путь к образу ПОРОЖДЁННОГО нами процесса, снятый сразу после запуска
    /// (`QueryFullProcessImageNameW`).
    ///
    /// 🔴 2026-08-14. Поле СПРАВОЧНОЕ: журнал и разбор случая у клиента. Основанием
    /// для снятия оно быть перестало — записанное устаревает, а решение теперь
    /// сверяет путь запущенного процесса с путём движка В ЭТОЙ УСТАНОВКЕ
    /// (`econ_sidecar::expected_engine_image_path`), то есть со статическим фактом,
    /// которому устаревать нечем.
    ///
    /// Обратная совместимость: у файла состояния прежних версий поля нет, `serde`
    /// подставит пустую строку — на переподключение к живому движку это не влияет.
    #[serde(default)]
    pub image_path: String,
}

/// Ответ `/health` endpoint'а. Схема расширена в v1.0.9.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthInfo {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub version: String,
    #[serde(default)]
    pub product: String,
    #[serde(default)]
    pub session_id: String,
    #[serde(default)]
    pub pid: u32,
    #[serde(default)]
    pub started_at: String,
}

// ── Решение о снятии процесса (чистая логика, без системных вызовов) ─────────

/// Свойства реально существующего процесса, снятые системным слоем
/// (`observe_process`). Все поля необязательные: если системный вызов не удался,
/// значение остаётся `None`, и решение обязано быть консервативным.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ObservedProcess {
    /// Владелец в виде `DOMAIN\user` либо `user`.
    pub owner: Option<String>,
    /// Полный путь к образу процесса (`QueryFullProcessImageNameW`).
    pub image_path: Option<String>,
    /// Момент создания процесса по системным часам, в UTC (`GetProcessTimes`).
    pub created_at: Option<DateTime<Utc>>,
}

/// Почему процесс решено НЕ снимать. Попадает в журнал и в тесты.
///
/// 🔴 2026-08-14. Прежний набор причин описывал сверку с ЗАПИСЬЮ в файле состояния
/// (`pid`, `image_path`, `started_at`). Основание сменилось: держателя порта теперь
/// называет сама операционная система, и устаревать записи больше нечему. Причины
/// «создан вне окна вокруг started_at», «started_at не разбирается», «время создания
/// неизвестно», «полный путь не совпал с записанным», «нулевой идентификатор»,
/// «запись от другого продукта» и «запись от другого пользователя» отсюда ушли
/// вместе с проверками, которые их порождали.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SkipReason {
    /// Порт никто не слушает — снимать нечего.
    NoListener,
    /// Порт слушают несколько РАЗНЫХ процессов (двойной стек, разные адреса на одном
    /// номере). Кто из них наш — неизвестно, и гадать нельзя.
    HolderAmbiguous,
    /// Держатель порта — сама оболочка продукта. Защита от самоубийства.
    SelfPid,
    /// Дескриптор держателя не открылся: процесс успел завершиться либо нет прав.
    ObserveFailed,
    /// Владельца процесса определить не удалось.
    OwnerUnknown,
    /// Владелец процесса — другой пользователь ОС.
    OwnerMismatch,
    /// Путь к образу процесса определить не удалось.
    ImageUnknown,
    /// Имя образа не наше (запасная сверка там, где ожидаемый путь неизвестен).
    ImageMismatch,
    /// Полный путь образа не совпал с движком ЭТОЙ установки — чужой процесс на
    /// нашем номере порта либо движок другой редакции продукта.
    ImagePathNotOurs,
    /// Между первым опросом и удержанием дескриптора держатель порта сменился.
    HolderChanged,
}

impl SkipReason {
    /// Пояснение на русском — для журнала приложения.
    pub fn as_str(&self) -> &'static str {
        match self {
            SkipReason::NoListener => "порт никто не слушает",
            SkipReason::HolderAmbiguous => "порт слушают несколько разных процессов",
            SkipReason::SelfPid => "держатель порта — сама оболочка продукта",
            SkipReason::ObserveFailed => "дескриптор держателя порта не открылся",
            SkipReason::OwnerUnknown => "владелец процесса неизвестен",
            SkipReason::OwnerMismatch => "процесс принадлежит другому пользователю",
            SkipReason::ImageUnknown => "путь к образу процесса неизвестен",
            SkipReason::ImageMismatch => "образ процесса не наш",
            SkipReason::ImagePathNotOurs => {
                "полный путь образа не совпадает с движком этой установки"
            }
            SkipReason::HolderChanged => "держатель порта сменился между опросами",
        }
    }
}

impl std::fmt::Display for SkipReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Итог проверки: снимать процесс или нет (и почему нет).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KillVerdict {
    Kill,
    Skip(SkipReason),
}

impl KillVerdict {
    pub fn is_kill(&self) -> bool {
        matches!(self, KillVerdict::Kill)
    }
}

/// Сравнение владельца процесса с текущим пользователем.
/// `owner` приходит как `DOMAIN\user` либо `user`; в файле состояния и в
/// `current_user_name()` домена нет, поэтому сверяем хвост.
fn owner_matches(owner: &str, current_user: &str) -> bool {
    let owner_lc = owner.trim().to_lowercase();
    let me_lc = current_user.trim().to_lowercase();
    if me_lc.is_empty() || me_lc == "unknown" {
        return false;
    }
    owner_lc == me_lc || owner_lc.ends_with(&format!("\\{me_lc}"))
}

/// Сверка образа процесса с ожидаемыми именами продукта.
///
/// Работаем с ПОЛНЫМ путём (`QueryFullProcessImageNameW`), берём имя файла без
/// расширения и сверяем его с `process_exe_hint` и `extra_image_hints`. Это строже
/// прежнего «вывод `tasklist` содержит подстроку»: подстрока могла совпасть с чем
/// угодно в строке вывода, а имя файла — ровно то, что запущено.
///
/// Допускается совпадение по началу имени (`python` ↔ `python3`): версии
/// интерпретатора различаются суффиксом, а не префиксом.
pub fn image_matches(image_path: Option<&str>, cfg: &SidecarConfig) -> bool {
    let Some(path) = image_path else {
        return false;
    };
    let file_name = path
        .rsplit(['\\', '/'])
        .next()
        .unwrap_or(path)
        .to_lowercase();
    let stem = file_name
        .strip_suffix(".exe")
        .unwrap_or(&file_name)
        .to_string();
    if stem.is_empty() {
        return false;
    }

    // 🔴 Medium-8 внешнего аудита 2.4.9. Совпадение ПО НАЧАЛУ имени принимается только
    // для сторонних интерпретаторов, где оно и было нужно: версия отличается суффиксом
    // (`python` ↔ `python3`), а не префиксом. Для собственного образа продукта сверка
    // строгая: иначе под неё подпадали `econometrica-sidecar-backup.exe`,
    // `econometrica-sidecar-old.exe` и любая переименованная копия рядом.
    let own_name_matches = {
        let hint = cfg.process_exe_hint.to_lowercase();
        !hint.is_empty() && stem == hint
    };
    own_name_matches
        || cfg
            .extra_image_hints
            .iter()
            .filter(|h| !h.is_empty())
            .any(|hint| {
                let hint_lc = hint.to_lowercase();
                stem == hint_lc || stem.starts_with(&hint_lc)
            })
}

/// Сверка ПОЛНОГО пути образа с ожидаемым путём движка этой установки.
///
/// 🔴 Проверка имени файла ([`image_matches`]) не различает две редакции продукта:
/// `product_id` у них намеренно одинаков (рукопожатие с Python-модулем), образ —
/// один и тот же файл `econometrica-sidecar.exe`, пользователь один. Отличается
/// только каталог установки, и он же — единственный признак, который остаётся.
///
/// Приводим обе стороны к одному написанию: разделители к `\` (обе формы
/// равноправны в вызовах Windows, но приходят из разных источников), отбрасываем
/// префикс `\\?\` (`QueryFullProcessImageNameW` с `PROCESS_NAME_WIN32` его не
/// добавляет, а `std::fs::canonicalize` — добавляет всегда) и сравниваем без учёта
/// регистра: пути Windows регистронезависимы.
///
/// 🔴 Расхождение написания — самое вероятное место тихого регресса «зомби перестал
/// сниматься»: раньше обе строки происходили из ОДНОГО источника (путь снимался у
/// живого процесса и записывался в файл состояния), теперь источника два — путь
/// установки и путь запущенного процесса. Короткие имена 8.3 и символические ссылки
/// эта функция снять не может: они разрешаются раньше, в
/// [`canonical_path_for_compare`], на системном слое.
pub fn image_path_matches(expected: &str, observed: &str) -> bool {
    fn normalize(p: &str) -> String {
        let t = p.trim().replace('/', "\\");
        let t = t
            .strip_prefix(r"\\?\UNC\")
            .map(|rest| format!(r"\\{rest}"))
            .unwrap_or_else(|| t.strip_prefix(r"\\?\").unwrap_or(&t).to_string());
        t.to_lowercase()
    }
    let a = normalize(expected);
    let b = normalize(observed);
    !a.is_empty() && a == b
}

/// Приводит путь к единственному написанию перед сравнением: разрешает короткие
/// имена 8.3 (`PROGRA~1`), символические ссылки и относительные звенья.
///
/// Системный вызов, поэтому вне чистой функции решения: вызывающая сторона
/// применяет его к ОБЕИМ строкам до сравнения. Если разрешить не удалось (файла нет,
/// нет прав) — возвращается исходная строка, и сравнение опирается только на
/// нормализацию внутри [`image_path_matches`].
pub fn canonical_path_for_compare(path: &str) -> String {
    match std::fs::canonicalize(path) {
        Ok(p) => p.to_string_lossy().into_owned(),
        Err(_) => path.to_string(),
    }
}

/// Факты о держателе порта, собранные системным слоем для чистого решения
/// [`should_kill_port_holder`].
///
/// Оба перечня держателей — снимки ответа операционной системы, взятые в РАЗНЫЕ
/// моменты: `holders` до открытия дескриптора, `holders_after` — после. Именно их
/// расхождение закрывает гонку, которую удержание дескриптора закрыть не может
/// (см. [`should_kill_port_holder`]).
pub struct PortHolderFacts<'a> {
    /// Кто слушал порт по ПЕРВОМУ опросу. Нулевые и повторяющиеся номера
    /// отбрасываются в [`holder_worth_observing`], чистить их заранее не нужно.
    pub holders: &'a [u32],
    /// Номер процесса самой оболочки — защита от самоубийства.
    pub self_pid: u32,
    /// Свойства держателя, снятые по УДЕРЖИВАЕМОМУ дескриптору. `None` — дескриптор
    /// не открылся. Полный путь образа здесь ожидается уже канонизированным
    /// ([`canonical_path_for_compare`]).
    pub observed: Option<&'a ObservedProcess>,
    /// Кто слушает порт по ПОВТОРНОМУ опросу, уже после удержания дескриптора.
    pub holders_after: &'a [u32],
    /// Полный путь образа движка в ЭТОЙ установке, канонизированный. `None` —
    /// ожидаемый путь неизвестен (отладочная сборка, где движок запускается
    /// интерпретатором), тогда сверка откатывается на имя образа.
    pub expected_image_path: Option<&'a str>,
}

/// Первый рубеж: стоит ли вообще открывать дескриптор держателя порта.
///
/// Вынесен отдельно от [`should_kill_port_holder`], потому что наблюдение — это
/// системный вызов, а самоубийство и «слушать некому» надо отсечь ДО него. Логика
/// живёт в одном месте: полное решение начинается с вызова этой же функции.
///
/// Нулевые номера отбрасываются (`GetExtendedTcpTable` отдаёт `0` там, где владельца
/// назвать не может), одинаковые — схлопываются: движок может держать порт двумя
/// записями сразу, и это по-прежнему ОДИН процесс.
pub fn holder_worth_observing(holders: &[u32], self_pid: u32) -> Result<u32, SkipReason> {
    let mut distinct: Vec<u32> = holders.iter().copied().filter(|p| *p != 0).collect();
    distinct.sort_unstable();
    distinct.dedup();

    match distinct.as_slice() {
        [] => Err(SkipReason::NoListener),
        [pid] if *pid == self_pid => Err(SkipReason::SelfPid),
        [pid] => Ok(*pid),
        _ => Err(SkipReason::HolderAmbiguous),
    }
}

/// Чистое решение «снимать ли процесс, который держит наш порт».
///
/// 🔴 CPD-79. Прежде решение принималось по НАШЕЙ ЖЕ записи в файле состояния: номер
/// процесса, путь образа и время старта, записанные при запуске движка. Файл
/// переживает падение приложения, Windows после перезагрузки раздаёт номера заново,
/// и записанный номер мог достаться постороннему процессу — у пользователя молча
/// снимался чужой расчёт. Заплатой служило окно допуска по времени создания: оно
/// лечило симптом, а не причину, и само по себе оставалось окном, в котором чужой
/// процесс проходил проверку.
///
/// Основание сменилось целиком: держателя порта называет операционная система в
/// ответ на вопрос «кто слушает этот порт СЕЙЧАС» (`GetExtendedTcpTable`), а
/// ожидаемый путь образа берётся из установки, а не из записи. Устаревать больше
/// нечему.
///
/// Порядок проверок — от дешёвых к дорогим; каждая может только запретить снятие.
/// Любая неопределённость трактуется как запрет: не снять своего зомби дешевле, чем
/// убить чужой расчёт. Зомби максимум удержит порт, а `allocate_port` в этом случае
/// возьмёт свободный — потеря восстановима без участия пользователя.
///
/// 🔴 Почему переспрос держателя обязателен, хотя дескриптор удерживается. Дескриптор
/// гарантирует, что номер не будет переиспользован ПОСЛЕ открытия. Зазор между первым
/// опросом таблицы и открытием дескриптора он не закрывает: держатель мог завершиться
/// сразу после ответа таблицы, а номер — уйти другому, и удержан оказался бы уже не
/// тот процесс. Повторный вопрос системе стоит те же миллисекунды и закрывает этот
/// зазор целиком.
pub fn should_kill_port_holder(
    facts: &PortHolderFacts,
    cfg: &SidecarConfig,
    current_user: &str,
) -> KillVerdict {
    // 1–2. Держатель есть, он один и это не мы.
    let holder = match holder_worth_observing(facts.holders, facts.self_pid) {
        Ok(pid) => pid,
        Err(reason) => return KillVerdict::Skip(reason),
    };

    // 3. Дескриптор удержан, свойства сняты.
    let Some(observed) = facts.observed else {
        return KillVerdict::Skip(SkipReason::ObserveFailed);
    };

    // 4. Владелец процесса — дёшево отсекает чужого пользователя на общей машине
    //    (инвариант RDP, ради которого этот код и писался).
    let Some(owner) = observed.owner.as_deref() else {
        return KillVerdict::Skip(SkipReason::OwnerUnknown);
    };
    if !owner_matches(owner, current_user) {
        return KillVerdict::Skip(SkipReason::OwnerMismatch);
    }

    // 5. Образ процесса. Основной путь — полное совпадение с движком этой установки;
    //    он же различает облачную и локальную редакции продукта. Запасной — сверка
    //    имени образа: только там, где ожидаемый путь неизвестен (отладочная сборка).
    let Some(observed_image) = observed.image_path.as_deref() else {
        return KillVerdict::Skip(SkipReason::ImageUnknown);
    };
    match facts.expected_image_path {
        Some(expected) if !expected.trim().is_empty() => {
            if !image_path_matches(expected, observed_image) {
                return KillVerdict::Skip(SkipReason::ImagePathNotOurs);
            }
        }
        _ => {
            if !image_matches(Some(observed_image), cfg) {
                return KillVerdict::Skip(SkipReason::ImageMismatch);
            }
        }
    }

    // 6. Переспрос: держатель тот же самый и по-прежнему один.
    match holder_worth_observing(facts.holders_after, facts.self_pid) {
        Ok(pid) if pid == holder => KillVerdict::Kill,
        _ => KillVerdict::Skip(SkipReason::HolderChanged),
    }
}

// ── Кто держит порт (системный слой) ─────────────────────────────────────────

/// Номера процессов, которые ПРЯМО СЕЙЧАС слушают этот TCP-порт.
///
/// Опрашиваются обе таблицы — IPv4 и IPv6: движок слушает `127.0.0.1`, но
/// хардкодить это нельзя. На части машин запись оказывается в таблице другого
/// семейства адресов, и односемейный опрос молча не нашёл бы держателя — зомби
/// перестал бы сниматься без единого сообщения в журнале.
///
/// 🔴 Никаких подпроцессов. Прежде тот же вопрос задавался через
/// `cmd /C "… -ano | … :порт"` — три скрытых консольных процесса, и получалась связка
/// «разведка процессов по порту → снятие найденного», которую поведенческая защита
/// антивируса разбирает как вредоносную (10.08.2026 Kaspersky снял оболочку продукта
/// с диска у пользователя, вердикт PDM:Trojan.Win32.Generic). Прямой системный вызов
/// не порождает процессов вовсе и стоит 7–15 мс на полный перечень.
///
/// Список может содержать повторы и нули — чистит их [`holder_worth_observing`].
/// Пустой список означает «никто не слушает» ЛИБО «спросить не удалось»: разница для
/// решения несущественна, обе трактуются как «снимать нечего».
pub fn listening_port_owners(port: u16) -> Vec<u32> {
    #[cfg(windows)]
    {
        win_impl::listening_port_owners_impl(port)
    }
    #[cfg(not(windows))]
    {
        let _ = port;
        Vec::new()
    }
}

// ── User identity (Windows-specific via WinAPI) ──────────────────────────────

/// Возвращает SID текущего пользователя как строку S-1-5-21-... или None.
/// На не-Windows - возвращает USER/USERNAME env как fallback (не для продакшна).
pub fn current_user_sid() -> Option<String> {
    #[cfg(windows)]
    {
        win_impl::current_user_sid_impl()
    }
    #[cfg(not(windows))]
    {
        std::env::var("USER").or_else(|_| std::env::var("USERNAME")).ok()
    }
}

/// Возвращает имя текущего пользователя (без домена).
/// На Windows - `GetUserNameW`; на других - $USER/%USERNAME%.
pub fn current_user_name() -> String {
    #[cfg(windows)]
    {
        win_impl::current_user_name_impl().unwrap_or_else(|| "unknown".to_string())
    }
    #[cfg(not(windows))]
    {
        std::env::var("USER")
            .or_else(|_| std::env::var("USERNAME"))
            .unwrap_or_else(|_| "unknown".to_string())
    }
}

// ── Port allocation ──────────────────────────────────────────────────────────

/// Deterministic per-user порт: `base + (xxhash(SID) % 100)`.
/// Возвращает тот же порт для того же юзера при каждом вызове.
/// Если SID недоступен - fallback на hash имени пользователя.
/// Если и это fail - возвращает `base` (legacy-режим).
pub fn user_scoped_port(base: u16) -> u16 {
    use xxhash_rust::xxh3::xxh3_64;

    let sid_or_name = current_user_sid().unwrap_or_else(current_user_name);
    if sid_or_name.is_empty() || sid_or_name == "unknown" {
        warn!("user_scoped_port: cannot determine user identity, using legacy port {base}");
        return base;
    }
    let hash = xxh3_64(sid_or_name.as_bytes());
    let offset = (hash % 100) as u16;
    base + offset
}

/// Проверяет, свободен ли TCP-порт на 127.0.0.1.
pub fn port_is_free(port: u16) -> bool {
    TcpListener::bind(("127.0.0.1", port)).is_ok()
}

/// Находит порт для этого юзера. Strategy:
/// 1. Если kill-switch `AURORA_SIDECAR_LEGACY_PORT=1` → вернуть `cfg.legacy_port`.
/// 2. Deterministic port по SID → если свободен, вернуть.
/// 3. Иначе - `bind(0)` OS-assigned ephemeral.
pub fn allocate_port(cfg: &SidecarConfig) -> std::io::Result<u16> {
    if is_kill_switch_enabled() {
        info!(
            "allocate_port: kill-switch enabled (AURORA_SIDECAR_LEGACY_PORT=1), \
             using legacy port {}",
            cfg.legacy_port
        );
        return Ok(cfg.legacy_port);
    }

    let preferred = user_scoped_port(cfg.legacy_port);
    if port_is_free(preferred) {
        debug!("allocate_port: using user-scoped port {preferred}");
        return Ok(preferred);
    }

    // Preferred занят - возможно, zombie от нашей сессии. Пробуем OS-assigned.
    warn!(
        "allocate_port: preferred port {preferred} busy (zombie?), \
         falling back to OS-assigned ephemeral"
    );
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

// ── Kill-switch ──────────────────────────────────────────────────────────────

/// Env var `AURORA_SIDECAR_LEGACY_PORT=1` - bypass port discovery,
/// использовать hardcoded port. Safety valve для прод-отката без rebuild.
pub fn is_kill_switch_enabled() -> bool {
    matches!(
        std::env::var("AURORA_SIDECAR_LEGACY_PORT")
            .unwrap_or_default()
            .as_str(),
        "1" | "true" | "yes"
    )
}

/// Env var `AURORA_SKIP_HANDSHAKE=1` - пропускать version/product check в handshake.
/// Оставляет только базовый HTTP health. Safety valve при thrashing'е.
pub fn is_handshake_disabled() -> bool {
    matches!(
        std::env::var("AURORA_SKIP_HANDSHAKE")
            .unwrap_or_default()
            .as_str(),
        "1" | "true" | "yes"
    )
}

// ── State file I/O ───────────────────────────────────────────────────────────

/// Путь к sidecar.json в `%LOCALAPPDATA%\<identifier_dir>\sidecar.json`.
/// Используется `%LOCALAPPDATA%` а не `%APPDATA%` - AppData\Local гарантированно
/// не роумит между RDP-серверами в AD-доменах.
pub fn state_file_path(cfg: &SidecarConfig) -> PathBuf {
    let base = if cfg!(windows) {
        std::env::var("LOCALAPPDATA")
            .ok()
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                // Fallback если LOCALAPPDATA не установлена (necessary на старых Windows)
                let home = std::env::var("USERPROFILE").unwrap_or_else(|_| ".".to_string());
                PathBuf::from(home).join("AppData").join("Local")
            })
    } else {
        // На Unix - ~/.local/share (XDG). Для тестов/CI.
        let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        PathBuf::from(home).join(".local").join("share")
    };

    base.join(cfg.identifier_dir).join("sidecar.json")
}

/// Atomic write: tmp + rename. На Windows используется MoveFileEx с
/// MOVEFILE_REPLACE_EXISTING (через std::fs::rename - корректно работает на NTFS).
pub fn write_state_file(cfg: &SidecarConfig, state: &SidecarState) -> std::io::Result<()> {
    let path = state_file_path(cfg);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension("json.tmp");

    let json = serde_json::to_string_pretty(state)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;
    std::fs::write(&tmp, json)?;
    std::fs::rename(&tmp, &path)?;
    debug!("write_state_file: {}", path.display());
    Ok(())
}

/// Читает state file, возвращает None если файла нет или он битый.
/// Битый файл логируется но не ломает startup (просто respawn заново).
pub fn read_state_file(cfg: &SidecarConfig) -> Option<SidecarState> {
    let path = state_file_path(cfg);
    let raw = std::fs::read_to_string(&path).ok()?;
    match serde_json::from_str::<SidecarState>(&raw) {
        Ok(s) => Some(s),
        Err(e) => {
            warn!(
                "read_state_file: corrupt sidecar.json at {} ({e}) - ignoring",
                path.display()
            );
            None
        }
    }
}

/// Удаление state file при graceful shutdown. Не ошибка если файла нет.
pub fn delete_state_file(cfg: &SidecarConfig) {
    let path = state_file_path(cfg);
    if path.exists() {
        if let Err(e) = std::fs::remove_file(&path) {
            warn!("delete_state_file: {} ({e})", path.display());
        }
    }
}

// ── Session ID ───────────────────────────────────────────────────────────────

/// Генерирует новый session_id - короткий UUID v4 hex.
pub fn generate_session_id() -> String {
    uuid::Uuid::new_v4().simple().to_string()
}

// ── Handshake ────────────────────────────────────────────────────────────────

/// Проверяет handshake с sidecar на указанном порту.
/// Возвращает HealthInfo если:
/// - HTTP `/health` вернул 200
/// - `product` совпадает с `cfg.product_id`
/// - `version` присутствует (строгость check'а решает caller)
///
/// Если `AURORA_SKIP_HANDSHAKE=1` - возвращает минимальный HealthInfo без проверок.
pub async fn verify_handshake(
    port: u16,
    cfg: &SidecarConfig,
    client: &reqwest::Client,
) -> Option<HealthInfo> {
    let url = format!("http://127.0.0.1:{port}/health");
    let resp = client.get(&url).send().await.ok()?;
    if !resp.status().is_success() {
        debug!("verify_handshake: {url} returned {}", resp.status());
        return None;
    }
    let info = resp.json::<HealthInfo>().await.ok()?;

    if is_handshake_disabled() {
        debug!("verify_handshake: AURORA_SKIP_HANDSHAKE=1, returning without product check");
        return Some(info);
    }

    if !info.product.is_empty() && info.product != cfg.product_id {
        warn!(
            "verify_handshake: product mismatch on port {port} - expected {}, got '{}'. \
             Foreign sidecar, will respawn.",
            cfg.product_id, info.product
        );
        return None;
    }

    Some(info)
}

/// Convenience: создаёт reqwest client с коротким timeout для /health probes.
pub fn handshake_client() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .unwrap_or_default()
}

// ── Process owner detection ──────────────────────────────────────────────────

/// Получает owner процесса (formatted как `DOMAIN\user` или `user`) через WinAPI.
/// Fallback: None - caller должен трактовать как "неизвестно, не убиваем".
pub fn get_process_owner(pid: u32) -> Option<String> {
    #[cfg(windows)]
    {
        win_impl::get_process_owner_impl(pid)
    }
    #[cfg(not(windows))]
    {
        let _ = pid;
        None
    }
}

/// Снимает свойства процесса одним открытием дескриптора: владелец, полный путь
/// к образу, время создания. Любое поле остаётся `None`, если системный вызов
/// не удался — вызывающая сторона обязана трактовать это как «не трогаем».
///
/// Один `OpenProcess` на все три запроса: и дешевле, и без гонки, при которой
/// между двумя открытиями номер процесса успевает смениться.
pub fn observe_process(pid: u32) -> ObservedProcess {
    #[cfg(windows)]
    {
        win_impl::observe_process_impl(pid)
    }
    #[cfg(not(windows))]
    {
        let _ = pid;
        ObservedProcess::default()
    }
}

/// Наблюдаемый процесс с УДЕРЖИВАЕМЫМ дескриптором: свойства сняты, дескриптор
/// открыт и живёт до снятия либо до выхода значения из области видимости.
///
/// 🔴 Зачем удерживать. [`observe_process`] открывает дескриптор, снимает свойства и
/// закрывает его; решение принимается уже по закрытому. Пока между решением и
/// снятием стоял `taskkill /PID n`, между этими двумя моментами лежало порождение
/// целого процесса — десятки миллисекунд, на загруженной машине больше. Если
/// наблюдаемый процесс за это время завершился сам, его номер немедленно доступен
/// к переиспользованию, и снималось бы то, что этот номер успело получить: вся
/// проверка в этот момент не действует вовсе. Windows не переиспользует номер, пока
/// жив хотя бы один дескриптор процесса, — удержание закрывает гонку бесплатно.
pub struct HeldProcess {
    pid: u32,
    observed: ObservedProcess,
    #[cfg(windows)]
    handle: win_impl::OwnedProcessHandle,
}

impl HeldProcess {
    pub fn pid(&self) -> u32 {
        self.pid
    }

    /// Свойства, снятые в момент открытия дескриптора.
    pub fn observed(&self) -> &ObservedProcess {
        &self.observed
    }

    /// Есть ли право на снятие. Если дескриптор удалось открыть только на чтение
    /// свойств, снимать придётся вызывающей стороне другим способом.
    pub fn can_terminate(&self) -> bool {
        #[cfg(windows)]
        {
            self.handle.can_terminate()
        }
        #[cfg(not(windows))]
        {
            false
        }
    }

    /// Ждёт фактического завершения процесса после [`Self::terminate`].
    /// `true` — завершился в отведённое время.
    pub fn wait_exit(&self, timeout_ms: u32) -> bool {
        #[cfg(windows)]
        {
            self.handle.wait_exit(timeout_ms)
        }
        #[cfg(not(windows))]
        {
            let _ = timeout_ms;
            false
        }
    }

    /// Снятие процесса по удерживаемому дескриптору (`TerminateProcess`).
    ///
    /// Снимает ТОЛЬКО сам процесс, без дерева потомков — в отличие от снятия
    /// деревом. Обоснование, почему для этого движка так можно, — у вызывающей
    /// стороны (`econ_sidecar::kill_port_holder`).
    pub fn terminate(&self) -> Result<(), String> {
        #[cfg(windows)]
        {
            self.handle.terminate()
        }
        #[cfg(not(windows))]
        {
            Err("снятие по дескриптору доступно только на Windows".to_string())
        }
    }
}

/// Открывает дескриптор процесса, снимает свойства и ОСТАВЛЯЕТ дескриптор открытым.
/// `None` — процесса нет либо дескриптор открыть не удалось (тогда снимать нечего:
/// решение и так обязано быть консервативным).
pub fn hold_and_observe(pid: u32) -> Option<HeldProcess> {
    #[cfg(windows)]
    {
        if pid == 0 {
            return None;
        }
        let handle = win_impl::open_process_for_kill(pid)?;
        let observed = handle.observe();
        Some(HeldProcess {
            pid,
            observed,
            handle,
        })
    }
    #[cfg(not(windows))]
    {
        let _ = pid;
        None
    }
}

/// Проверяет что процесс PID:
/// 1. Принадлежит текущему OS-пользователю (multi-tenant safety)
/// 2. Имя образа входит в список ожидаемых имён продукта
///    (`cfg.process_exe_hint` + `cfg.extra_image_hints`)
///
/// Никогда не возвращает true для процесса другого пользователя -
/// security invariant для RDP.
///
/// 🔴 Этой проверки НЕДОСТАТОЧНО для решения о снятии процесса: она ничего не
/// знает ни о том, держит ли процесс наш порт, ни о переиспользовании номера
/// процесса операционной системой. Решение принимает [`should_kill_port_holder`]
/// (CPD-79).
pub fn is_our_process_and_user(pid: u32, cfg: &SidecarConfig) -> bool {
    #[cfg(windows)]
    {
        let observed = observe_process(pid);
        let Some(owner) = observed.owner.as_deref() else {
            debug!("is_our_process_and_user: owner unknown for PID={pid}, NOT killing (safe default)");
            return false;
        };
        let me = current_user_name();
        if !owner_matches(owner, &me) {
            debug!(
                "is_our_process_and_user: PID={pid} owner={owner} ≠ current user {me}, NOT killing"
            );
            return false;
        }

        image_matches(observed.image_path.as_deref(), cfg)
    }
    #[cfg(not(windows))]
    {
        let _ = (pid, cfg);
        false
    }
}

// ── Windows-specific implementations ─────────────────────────────────────────

#[cfg(windows)]
mod win_impl {
    use chrono::{DateTime, Utc};
    use log::debug;
    use windows_sys::Win32::{
        Foundation::{
            CloseHandle, LocalFree, ERROR_INSUFFICIENT_BUFFER, FILETIME, HANDLE, HLOCAL,
        },
        NetworkManagement::IpHelper::{
            GetExtendedTcpTable, MIB_TCP6TABLE_OWNER_PID, MIB_TCPTABLE_OWNER_PID,
            TCP_TABLE_OWNER_PID_LISTENER,
        },
        Networking::WinSock::{AF_INET, AF_INET6},
        Security::{
            Authorization::ConvertSidToStringSidW, GetTokenInformation, LookupAccountSidW,
            TokenUser, SID_NAME_USE, TOKEN_QUERY, TOKEN_USER,
        },
        System::Threading::{
            GetCurrentProcess, GetProcessTimes, OpenProcess, OpenProcessToken,
            GetExitCodeProcess, QueryFullProcessImageNameW, TerminateProcess, PROCESS_NAME_WIN32,
            PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_TERMINATE,
        },
    };

    use super::ObservedProcess;

    /// Держатели порта из обеих таблиц — IPv4 и IPv6.
    pub fn listening_port_owners_impl(port: u16) -> Vec<u32> {
        let mut owners = Vec::new();
        if let Some(buf) = tcp_table_raw(AF_INET as u32) {
            collect_v4(&buf, port, &mut owners);
        }
        if let Some(buf) = tcp_table_raw(AF_INET6 as u32) {
            collect_v6(&buf, port, &mut owners);
        }
        owners
    }

    /// Двухфазный вызов `GetExtendedTcpTable`: первый вызов с нулевым размером
    /// возвращает `ERROR_INSUFFICIENT_BUFFER` и записывает нужный размер, второй —
    /// заполняет выделенный буфер. Повтор нужен потому, что таблица могла вырасти
    /// между двумя вызовами; число попыток ограничено, чтобы не крутиться вечно на
    /// машине с бурным сетевым обменом.
    fn tcp_table_raw(af: u32) -> Option<Vec<u8>> {
        let mut size: u32 = 0;
        let ret = unsafe {
            GetExtendedTcpTable(
                std::ptr::null_mut(),
                &mut size,
                0, // сортировка не нужна
                af,
                TCP_TABLE_OWNER_PID_LISTENER,
                0,
            )
        };
        if ret != ERROR_INSUFFICIENT_BUFFER || size == 0 {
            debug!("GetExtendedTcpTable(af={af}): запрос размера вернул код {ret}, размер {size}");
            return None;
        }

        for _ in 0..5 {
            let mut buf = vec![0u8; size as usize];
            let ret = unsafe {
                GetExtendedTcpTable(
                    buf.as_mut_ptr() as *mut core::ffi::c_void,
                    &mut size,
                    0,
                    af,
                    TCP_TABLE_OWNER_PID_LISTENER,
                    0,
                )
            };
            if ret == 0 {
                buf.truncate(size as usize);
                return Some(buf);
            }
            if ret != ERROR_INSUFFICIENT_BUFFER {
                debug!("GetExtendedTcpTable(af={af}): заполнение вернуло код {ret}");
                return None;
            }
            // Таблица выросла, `size` уже обновлён — пробуем снова.
        }
        debug!("GetExtendedTcpTable(af={af}): таблица растёт быстрее, чем читается");
        None
    }

    /// Сколько байт занимает заголовок таблицы до первой записи. В C `table` —
    /// гибкий массив, объявленный как массив из одного элемента, поэтому размер
    /// заголовка = размер структуры минус размер одной записи (выравнивание учтено
    /// самим компилятором).
    fn header_len<T, R>() -> usize {
        std::mem::size_of::<T>().saturating_sub(std::mem::size_of::<R>())
    }

    /// Сколько записей реально помещается в полученный буфер. Число из
    /// `dwNumEntries` берётся как заявленное, но читаем мы не больше, чем прислано:
    /// чтение за границей буфера в `unsafe` — это порча памяти, а не ошибка разбора.
    fn safe_entry_count<T, R>(buf: &[u8], declared: usize) -> usize {
        let header = header_len::<T, R>();
        let row = std::mem::size_of::<R>();
        if row == 0 || buf.len() < header {
            return 0;
        }
        declared.min((buf.len() - header) / row)
    }

    fn collect_v4(buf: &[u8], port: u16, out: &mut Vec<u32>) {
        type Table = MIB_TCPTABLE_OWNER_PID;
        type Row = windows_sys::Win32::NetworkManagement::IpHelper::MIB_TCPROW_OWNER_PID;
        if buf.len() < std::mem::size_of::<u32>() {
            return;
        }
        unsafe {
            let table = buf.as_ptr() as *const Table;
            let n = safe_entry_count::<Table, Row>(buf, (*table).dwNumEntries as usize);
            let rows = (*table).table.as_ptr();
            for i in 0..n {
                let row = &*rows.add(i);
                if local_port(row.dwLocalPort) == port {
                    out.push(row.dwOwningPid);
                }
            }
        }
    }

    fn collect_v6(buf: &[u8], port: u16, out: &mut Vec<u32>) {
        type Table = MIB_TCP6TABLE_OWNER_PID;
        type Row = windows_sys::Win32::NetworkManagement::IpHelper::MIB_TCP6ROW_OWNER_PID;
        if buf.len() < std::mem::size_of::<u32>() {
            return;
        }
        unsafe {
            let table = buf.as_ptr() as *const Table;
            let n = safe_entry_count::<Table, Row>(buf, (*table).dwNumEntries as usize);
            let rows = (*table).table.as_ptr();
            for i in 0..n {
                let row = &*rows.add(i);
                if local_port(row.dwLocalPort) == port {
                    out.push(row.dwOwningPid);
                }
            }
        }
    }

    /// `dwLocalPort` хранит номер порта в сетевом порядке байт в младших 16 битах.
    fn local_port(raw: u32) -> u16 {
        u16::from_be((raw & 0xFFFF) as u16)
    }

    /// Дескриптор процесса во владении: закрывается ровно один раз, в `Drop`.
    ///
    /// Пока значение живо, номер процесса не может быть переиспользован
    /// операционной системой — на этом и держится вся проверка «наш ли процесс»
    /// в момент снятия.
    pub struct OwnedProcessHandle {
        handle: HANDLE,
        can_terminate: bool,
    }

    impl OwnedProcessHandle {
        pub fn can_terminate(&self) -> bool {
            self.can_terminate
        }

        /// Свойства процесса по уже открытому дескриптору — без второго открытия.
        pub fn observe(&self) -> ObservedProcess {
            unsafe {
                ObservedProcess {
                    owner: owner_from_process_handle(self.handle),
                    image_path: image_path_from_process_handle(self.handle),
                    created_at: creation_time_from_process_handle(self.handle),
                }
            }
        }

        pub fn terminate(&self) -> Result<(), String> {
            if !self.can_terminate {
                return Err("дескриптор открыт без права на снятие".to_string());
            }
            let ok = unsafe { TerminateProcess(self.handle, 1) };
            if ok == 0 {
                Err(format!(
                    "TerminateProcess отказал (код {})",
                    std::io::Error::last_os_error()
                ))
            } else {
                Ok(())
            }
        }

        /// Ждёт фактического завершения процесса. `TerminateProcess` только ЗАПРАШИВАЕТ
        /// снятие и возвращает управление сразу; прежний `taskkill` через `.output()`
        /// давал эту паузу неявно — порождением и ожиданием целой утилиты. Без
        /// ожидания следующий шаг (`allocate_port`) мог увидеть порт ещё занятым.
        /// `true` — процесс завершился в отведённое время.
        ///
        /// Опрос через `GetExitCodeProcess`, а не ожидание объекта: последнее требует
        /// права `SYNCHRONIZE`, ради которого пришлось бы расширять запрос прав при
        /// открытии дескриптора. `PROCESS_QUERY_LIMITED_INFORMATION` для опроса уже
        /// есть, а снимаем мы кодом 1 — путаницы с `STILL_ACTIVE` (259) не возникает.
        pub fn wait_exit(&self, timeout_ms: u32) -> bool {
            const STILL_ACTIVE: u32 = 259;
            const STEP_MS: u32 = 50;
            let mut waited = 0u32;
            loop {
                let mut code: u32 = 0;
                let ok = unsafe { GetExitCodeProcess(self.handle, &mut code) };
                if ok == 0 {
                    // Свойства процесса больше не читаются — считаем завершившимся.
                    return true;
                }
                if code != STILL_ACTIVE {
                    return true;
                }
                if waited >= timeout_ms {
                    return false;
                }
                std::thread::sleep(std::time::Duration::from_millis(STEP_MS as u64));
                waited += STEP_MS;
            }
        }
    }

    impl Drop for OwnedProcessHandle {
        fn drop(&mut self) {
            if !self.handle.is_null() {
                unsafe { CloseHandle(self.handle) };
            }
        }
    }

    /// Открывает дескриптор с правом на снятие. Если такого права нет (редкость для
    /// собственного процесса того же пользователя, но возможно при защите со стороны
    /// сторонних средств), откатывается на дескриптор только для чтения свойств —
    /// удержание номера процесса работает и в этом случае.
    pub fn open_process_for_kill(pid: u32) -> Option<OwnedProcessHandle> {
        unsafe {
            let full = OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE,
                0,
                pid,
            );
            if !full.is_null() {
                return Some(OwnedProcessHandle {
                    handle: full,
                    can_terminate: true,
                });
            }
            debug!("OpenProcess({pid}) с правом на снятие не удался, пробуем только чтение");
            let ro = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
            if ro.is_null() {
                debug!("OpenProcess({pid}) failed (process gone or permission denied)");
                return None;
            }
            Some(OwnedProcessHandle {
                handle: ro,
                can_terminate: false,
            })
        }
    }

    /// Возвращает SID текущего пользователя как S-1-5-... строку.
    pub fn current_user_sid_impl() -> Option<String> {
        unsafe {
            let proc_handle: HANDLE = GetCurrentProcess();
            let mut token: HANDLE = std::ptr::null_mut();
            if OpenProcessToken(proc_handle, TOKEN_QUERY, &mut token) == 0 {
                return None;
            }
            let result = sid_string_from_token(token);
            CloseHandle(token);
            result
        }
    }

    /// Возвращает имя текущего пользователя (без домена).
    pub fn current_user_name_impl() -> Option<String> {
        // Простой путь через %USERNAME% - задаётся ОС корректно
        std::env::var("USERNAME").ok().filter(|s| !s.is_empty())
    }

    /// Owner чужого процесса через OpenProcess + token + LookupAccountSidW.
    pub fn get_process_owner_impl(pid: u32) -> Option<String> {
        unsafe {
            let proc_handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
            if proc_handle.is_null() {
                debug!("OpenProcess({pid}) failed (process gone or permission denied)");
                return None;
            }
            let owner = owner_from_process_handle(proc_handle);
            CloseHandle(proc_handle);
            owner
        }
    }

    /// Владелец, полный путь к образу и время создания — за одно открытие
    /// дескриптора. `PROCESS_QUERY_LIMITED_INFORMATION` достаточно для всех трёх
    /// запросов и не требует повышения прав.
    ///
    /// 🔴 Прежде имя образа выяснялось порождением `tasklist` со скрытым окном, а
    /// следом шёл `taskkill` — тоже со скрытым окном. Связка «скрытая разведка
    /// процессов → принудительное снятие дерева» разбирается поведенческой защитой
    /// антивируса как вредоносная (10.08 Kaspersky снял оболочку продукта с диска,
    /// вердикт PDM:Trojan.Win32.Generic). Прямой системный вызов не порождает
    /// процессов вовсе и заодно даёт ПОЛНЫЙ путь вместо строки вывода утилиты.
    pub fn observe_process_impl(pid: u32) -> ObservedProcess {
        if pid == 0 {
            return ObservedProcess::default();
        }
        unsafe {
            let proc_handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
            if proc_handle.is_null() {
                debug!("OpenProcess({pid}) failed (process gone or permission denied)");
                return ObservedProcess::default();
            }

            let observed = ObservedProcess {
                owner: owner_from_process_handle(proc_handle),
                image_path: image_path_from_process_handle(proc_handle),
                created_at: creation_time_from_process_handle(proc_handle),
            };

            CloseHandle(proc_handle);
            observed
        }
    }

    /// Полный путь к образу процесса. `MAX_PATH` недостаточно — пути с длинными
    /// именами и включённым `LongPathsEnabled` доходят до 32 767 символов.
    unsafe fn image_path_from_process_handle(proc_handle: HANDLE) -> Option<String> {
        let mut buf = vec![0u16; 32768];
        let mut size = buf.len() as u32;
        if QueryFullProcessImageNameW(proc_handle, PROCESS_NAME_WIN32, buf.as_mut_ptr(), &mut size)
            == 0
            || size == 0
        {
            return None;
        }
        String::from_utf16(&buf[..size as usize]).ok()
    }

    /// Время создания процесса. `GetProcessTimes` отдаёт `FILETIME` в UTC —
    /// часовой пояс машины на результат не влияет.
    unsafe fn creation_time_from_process_handle(proc_handle: HANDLE) -> Option<DateTime<Utc>> {
        let mut creation = FILETIME {
            dwLowDateTime: 0,
            dwHighDateTime: 0,
        };
        let mut exit = creation;
        let mut kernel = creation;
        let mut user = creation;
        if GetProcessTimes(
            proc_handle,
            &mut creation,
            &mut exit,
            &mut kernel,
            &mut user,
        ) == 0
        {
            return None;
        }
        filetime_to_utc(creation)
    }

    /// `FILETIME` — число интервалов по 100 нс от 1601-01-01 UTC.
    fn filetime_to_utc(ft: FILETIME) -> Option<DateTime<Utc>> {
        /// Интервалов по 100 нс между 1601-01-01 и 1970-01-01.
        const UNIX_EPOCH_TICKS: u64 = 116_444_736_000_000_000;

        let ticks = ((ft.dwHighDateTime as u64) << 32) | ft.dwLowDateTime as u64;
        if ticks < UNIX_EPOCH_TICKS {
            // Ноль либо дата до 1970 — доверять такому значению нельзя.
            return None;
        }
        let since_epoch = ticks - UNIX_EPOCH_TICKS;
        let secs = (since_epoch / 10_000_000) as i64;
        let nanos = ((since_epoch % 10_000_000) * 100) as u32;
        DateTime::from_timestamp(secs, nanos)
    }

    // ── Internal token helpers ───────────────────────────────────────────

    /// Владелец процесса по уже открытому дескриптору. Дескриптор процесса
    /// закрывает вызывающая сторона, токен закрывается здесь.
    unsafe fn owner_from_process_handle(proc_handle: HANDLE) -> Option<String> {
        let mut token: HANDLE = std::ptr::null_mut();
        if OpenProcessToken(proc_handle, TOKEN_QUERY, &mut token) == 0 || token.is_null() {
            return None;
        }
        let owner = domain_user_from_token(token);
        CloseHandle(token);
        owner
    }

    /// Читает SID из token, возвращает как S-1-5-... строку.
    unsafe fn sid_string_from_token(token: HANDLE) -> Option<String> {
        let mut needed: u32 = 0;
        GetTokenInformation(token, TokenUser, std::ptr::null_mut(), 0, &mut needed);
        if needed == 0 {
            return None;
        }
        let mut buf = vec![0u8; needed as usize];
        if GetTokenInformation(
            token,
            TokenUser,
            buf.as_mut_ptr() as _,
            needed,
            &mut needed,
        ) == 0
        {
            return None;
        }
        let tu = &*(buf.as_ptr() as *const TOKEN_USER);
        let sid = tu.User.Sid;
        if sid.is_null() {
            return None;
        }

        let mut sid_str_ptr: *mut u16 = std::ptr::null_mut();
        if ConvertSidToStringSidW(sid, &mut sid_str_ptr) == 0 || sid_str_ptr.is_null() {
            return None;
        }

        // Read UTF-16 until null
        let mut len = 0usize;
        while *sid_str_ptr.add(len) != 0 {
            len += 1;
        }
        let slice = std::slice::from_raw_parts(sid_str_ptr, len);
        let result = String::from_utf16(slice).ok();

        LocalFree(sid_str_ptr as HLOCAL);
        result
    }

    /// Читает SID из token, резолвит в DOMAIN\user через LookupAccountSidW.
    unsafe fn domain_user_from_token(token: HANDLE) -> Option<String> {
        let mut needed: u32 = 0;
        GetTokenInformation(token, TokenUser, std::ptr::null_mut(), 0, &mut needed);
        if needed == 0 {
            return None;
        }
        let mut buf = vec![0u8; needed as usize];
        if GetTokenInformation(
            token,
            TokenUser,
            buf.as_mut_ptr() as _,
            needed,
            &mut needed,
        ) == 0
        {
            return None;
        }
        let tu = &*(buf.as_ptr() as *const TOKEN_USER);
        let sid = tu.User.Sid;
        if sid.is_null() {
            return None;
        }

        // First pass - get required buffer sizes
        let mut name_len: u32 = 0;
        let mut domain_len: u32 = 0;
        let mut sid_use: SID_NAME_USE = 0;
        LookupAccountSidW(
            std::ptr::null(),
            sid,
            std::ptr::null_mut(),
            &mut name_len,
            std::ptr::null_mut(),
            &mut domain_len,
            &mut sid_use,
        );
        if name_len == 0 || domain_len == 0 {
            return None;
        }

        let mut name_buf = vec![0u16; name_len as usize];
        let mut domain_buf = vec![0u16; domain_len as usize];
        if LookupAccountSidW(
            std::ptr::null(),
            sid,
            name_buf.as_mut_ptr(),
            &mut name_len,
            domain_buf.as_mut_ptr(),
            &mut domain_len,
            &mut sid_use,
        ) == 0
        {
            return None;
        }

        // Trim trailing nulls
        let name = String::from_utf16_lossy(&name_buf[..name_len as usize]);
        let domain = String::from_utf16_lossy(&domain_buf[..domain_len as usize]);

        if domain.is_empty() {
            Some(name)
        } else {
            Some(format!("{domain}\\{name}"))
        }
    }
}

// ── Tests ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    const TEST_CFG: SidecarConfig = SidecarConfig {
        product_id: "com.aurora.test",
        version: "0.0.1",
        legacy_port: 7430,
        identifier_dir: "com.aurora.test",
        process_exe_hint: "test-sidecar",
        extra_image_hints: &[],
    };

    #[test]
    fn user_scoped_port_stable() {
        let p1 = user_scoped_port(7430);
        let p2 = user_scoped_port(7430);
        assert_eq!(p1, p2, "same user must get same port");
        assert!(
            p1 >= 7430 && p1 < 7530,
            "port {p1} должен быть в диапазоне base..base+100"
        );
    }

    #[test]
    fn user_scoped_port_different_bases() {
        let p1 = user_scoped_port(7430);
        let p2 = user_scoped_port(7420);
        // Offset одинаковый для одного user
        assert_eq!(p1 - 7430, p2 - 7420);
    }

    #[test]
    fn state_file_roundtrip() {
        let state = SidecarState {
            port: 52431,
            pid: 19284,
            session_id: "abc123".to_string(),
            product: "com.aurora.test".to_string(),
            version: "1.0.9".to_string(),
            user: "tester".to_string(),
            started_at: "2026-04-20T14:32:01Z".to_string(),
            image_path: r"C:\Program Files\Aurora\test-sidecar.exe".to_string(),
        };

        let cfg = SidecarConfig {
            identifier_dir: "com.aurora.test-rt",
            ..TEST_CFG
        };

        // Очистка после предыдущих прогонов
        delete_state_file(&cfg);

        write_state_file(&cfg, &state).expect("write");
        let read = read_state_file(&cfg).expect("read");

        assert_eq!(read.port, state.port);
        assert_eq!(read.pid, state.pid);
        assert_eq!(read.session_id, state.session_id);
        assert_eq!(read.product, state.product);
        assert_eq!(read.image_path, state.image_path);

        delete_state_file(&cfg);
    }

    /// Обратная совместимость: файл состояния прежней версии полного пути образа не
    /// содержит. Он обязан читаться, а поле — оказаться пустым, чтобы сверка при
    /// снятии откатилась на сравнение по имени образа. Иначе после обновления
    /// собственный зомби от прежней версии перестал бы сниматься.
    #[test]
    fn state_file_without_image_path_reads_with_empty_field() {
        let cfg = SidecarConfig {
            identifier_dir: "com.aurora.test-legacy-state",
            ..TEST_CFG
        };
        let path = state_file_path(&cfg);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(
            &path,
            r#"{"port":7461,"pid":9134,"session_id":"abc","product":"com.aurora.test",
                "version":"2.4.8","user":"tester","started_at":"2026-04-20T14:32:01Z"}"#,
        )
        .unwrap();

        let read = read_state_file(&cfg).expect("файл прежней версии обязан читаться");
        assert_eq!(read.pid, 9134);
        assert!(read.image_path.is_empty());

        delete_state_file(&cfg);
    }

    #[test]
    fn read_state_file_missing_returns_none() {
        let cfg = SidecarConfig {
            identifier_dir: "com.aurora.test-missing-nonexistent-dir",
            ..TEST_CFG
        };
        delete_state_file(&cfg); // ensure missing
        assert!(read_state_file(&cfg).is_none());
    }

    #[test]
    fn read_state_file_corrupt_returns_none() {
        let cfg = SidecarConfig {
            identifier_dir: "com.aurora.test-corrupt",
            ..TEST_CFG
        };
        let path = state_file_path(&cfg);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, "not json at all {{").unwrap();

        assert!(read_state_file(&cfg).is_none());
        delete_state_file(&cfg);
    }

    #[test]
    fn session_id_unique() {
        let a = generate_session_id();
        let b = generate_session_id();
        assert_ne!(a, b);
        assert_eq!(a.len(), 32); // simple UUID hex
    }

    #[test]
    fn allocate_port_returns_free_port() {
        let cfg = SidecarConfig {
            legacy_port: 17430, // unusual base чтобы не конфликтовать с реальным sidecar'ом
            ..TEST_CFG
        };
        let port = allocate_port(&cfg).expect("allocate");
        assert!(port >= 1024); // sanity - не privileged range
    }

    #[test]
    fn kill_switch_disabled_by_default() {
        // Тест может ложно упасть если test harness запущен с AURORA_SIDECAR_LEGACY_PORT=1
        if std::env::var("AURORA_SIDECAR_LEGACY_PORT").is_err() {
            assert!(!is_kill_switch_enabled());
        }
    }

    #[test]
    fn current_user_not_empty() {
        let u = current_user_name();
        assert!(!u.is_empty());
        assert_ne!(u, "unknown", "CI must provide USERNAME/USER");
    }

    #[cfg(windows)]
    #[test]
    fn current_user_sid_format() {
        let sid = current_user_sid().expect("SID on Windows");
        assert!(sid.starts_with("S-1-"), "SID format S-1-... got '{sid}'");
    }

    // ── CPD-79: решение о снятии процесса ────────────────────────────────
    //
    // Решение вынесено в чистую функцию именно ради этих тестов: ни Windows,
    // ни живых процессов они не требуют. До правки таких тестов не было вовсе -
    // решение было сварено с системными вызовами, и вызывать было нечего.

    /// Конфиг «как в релизе»: движок — собранный exe, сторонние интерпретаторы
    /// в список допустимых имён образа не входят.
    const KILL_CFG: SidecarConfig = SidecarConfig {
        process_exe_hint: "econometrica-sidecar",
        ..TEST_CFG
    };

    /// Конфиг «как в отладочной сборке»: движок запускается интерпретатором.
    const KILL_CFG_DEV: SidecarConfig = SidecarConfig {
        extra_image_hints: &["python", "pythonw"],
        ..KILL_CFG
    };

    const OUR_USER: &str = "anton";
    const OUR_IMAGE: &str = r"C:\Program Files\Aurora Econometrica\sidecar\econometrica\econometrica-sidecar.exe";

    /// Путь установки ДРУГОЙ редакции продукта: тот же файл образа, тот же
    /// `product_id`, тот же пользователь — различает только каталог.
    const OTHER_EDITION_IMAGE: &str =
        r"C:\Program Files\Optimizer MMM Local\sidecar\econometrica\econometrica-sidecar.exe";

    /// Номер процесса-держателя порта во всех таблицах ниже.
    const HOLDER: u32 = 9134;
    /// Номер процесса самой оболочки — она себя трогать не вправе.
    const SHELL: u32 = 4242;

    fn observed(image: &str) -> ObservedProcess {
        ObservedProcess {
            owner: Some(format!("AURORA-PC\\{OUR_USER}")),
            image_path: Some(image.to_string()),
            created_at: None,
        }
    }

    /// Штатный набор фактов: порт держит один процесс, он не мы, дескриптор удержан,
    /// держатель между опросами не сменился, ожидаемый путь — путь этой установки.
    /// Каждый тест портит РОВНО ОДНО поле — так видно, какая именно проверка сработала.
    fn facts<'a>(
        holders: &'a [u32],
        observed: Option<&'a ObservedProcess>,
        holders_after: &'a [u32],
        expected_image_path: Option<&'a str>,
    ) -> PortHolderFacts<'a> {
        PortHolderFacts {
            holders,
            self_pid: SHELL,
            observed,
            holders_after,
            expected_image_path,
        }
    }

    // ── Первый рубеж: стоит ли вообще открывать дескриптор ───────────────

    /// Порт никто не слушает — снимать нечего. Отдельная причина, а не «не наш»:
    /// в журнале это разные события, и путать их при разборе у клиента нельзя.
    #[test]
    fn skip_when_nobody_listens_on_the_port() {
        let after: [u32; 0] = [];
        assert_eq!(
            should_kill_port_holder(&facts(&[], None, &after, Some(OUR_IMAGE)), &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::NoListener)
        );
    }

    /// Нулевой номер система отдаёт там, где владельца назвать не может. Держателем
    /// он не считается — иначе первая же такая запись увела бы решение в наблюдение
    /// несуществующего процесса.
    #[test]
    fn zero_pid_is_not_a_holder() {
        let after: [u32; 0] = [];
        assert_eq!(
            should_kill_port_holder(&facts(&[0], None, &after, Some(OUR_IMAGE)), &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::NoListener)
        );
    }

    /// Держатель порта — сама оболочка продукта. Снятие унесло бы приложение
    /// пользователя целиком, поэтому проверка стоит ДО открытия дескриптора.
    #[test]
    fn skip_when_holder_is_our_own_shell() {
        let after = [SHELL];
        assert_eq!(
            should_kill_port_holder(
                &facts(&[SHELL], None, &after, Some(OUR_IMAGE)),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Skip(SkipReason::SelfPid)
        );
    }

    /// Один и тот же процесс может держать порт двумя записями сразу (например в
    /// обеих таблицах адресов). Это по-прежнему ОДИН держатель — снятие обязано
    /// работать, иначе собственный зомби на двойном стеке перестал бы сниматься.
    #[test]
    fn duplicate_rows_of_one_process_are_one_holder() {
        assert_eq!(holder_worth_observing(&[HOLDER, HOLDER], SHELL), Ok(HOLDER));
        assert_eq!(holder_worth_observing(&[HOLDER, 0, HOLDER], SHELL), Ok(HOLDER));
    }

    /// Номер порта заняли РАЗНЫЕ процессы (двойной стек, разные локальные адреса на
    /// одном номере). Кто из них наш — неизвестно, и гадать нельзя: цена ошибки —
    /// снятый чужой расчёт, цена отказа — незанятый порт.
    #[test]
    fn skip_when_several_different_processes_hold_the_port() {
        let holders = [HOLDER, 7777];
        assert_eq!(
            should_kill_port_holder(
                &facts(&holders, Some(&observed(OUR_IMAGE)), &holders, Some(OUR_IMAGE)),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Skip(SkipReason::HolderAmbiguous)
        );
    }

    // ── Наблюдение и сверка держателя ────────────────────────────────────

    /// Штатное снятие зомби: порт держит наш движок этой установки, между опросами
    /// ничего не изменилось. Главный положительный случай — если он сломается,
    /// зомби перестанут сниматься вовсе.
    #[test]
    fn kill_when_holder_is_our_engine() {
        let holders = [HOLDER];
        assert_eq!(
            should_kill_port_holder(
                &facts(&holders, Some(&observed(OUR_IMAGE)), &holders, Some(OUR_IMAGE)),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Kill
        );
    }

    /// Дескриптор держателя не открылся: процесс успел завершиться либо нет прав.
    /// Решение консервативное — не снять своего зомби дешевле, чем убить чужое.
    #[test]
    fn skip_when_handle_did_not_open() {
        let holders = [HOLDER];
        assert_eq!(
            should_kill_port_holder(
                &facts(&holders, None, &holders, Some(OUR_IMAGE)),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Skip(SkipReason::ObserveFailed)
        );
    }

    /// Процесс принадлежит другому пользователю ОС — неприкосновенен (инвариант RDP,
    /// ради которого этот код и писался). Порт при этом он держит наш.
    #[test]
    fn skip_when_process_owner_is_another_user() {
        let holders = [HOLDER];
        let obs = ObservedProcess {
            owner: Some("AURORA-PC\\maria".to_string()),
            ..observed(OUR_IMAGE)
        };
        assert_eq!(
            should_kill_port_holder(
                &facts(&holders, Some(&obs), &holders, Some(OUR_IMAGE)),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Skip(SkipReason::OwnerMismatch)
        );
    }

    /// Владельца определить не удалось (процесс исчез между вызовами либо нет прав).
    #[test]
    fn skip_when_owner_unavailable() {
        let holders = [HOLDER];
        let obs = ObservedProcess {
            owner: None,
            ..observed(OUR_IMAGE)
        };
        assert_eq!(
            should_kill_port_holder(
                &facts(&holders, Some(&obs), &holders, Some(OUR_IMAGE)),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Skip(SkipReason::OwnerUnknown)
        );
    }

    /// Путь к образу недоступен — сверять не с чем, значит не снимаем.
    #[test]
    fn skip_when_image_path_unavailable() {
        let holders = [HOLDER];
        let obs = ObservedProcess {
            image_path: None,
            ..observed(OUR_IMAGE)
        };
        assert_eq!(
            should_kill_port_holder(
                &facts(&holders, Some(&obs), &holders, Some(OUR_IMAGE)),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Skip(SkipReason::ImageUnknown)
        );
    }

    // ── 🔴 Прямой контроль дефекта CPD-79 ────────────────────────────────

    /// 🔴 ГЛАВНЫЙ КОНТРОЛЬ. Порт занял ПОСТОРОННИЙ процесс того же пользователя —
    /// Jupyter, Anaconda, движок соседнего продукта Aurora. Держателем он является
    /// по-настоящему, владелец совпадает, между опросами ничего не менялось:
    /// отсекает его только полный путь образа.
    ///
    /// Ровно этот случай уехал к клиентам: файл состояния переживал падение
    /// приложения, Windows после перезагрузки раздавала номера процессов заново, и
    /// записанный номер доставался постороннему — расчёт снимался молча.
    #[test]
    fn skip_foreign_process_holding_our_port() {
        let holders = [HOLDER];
        let foreign = observed(r"C:\Users\anton\anaconda3\python.exe");
        assert_eq!(
            should_kill_port_holder(
                &facts(&holders, Some(&foreign), &holders, Some(OUR_IMAGE)),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Skip(SkipReason::ImagePathNotOurs)
        );
    }

    /// High-1. Обе редакции продукта: один и тот же `product_id` (рукопожатие с
    /// Python-модулем), один и тот же файл образа, один пользователь. Различает их
    /// только каталог установки — и теперь сверка идёт с каталогом ЭТОЙ установки,
    /// а не с тем, что мы когда-то записали.
    #[test]
    fn skip_engine_of_other_product_edition() {
        let holders = [HOLDER];
        let other = observed(OTHER_EDITION_IMAGE);

        // Имя файла образа у редакций совпадает — сверки по имени тут не хватило бы.
        assert!(image_matches(Some(OTHER_EDITION_IMAGE), &KILL_CFG));

        assert_eq!(
            should_kill_port_holder(
                &facts(&holders, Some(&other), &holders, Some(OUR_IMAGE)),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Skip(SkipReason::ImagePathNotOurs)
        );
    }

    // ── 🔴 Риск 1 проекта: расхождение написания пути ────────────────────

    /// 🔴 Самое вероятное место тихого регресса «зомби перестал сниматься». Прежде обе
    /// строки происходили из ОДНОГО источника: путь снимался у живого процесса и им же
    /// записывался в файл состояния. Теперь источника два — путь установки и путь
    /// запущенного процесса, — и разойтись они могут в написании, оставаясь одним и тем
    /// же файлом: префикс `\\?\` (его всегда добавляет `std::fs::canonicalize` и никогда
    /// не добавляет `QueryFullProcessImageNameW`), регистр (пути Windows
    /// регистронезависимы), разделители.
    ///
    /// Направление отказа здесь БЕЗОПАСНОЕ (зомби просто не снимется), потому и тихое —
    /// поймать его может только этот тест.
    #[test]
    fn kill_our_engine_despite_path_spelling_difference() {
        let holders = [HOLDER];

        let spellings = [
            format!(r"\\?\{OUR_IMAGE}"),
            OUR_IMAGE.to_uppercase(),
            OUR_IMAGE.replace('\\', "/"),
            format!(r"\\?\{}", OUR_IMAGE.to_uppercase()),
            format!("  {OUR_IMAGE}  "),
        ];

        for spelling in &spellings {
            let obs = observed(spelling);
            assert_eq!(
                should_kill_port_holder(
                    &facts(&holders, Some(&obs), &holders, Some(OUR_IMAGE)),
                    &KILL_CFG,
                    OUR_USER
                ),
                KillVerdict::Kill,
                "написание «{spelling}» обязано считаться тем же файлом, что и «{OUR_IMAGE}»"
            );

            // И в обратную сторону: разойтись может ожидаемый путь, а не наблюдаемый.
            let obs_plain = observed(OUR_IMAGE);
            assert_eq!(
                should_kill_port_holder(
                    &facts(&holders, Some(&obs_plain), &holders, Some(spelling)),
                    &KILL_CFG,
                    OUR_USER
                ),
                KillVerdict::Kill,
                "ожидаемый путь в написании «{spelling}» обязан совпасть с «{OUR_IMAGE}»"
            );
        }
    }

    /// Сверка полного пути: регистр не важен, префикс `\\?\` и разделители не считаются
    /// расхождением, а чужой каталог — считается.
    #[test]
    fn image_path_matches_normalizes_case_separators_and_verbatim_prefix() {
        assert!(image_path_matches(OUR_IMAGE, &OUR_IMAGE.to_uppercase()));
        assert!(image_path_matches(OUR_IMAGE, &format!(r"\\?\{OUR_IMAGE}")));
        assert!(image_path_matches(OUR_IMAGE, &OUR_IMAGE.replace('\\', "/")));
        assert!(image_path_matches(
            r"\\?\UNC\server\share\econometrica-sidecar.exe",
            r"\\server\share\econometrica-sidecar.exe"
        ));
        assert!(!image_path_matches(OUR_IMAGE, OTHER_EDITION_IMAGE));
        assert!(!image_path_matches("", OUR_IMAGE));
    }

    /// Короткие имена 8.3 и символические ссылки строковой нормализацией не снимаются —
    /// их разрешает системный слой. Проверяем на самом надёжном пути, который есть на
    /// любой машине: каталог временных файлов сборки.
    #[test]
    fn canonical_path_for_compare_resolves_existing_path_and_survives_missing_one() {
        let existing = std::env::current_exe().expect("путь до тестового бинарника");
        let canonical = canonical_path_for_compare(&existing.to_string_lossy());
        assert!(
            image_path_matches(&canonical, &existing.to_string_lossy()),
            "канонизация не должна ломать совпадение с исходным путём"
        );

        let missing = r"C:\каталог\которого\нет\engine.exe";
        assert_eq!(
            canonical_path_for_compare(missing),
            missing,
            "несуществующий путь обязан вернуться как есть, а не пропасть"
        );
    }

    // ── 🔴 Гонка: держатель сменился между опросами ──────────────────────

    /// 🔴 Зазор между первым опросом таблицы и открытием дескриптора. Держатель успел
    /// завершиться, а номер порта достался другому процессу — удержание дескриптора
    /// эту гонку НЕ закрывает (оно защищает только от переиспользования ПОСЛЕ
    /// открытия). Закрывает переспрос: держатель обязан оказаться тем же самым.
    #[test]
    fn skip_when_holder_changed_between_probes() {
        let before = [HOLDER];
        let after = [7777];
        assert_eq!(
            should_kill_port_holder(
                &facts(&before, Some(&observed(OUR_IMAGE)), &after, Some(OUR_IMAGE)),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Skip(SkipReason::HolderChanged)
        );
    }

    /// Тот же зазор, но держатель просто исчез: порт освободился, снимать нечего.
    #[test]
    fn skip_when_holder_disappeared_between_probes() {
        let before = [HOLDER];
        let after: [u32; 0] = [];
        assert_eq!(
            should_kill_port_holder(
                &facts(&before, Some(&observed(OUR_IMAGE)), &after, Some(OUR_IMAGE)),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Skip(SkipReason::HolderChanged)
        );
    }

    /// Переспрос обязан стоять ПОСЛЕ сверки образа, а не вместо неё: чужой процесс,
    /// стабильно державший порт оба раза, всё равно не снимается.
    #[test]
    fn stable_foreign_holder_is_still_not_killed() {
        let holders = [HOLDER];
        let foreign = observed(r"C:\Program Files\Jupyter\python.exe");
        assert_eq!(
            should_kill_port_holder(
                &facts(&holders, Some(&foreign), &holders, Some(OUR_IMAGE)),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Skip(SkipReason::ImagePathNotOurs)
        );
    }

    // ── Запасная сверка по имени образа (отладочная сборка) ──────────────

    /// В отладочной сборке движок запускается интерпретатором (`python -B server.py`),
    /// ожидаемого пути установки нет, и сверка откатывается на имя образа —
    /// `SIDECAR_IMAGE_HINTS` там как раз содержит `python`/`pythonw`.
    #[test]
    fn kill_dev_python_engine_by_image_name_when_expected_path_unknown() {
        let holders = [HOLDER];
        let obs = observed(r"C:\Python312\python.exe");
        assert_eq!(
            should_kill_port_holder(&facts(&holders, Some(&obs), &holders, None), &KILL_CFG_DEV, OUR_USER),
            KillVerdict::Kill
        );
    }

    /// Тот же откат, но конфиг релизной сборки: сторонние интерпретаторы в список
    /// допустимых имён не входят, поэтому чужой python не пройдёт и здесь.
    #[test]
    fn skip_foreign_python_by_image_in_release_config() {
        let holders = [HOLDER];
        let obs = observed(r"C:\Users\anton\anaconda3\python.exe");
        assert_eq!(
            should_kill_port_holder(&facts(&holders, Some(&obs), &holders, None), &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::ImageMismatch)
        );
    }

    /// Пустая строка в ожидаемом пути — это «путь неизвестен», а не «совпасть не с чем».
    /// Иначе сорвавшееся разрешение пути установки молча снимало бы сверку целиком.
    #[test]
    fn empty_expected_path_falls_back_to_image_name_check() {
        let holders = [HOLDER];
        let obs = observed(r"C:\Users\anton\anaconda3\python.exe");
        assert_eq!(
            should_kill_port_holder(
                &facts(&holders, Some(&obs), &holders, Some("   ")),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Skip(SkipReason::ImageMismatch)
        );
    }

    // ── Каждая причина отказа достижима ──────────────────────────────────

    /// Проект требует, чтобы каждая причина отказа попадала в журнал ОТДЕЛЬНОЙ
    /// формулировкой: направление отказа безопасное, но молчаливым быть не должно.
    /// Тест держит два условия сразу — все причины достижимы через решение и у каждой
    /// своё пояснение.
    #[test]
    fn every_skip_reason_is_reachable_and_distinctly_worded() {
        let all = [
            SkipReason::NoListener,
            SkipReason::HolderAmbiguous,
            SkipReason::SelfPid,
            SkipReason::ObserveFailed,
            SkipReason::OwnerUnknown,
            SkipReason::OwnerMismatch,
            SkipReason::ImageUnknown,
            SkipReason::ImageMismatch,
            SkipReason::ImagePathNotOurs,
            SkipReason::HolderChanged,
        ];
        let mut texts: Vec<&str> = all.iter().map(|r| r.as_str()).collect();
        let before = texts.len();
        texts.sort_unstable();
        texts.dedup();
        assert_eq!(before, texts.len(), "две причины отказа с одинаковым пояснением");
        assert!(all.iter().all(|r| !r.as_str().is_empty()));
        assert_eq!(
            format!("{}", SkipReason::ImagePathNotOurs),
            SkipReason::ImagePathNotOurs.as_str(),
            "Display обязан совпадать с пояснением для журнала"
        );
    }

    // ── Системный слой на живом процессе ─────────────────────────────────

    /// Системный слой вживую: открываем настоящий слушающий сокет и спрашиваем систему,
    /// кто держит этот порт. Ответ обязан назвать нас — иначе весь новый механизм молча
    /// не находит держателя, и зомби перестают сниматься.
    #[cfg(windows)]
    #[test]
    fn listening_port_owners_finds_real_listener() {
        let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).expect("тестовый сокет");
        let port = listener.local_addr().expect("адрес сокета").port();

        let owners = listening_port_owners(port);
        assert!(
            owners.contains(&std::process::id()),
            "система обязана назвать наш процесс держателем порта {port}, вернула {owners:?}"
        );
        assert_eq!(
            holder_worth_observing(&owners, 0),
            Ok(std::process::id()),
            "держатель обязан быть распознан как единственный"
        );

        drop(listener);
    }

    /// 🔴 Риск 3 проекта: двойной стек. Слушатель на `::1` попадает ТОЛЬКО в таблицу
    /// IPv6 — односемейный опрос его не найдёт, и зомби перестанет сниматься молча,
    /// без единого сообщения в журнале. Проверено мутацией: если убрать опрос второй
    /// таблицы, красится ровно этот тест и больше ни один.
    ///
    /// Если IPv6 на машине отключён, привязка не удастся — тогда проверять нечего, и
    /// тест честно ничего не утверждает (на такой машине двойного стека нет).
    #[cfg(windows)]
    #[test]
    fn listening_port_owners_finds_ipv6_listener() {
        let Ok(listener) = std::net::TcpListener::bind(("::1", 0)) else {
            eprintln!("IPv6 на этой машине недоступен - проверять двойной стек нечем");
            return;
        };
        let port = listener.local_addr().expect("адрес сокета").port();

        let owners = listening_port_owners(port);
        assert!(
            owners.contains(&std::process::id()),
            "слушатель IPv6 обязан находиться: опрашивать надо ОБЕ таблицы, а не только IPv4 \
             (порт {port}, ответ {owners:?})"
        );

        drop(listener);
    }

    /// Обратная сторона: порт, который никто не слушает, держателей не имеет.
    /// Без этой проверки предыдущий тест прошёл бы и на функции, возвращающей
    /// «все процессы машины».
    #[cfg(windows)]
    #[test]
    fn listening_port_owners_empty_for_free_port() {
        let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).expect("тестовый сокет");
        let port = listener.local_addr().expect("адрес сокета").port();
        drop(listener); // порт освобождён

        assert!(
            listening_port_owners(port).is_empty(),
            "у свободного порта {port} держателей быть не должно"
        );
    }

    /// Сверка образа идёт по имени файла из полного пути, а не по подстроке в
    /// строке вывода утилиты: чужой каталог с похожим названием не проходит.
    #[test]
    fn image_matches_uses_file_name_not_substring() {
        assert!(image_matches(Some(OUR_IMAGE), &KILL_CFG));
        assert!(image_matches(
            Some(r"D:\build\econometrica-sidecar.exe"),
            &KILL_CFG
        ));
        assert!(!image_matches(
            Some(r"C:\econometrica-sidecar\notepad.exe"),
            &KILL_CFG
        ));
        assert!(!image_matches(Some(r"C:\Windows\py.exe"), &KILL_CFG_DEV));
        assert!(image_matches(Some(r"C:\Python312\python3.exe"), &KILL_CFG_DEV));
        assert!(!image_matches(None, &KILL_CFG));
    }

    /// Medium-8 внешнего аудита 2.4.9. Совпадение по НАЧАЛУ имени образа принимается
    /// только для сторонних интерпретаторов (`python` ↔ `python3` — версия отличается
    /// суффиксом). Для собственного образа продукта сверка строгая: иначе под неё
    /// подпадает любая переименованная копия рядом с движком.
    ///
    /// Проверка достижима: на основном пути образ сверяется целиком по полному пути,
    /// но при неизвестном ожидаемом пути (отладочная сборка, несобранная поставка)
    /// решение откатывается сюда — и дыра была бы живой.
    #[test]
    fn image_matches_does_not_accept_renamed_copies_of_our_engine() {
        assert!(!image_matches(
            Some(r"C:\Program Files\Aurora\econometrica-sidecar-backup.exe"),
            &KILL_CFG
        ));
        assert!(!image_matches(
            Some(r"C:\Program Files\Aurora\econometrica-sidecar-old.exe"),
            &KILL_CFG
        ));
        assert!(
            image_matches(
                Some(r"C:\Program Files\Aurora\econometrica-sidecar.exe"),
                &KILL_CFG
            ),
            "строгая сверка не должна ломать собственный образ"
        );
        assert!(
            image_matches(Some(r"C:\Python312\python3.exe"), &KILL_CFG_DEV),
            "совпадение по началу имени обязано остаться для интерпретаторов"
        );
    }

    /// Владелец приходит как `DOMAIN\user`, в состоянии и в `current_user_name()`
    /// домена нет - сверяем хвост, но не путаем разных пользователей.
    /// High-3 на живом процессе: дескриптор открывается с правом на снятие, свойства
    /// снимаются по нему же (без второго открытия), снятие проходит по дескриптору —
    /// без порождения внешней утилиты, — и процесс действительно завершается.
    #[cfg(windows)]
    #[test]
    fn held_process_observes_and_terminates_real_process() {
        use std::process::{Command, Stdio};

        let mut child = Command::new("ping")
            .args(["127.0.0.1", "-n", "30"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("порождение долгоживущего процесса для проверки");
        let pid = child.id();

        let held = hold_and_observe(pid).expect("дескриптор живого процесса обязан открыться");
        assert_eq!(held.pid(), pid);
        let image = held
            .observed()
            .image_path
            .as_deref()
            .expect("полный путь образа")
            .to_lowercase();
        assert!(image.contains("ping"), "неожиданный образ: {image}");
        assert!(held.observed().created_at.is_some(), "время создания");
        assert!(held.observed().owner.is_some(), "владелец");
        assert!(held.can_terminate(), "право на снятие своего же процесса");

        held.terminate().expect("снятие по дескриптору");
        assert!(held.wait_exit(5000), "процесс обязан завершиться после снятия");
        let _ = child.wait();
    }

    #[test]
    fn owner_matches_handles_domain_prefix() {
        assert!(owner_matches("AURORA-PC\\anton", "anton"));
        assert!(owner_matches("anton", "ANTON"));
        assert!(!owner_matches("AURORA-PC\\anton2", "anton"));
        assert!(!owner_matches("AURORA-PC\\anton", "unknown"));
        assert!(!owner_matches("AURORA-PC\\anton", ""));
    }
}
