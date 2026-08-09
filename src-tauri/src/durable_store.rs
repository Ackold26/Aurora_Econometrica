//! Durable-состояние приложения: per-app каталог + one-shot миграция из общего legacy-каталога.
//!
//! CPD-30 (2026-07-29): все Aurora-продукты машины писали историю/метрики/сессии в ОБЩИЙ
//! `%LOCALAPPDATA%\AIAgency\<sub>` без идентификатора продукта. Имя файла истории — идентификатор
//! кабинета, поэтому продукты с одноимённым кабинетом читали и перезаписывали чужую историю
//! (доказано вживую на этой машине: `econometrist.json` в общем `AIAgency\history\` — тот же файл,
//! что читал бы кабинет econometrist в любом другом Aurora-продукте с этим кабинетом). Решение —
//! per-app каталог (`app_local_data_dir()`, чистится деинсталлятором) с одноразовым переносом
//! legacy-файлов при первом запуске.
//!
//! Эталон-донор этого файла — `ROSST_AI_DocMaster/src-tauri/src/durable_store.rs` (сам он —
//! усиленная версия первопроходца `ROSST_AI_Media`, см. докстринг там же про `fresh = !dir.exists()`
//! до `create_dir_all` и глотание ошибок `fs::copy(...).is_ok()` — в Econometrica этих слабостей
//! не было НИКОГДА, копируем сразу усиленный контракт).
//!
//! Признак завершённого переноса — ОТДЕЛЬНЫЙ файл-маркер (`.legacy-migrated`) ВНУТРИ нового
//! каталога, записывается ТОЛЬКО когда ВСЕ файлы перенесены без единой ошибки:
//! - маркера нет → перенос выполняется (в т.ч. повторно после оборванного);
//! - файл уже существует в новом каталоге → НЕ перезаписывается (свежая история продукта
//!   важнее legacy-копии);
//! - хотя бы один файл не скопировался → маркер НЕ пишется, `warn!` с именем файла и причиной,
//!   следующий запуск пробует снова;
//! - legacy-каталог не удаляется никогда — им пользуются другие установленные Aurora-продукты,
//!   а при откате версии история должна остаться на месте.

use anyhow::{Context, Result};
use log::{info, warn};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};

/// Имя файла-маркера завершённого переноса (внутри НОВОГО каталога, не трогает legacy).
const MIGRATION_MARKER: &str = ".legacy-migrated";

fn local_app_data() -> PathBuf {
    PathBuf::from(
        std::env::var("LOCALAPPDATA").unwrap_or_else(|_| "C:\\Users\\Default\\AppData\\Local".to_string()),
    )
}

/// База durable-состояния = папка приложения (`app_local_data_dir()` = `%LOCALAPPDATA%\<identifier>`).
/// Инициализируется один раз при старте (см. `lib.rs::run()` и `.setup()`) — чтобы состояние
/// лежало там же, где остальные данные приложения, и чистилось деинсталлятором.
static BASE_DIR: OnceLock<PathBuf> = OnceLock::new();

/// Вызывается один раз в `run()`/`.setup()`: base = per-app каталог (`%LOCALAPPDATA%\<identifier>`).
pub fn init(base: PathBuf) {
    let _ = BASE_DIR.set(base);
}

fn base_dir() -> PathBuf {
    // Фолбэк (тесты/вызов до init): per-app по имени пакета — тоже уникально на вариант сборки
    // (Cargo.toml::name отличается у каждого Aurora-продукта форка).
    BASE_DIR
        .get()
        .cloned()
        .unwrap_or_else(|| local_app_data().join(env!("CARGO_PKG_NAME")))
}

/// Имя подкаталога сессий — единственный источник правды для `session/manager.rs` и
/// `session/cleanup.rs` (testleak-фикс, 2026-07-29): раньше оба места писали независимый
/// строковый литерал `"sessions"`, которые могли незаметно разойтись; теперь оба ссылаются на
/// эту константу — расхождение стало ошибкой компиляции, а не тихим дефектом. Гейт
/// `session::tests::manager_and_cleanup_reference_the_same_sessions_constant`
/// (`session/mod.rs`) сканирует исходники и красит, если кто-то вернётся к литералу.
pub const SESSIONS_SUB: &str = "sessions";

/// Путь, который вернёт `app_state_dir(sub)`, — БЕЗ создания каталогов и БЕЗ миграции. Чистая
/// функция (никакого I/O): читает `BASE_DIR`, если он уже инициализирован, иначе считает тот
/// же фолбэк, что и `base_dir()`. Существует, чтобы тесты могли резолвить путь, не трогая
/// диск и не завися от того, вызывал ли кто-то `init()` в этом процессе.
pub fn resolve_path(sub: &str) -> PathBuf {
    if sub.is_empty() { base_dir() } else { base_dir().join(sub) }
}

/// 🔴 Внешний аудит 2026-07-30 (Medium, C9): каталоги, для которых перенос в ЭТОМ процессе уже
/// завершился успешно. Раньше `app_state_dir` дёргал `migrate_into` на КАЖДЫЙ вызов, пока не
/// встанет файл-маркер, а вызывается он на каждое сохранение сообщения и каждый инкремент
/// счётчика: лишние обращения к диску плюс гонка — между проверкой «файл существует» и
/// переименованием другой поток успевал записать свежее сообщение, которое затем затиралось
/// legacy-копией. Ключ — резолвнутый ПУТЬ, а не `sub`: `BASE_DIR` (`OnceLock`) может быть
/// инициализирован уже ПОСЛЕ первых вызовов (страховочный `init()` в `.setup()`, см. `lib.rs`),
/// и после смены базы каталог обязан быть создан и перенесён заново.
static MIGRATED_DIRS: OnceLock<Mutex<HashSet<PathBuf>>> = OnceLock::new();

fn migrated_dirs() -> &'static Mutex<HashSet<PathBuf>> {
    MIGRATED_DIRS.get_or_init(|| Mutex::new(HashSet::new()))
}

/// Per-app каталог durable-состояния с one-shot миграцией из общего legacy `AIAgency\<sub>`.
/// `sub` — подкаталог (`"history"`, `"metrics"`, `"sessions"`); пустая строка — сам каталог
/// приложения (для файлов, лежавших прямо в legacy-корне `AIAgency\`, например `audit.log`).
pub fn app_state_dir(sub: &str) -> Result<PathBuf> {
    let dir = resolve_path(sub);
    let legacy = if sub.is_empty() {
        local_app_data().join("AIAgency")
    } else {
        local_app_data().join("AIAgency").join(sub)
    };
    prepare_state_dir(&dir, &legacy, sub, |s: &Path, d: &Path| std::fs::copy(s, d))?;
    Ok(dir)
}

/// Подготовка каталога состояния к работе: одноразовый перенос + гарантия, что каталог
/// существует ПРЯМО СЕЙЧАС.
///
/// 🔴 Внешний аудит 2026-07-30 (Medium, C9), правка к самому эталону: запоминание выполненного
/// переноса (`migrate_once`) сэкономило обращения к диску, но заодно отменило бы контракт
/// «функция отдаёт СУЩЕСТВУЮЩИЙ каталог»: после первого успеха `app_state_dir` возвращал бы путь
/// без единой проверки, и удаление каталога во время работы (чистильщик, антивирус, ручная
/// уборка) роняло бы следующую запись «путь не найден», тогда как раньше каталог восстанавливался
/// сам. Кэшируем факт переноса — да; существование каталога проверяем на каждый вызов
/// (`create_dir_all` на существующем каталоге — один дешёвый системный вызов, а не
/// пересканирование legacy).
fn prepare_state_dir(
    dir: &Path,
    legacy: &Path,
    label: &str,
    copier: impl Fn(&Path, &Path) -> std::io::Result<u64>,
) -> Result<()> {
    migrate_once(dir, legacy, label, copier)?;
    std::fs::create_dir_all(dir)
        .with_context(|| format!("не создать каталог состояния '{label}': {}", dir.display()))?;
    Ok(())
}

/// Перенос НЕ ЧАЩЕ одного успешного раза на каталог в пределах процесса. Блокировка держится на
/// всё время переноса: два потока не переносят один каталог одновременно — второй дожидается и
/// уходит по короткому пути. Отдельная функция ещё и затем, чтобы тест мог проверить именно
/// запоминание, передав пути явно (без глобальных `BASE_DIR`/`LOCALAPPDATA` и без единого
/// обращения к каталогу профиля).
fn migrate_once(
    dir: &Path,
    legacy: &Path,
    label: &str,
    copier: impl Fn(&Path, &Path) -> std::io::Result<u64>,
) -> Result<()> {
    let mut done = migrated_dirs().lock().unwrap_or_else(|e| e.into_inner());
    if done.contains(dir) {
        return Ok(());
    }
    // Ошибка уходит наверх ДО вставки в множество: неудачный перенос обязан пробоваться снова.
    migrate_into(dir, legacy, label, copier)?;
    done.insert(dir.to_path_buf());
    Ok(())
}

/// Ядро переноса — тестируемое, без глобальных LOCALAPPDATA/BASE_DIR (пути передаются явно,
/// `copier` инъецируется, чтобы тест мог детерминированно смоделировать отказ копирования
/// одного файла без порчи файловой системы).
fn migrate_into(
    dir: &Path,
    legacy: &Path,
    label: &str,
    copier: impl Fn(&Path, &Path) -> std::io::Result<u64>,
) -> Result<()> {
    std::fs::create_dir_all(dir).with_context(|| format!("не создать каталог состояния '{label}'"))?;

    let marker = dir.join(MIGRATION_MARKER);
    if marker.exists() {
        return Ok(()); // перенос уже завершён без ошибок — не пересканируем legacy впустую
    }

    if !legacy.is_dir() {
        // Legacy-каталога нет вовсе (чистая установка либо продукт никогда не писал сюда) —
        // переносить нечего; маркер всё равно пишем, чтобы не читать read_dir на каждый вызов.
        std::fs::write(&marker, migration_stamp())
            .with_context(|| format!("не записать маркер переноса {}", marker.display()))?;
        return Ok(());
    }

    let mut copied = 0usize;
    let mut failed: Vec<String> = vec![];

    match std::fs::read_dir(legacy) {
        Ok(read_dir) => {
            for entry in read_dir {
                let entry = match entry {
                    Ok(e) => e,
                    Err(err) => {
                        failed.push(format!("<запись каталога>: {err}"));
                        continue;
                    }
                };
                let src = entry.path();
                if !src.is_file() {
                    continue; // поддиректории (напр. чужие подпродукты) переносом не затрагиваются
                }
                let name = entry.file_name();
                let dst = dir.join(&name);
                if dst.exists() {
                    // Свежая история продукта важнее legacy-копии — не перезаписываем.
                    continue;
                }
                // 🔴 Внешний аудит 2026-07-29 (High): копируем во ВРЕМЕННЫЙ файл рядом и
                // переименовываем. Прямая запись в `dst` при обрыве (питание, полный диск)
                // оставляла усечённый файл, а проверка `dst.exists()` выше пропускала его
                // НАВСЕГДА — маркер записывался, legacy-оригинал больше не читался, и клиент
                // получал обрезанную историю без единого признака сбоя. Переименование в
                // пределах одного каталога атомарно, поэтому промежуточного состояния нет.
                let staging = dir.join(format!(
                    "{}.legacy-migrating",
                    name.to_string_lossy()
                ));
                let _ = std::fs::remove_file(&staging); // хвост прошлого оборванного захода
                match copier(&src, &staging).and_then(|written| {
                    std::fs::rename(&staging, &dst).map(|_| written)
                }) {
                    Ok(_) => copied += 1,
                    Err(err) => {
                        let _ = std::fs::remove_file(&staging);
                        failed.push(format!("{}: {err}", name.to_string_lossy()));
                    }
                }
            }
        }
        Err(err) => failed.push(format!("<не открыт legacy-каталог {}>: {err}", legacy.display())),
    }

    if failed.is_empty() {
        if copied > 0 {
            info!("durable_store: перенесено {copied} файлов из legacy AIAgency/{label}");
        }
        std::fs::write(&marker, migration_stamp())
            .with_context(|| format!("не записать маркер переноса {}", marker.display()))?;
        Ok(())
    } else {
        warn!(
            "durable_store: перенос '{label}' не завершён — {} из {} файлов не скопировано ({}); \
             маркер не записан, следующий запуск попробует снова",
            failed.len(),
            copied + failed.len(),
            failed.join("; ")
        );
        // 🔴 Внешний аудит 2026-07-29 (Critical): раньше здесь возвращался Ok, и потребитель
        // немедленно работал с ПУСТЫМ местом непереехавшего файла — показывал пустую историю и
        // создавал новый файл поверх. На следующем запуске правило «свежее важнее legacy»
        // навсегда закрывало дорогу оригиналу, маркер писался, переписка клиента исчезала без
        // единого признака отказа. Честный отказ лучше молчаливой потери: пусть вызывающий
        // решает, показать ошибку или отступить, но не пишет на место непереехавшего.
        anyhow::bail!(
            "перенос состояния '{label}' не завершён: {} из {} файлов не скопировано ({}). \
             Данные остались в прежнем каталоге; повторите запуск после устранения причины",
            failed.len(),
            copied + failed.len(),
            failed.join("; ")
        );
    }
}

fn migration_stamp() -> String {
    format!(
        "перенесено {}\n",
        chrono::Local::now().format("%Y-%m-%dT%H:%M:%S")
    )
}

// 🔴 Внешний аудит 2026-07-29 (High): три функции ниже возвращены из донора-эталона
// (`ROSST_AI_Media/src-tauri/src/durable_store.rs`, продукт Smart Analytica) — при переносе
// состояния в per-app каталог сюда перенесли только миграционную логику (`migrate_into` выше), а
// эти защитные примитивы забыли. Без них: `save_message`/`save_to_disk`/`save_ratings` писали
// напрямую в целевой файл — обрыв процесса на середине записи оставлял усечённый JSON; чтение
// битого JSON падало на `unwrap_or_else`/`unwrap_or_default()` без следа — файл истории/метрик
// молча превращался в пустой список, и следующее же сохранение стирало оригинал НАВСЕГДА (тот же
// класс отказа, что и у `migrate_into` при обрыве переноса, только не при переносе, а при обычной
// работе); `audit.log` рос без предела.

/// Единый цикл повторов для ВСЕХ временных отказов вокруг файлов состояния: 5 попыток по 100 мс,
/// то есть не дольше полусекунды ожидания.
///
/// 🔴 Внешний аудит 2026-07-30, поправка к контракту (одна константа на три места намеренно):
/// столько ждут и межпроцессный замок истории (`session/history.rs`), и повторное чтение перед
/// записью (`load_json_for_update`), и повторная атомарная замена в `write_atomic`. Причина у них
/// одна — файл состояния кем-то ненадолго занят (второе окно, индексатор, антивирус, резервное
/// копирование), и она проходит за миллисекунды. Полсекунды, а не три: `save_message` вызывается
/// СИНХРОННОЙ командой `save_chat_message` (`lib.rs`), то есть ожидание лежит на пути из
/// интерфейса, а три секунды защищали бы от того, чего не бывает.
pub const STATE_RETRY_ATTEMPTS: u32 = 5;
pub const STATE_RETRY_PAUSE: std::time::Duration = std::time::Duration::from_millis(100);

/// Счётчик временных файлов атомарной записи — растёт монотонно в пределах процесса.
static TMP_WRITE_SEQ: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// Имя временного файла атомарной записи: `<имя цели>.<pid>-<номер>.tmp.write`, рядом с целью.
///
/// 🔴 Внешний аудит 2026-07-30 (Medium, C6): имя было ФИКСИРОВАННЫМ (`with_extension("tmp.write")`),
/// то есть два процесса, пишущих один файл истории, писали в ОДИН временный файл вперемешку, а
/// `rename` клал на место цели смесь двух JSON — следующий запуск получал битый файл. Идентификатор
/// процесса разводит экземпляры приложения, монотонный счётчик — потоки и последовательные записи
/// одного процесса (тот же приём, что в реестре CPD-15, упрочнение №6). Файл обязан лежать в ТОМ ЖЕ
/// каталоге, что цель: переименование атомарно только в пределах тома, а по каталогам действуют
/// разные права.
fn tmp_write_path(path: &Path) -> PathBuf {
    let seq = TMP_WRITE_SEQ.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let name = path
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| "state".to_string());
    path.with_file_name(format!("{name}.{}-{seq}.tmp.write", std::process::id()))
}

/// Атомарная запись: временный файл в том же каталоге → сброс на диск → `rename`.
///
/// 🔴 Внешний аудит 2026-07-30 (High, C5): `sync_all()` ДО переименования — не украшение. Без него
/// при обрыве питания метаданные переименования ложатся на диск раньше содержимого: целевой файл
/// существует, но обрезан или забит нулями, а дальше по C1 такой файл уводится в карантин, и
/// клиент видит пустую историю. В этой же линейке более сильная реализация уже была —
/// `Aurora_Creative_Hub/src-tauri/src/commands/content_updater.rs` (`sync_all` + комментарий ровно
/// про эту опасность), то есть «возвращённый из донора» примитив был слабее соседнего, а докстринг
/// обещал больше, чем делал. Сторож — `tests::write_atomic_syncs_tmp_file_before_rename`.
pub fn write_atomic(path: &Path, bytes: &[u8]) -> Result<()> {
    let tmp = tmp_write_path(path);
    let staged = (|| -> Result<()> {
        use std::io::Write;
        let mut file = std::fs::File::create(&tmp)
            .with_context(|| format!("не создать временный файл {}", tmp.display()))?;
        file.write_all(bytes)
            .with_context(|| format!("не записать {}", tmp.display()))?;
        file.sync_all()
            .with_context(|| format!("не сброшен на диск {}", tmp.display()))?;
        Ok(())
    })();
    if let Err(e) = staged {
        // Имя временного файла теперь уникально, поэтому неудачный заход больше не будет
        // перезаписан следующим — убираем за собой сами.
        let _ = std::fs::remove_file(&tmp);
        return Err(e);
    }
    // 🔴 Внешний аудит 2026-07-30, поправка к контракту (F-13/M05): запасной ветки
    // «`remove_file`(цель), затем `rename`» здесь БОЛЬШЕ НЕТ. Между удалением и переименованием
    // файла на диске не существовало вовсе, а `load_json` в этот миг честно отвечает `Absent` —
    // «файла нет, законно начинать с пустого». То есть весь труд C1 по отделению отказа от пустоты
    // обходился с фланга: второе окно на чтении истории показало бы клиенту пустую переписку, а
    // сохранение поверх неё довершило бы потерю. Замены цели удалением не требуется:
    // `std::fs::rename` на Windows — это `MoveFileExW(MOVEFILE_REPLACE_EXISTING)` (раздел
    // «Platform-specific behavior» его документации), то есть замена уже атомарна, момента без
    // файла не бывает. Отказ здесь означает не «нужно удалить цель», а «файл кем-то держится»
    // (индексатор, антивирус, второе окно) — это проходит, поэтому повторяем ту же атомарную
    // замену, а не ломаем инвариант.
    let mut last_err = None;
    for attempt in 0..STATE_RETRY_ATTEMPTS {
        match std::fs::rename(&tmp, path) {
            Ok(()) => return Ok(()),
            Err(e) => {
                last_err = Some(e);
                if attempt + 1 < STATE_RETRY_ATTEMPTS {
                    std::thread::sleep(STATE_RETRY_PAUSE);
                }
            }
        }
    }
    // Ни старое, ни новое не потеряно: цель на месте, новое содержимое лежит в tmp. Временный файл
    // намеренно НЕ удаляется — в нём единственная копия несохранённого, и стереть её значит
    // потерять и то, и другое разом.
    Err(anyhow::anyhow!(
        "не заменить {} за {} попыток: {} (новое содержимое сохранено в {} — прежний файл цел)",
        path.display(),
        STATE_RETRY_ATTEMPTS,
        last_err
            .map(|e| e.to_string())
            .unwrap_or_else(|| "причина неизвестна".to_string()),
        tmp.display()
    ))
}

/// Исход чтения файла состояния. Три состояния, потому что вызывающему они нужны разные.
///
/// 🔴 Внешний аудит 2026-07-30 (High, C1), корень тот же, что у CPD-26 и CPD-28: три РАЗНЫХ факта —
/// «файла нет», «файл испорчен» и «файл есть, но прочитать нельзя» — сводились к одному значению
/// `None`, а вызывающий делал `unwrap_or_default()`. Отказ чтения выглядел пустой историей, и
/// следующая запись затирала переписку клиента.
pub enum LoadOutcome<T> {
    /// Прочитано и разобрано.
    Loaded(T),
    /// Файла нет — законно начинать с пустого значения.
    Absent,
    /// Файл был испорчен, уведён в карантин; исходник сохранён. Законно начинать с пустого.
    Quarantined,
}

impl<T> LoadOutcome<T> {
    /// Прочитанное значение либо `None` для двух ЗАКОННЫХ пустот (`Absent`, `Quarantined`).
    /// Отказ чтения сюда не попадает вовсе — он остался в `Err` у `load_json`.
    pub fn into_value(self) -> Option<T> {
        match self {
            LoadOutcome::Loaded(v) => Some(v),
            LoadOutcome::Absent | LoadOutcome::Quarantined => None,
        }
    }
}

/// Прочитать файл состояния, РАЗЛИЧАЯ исходы.
///
/// `Err` означает «файл есть, но прочитать его сейчас нельзя» (нет прав, занят другим процессом).
/// 🔴 Вызывающий ОБЯЗАН в этом случае отказаться от записи: пустой список поверх нечитаемого файла
/// уничтожает переписку клиента. Потерять одно новое сообщение дешевле, чем всю историю.
///
/// Отнесение исходов:
/// - файла нет → `Absent`;
/// - `read_to_string` вернул `Err(InvalidData)` → содержимое не UTF-8, признак усечения на
///   многобайтовом символе, то есть ПОРЧА → карантин → `Quarantined`;
/// - `read_to_string` вернул любой другой `Err` → ОТКАЗ, возвращается `Err`, карантин НЕ делается:
///   файл цел, и портить его переносом нельзя;
/// - разбор JSON не удался → карантин → `Quarantined`.
pub fn load_json<T: serde::de::DeserializeOwned>(path: &Path) -> Result<LoadOutcome<T>> {
    if !path.exists() {
        return Ok(LoadOutcome::Absent);
    }
    let content = match std::fs::read_to_string(path) {
        Ok(c) => c,
        Err(e) if e.kind() == std::io::ErrorKind::InvalidData => {
            // Не-UTF-8: ровно тот отказ, ради которого вводили атомарную запись — файл усечён
            // посреди многобайтового символа. Это порча, её место в карантине.
            quarantine(path, &format!("содержимое не UTF-8: {e}"));
            return Ok(LoadOutcome::Quarantined);
        }
        Err(e) => {
            return Err(anyhow::Error::new(e).context(format!(
                "файл состояния {} есть, но прочитать его сейчас нельзя — запись поверх него \
                 уничтожила бы данные клиента",
                path.display()
            )));
        }
    };
    match serde_json::from_str::<T>(&content) {
        Ok(v) => Ok(LoadOutcome::Loaded(v)),
        Err(e) => {
            quarantine(path, &format!("не разобран JSON: {e}"));
            Ok(LoadOutcome::Quarantined)
        }
    }
}

/// То же чтение, но с повторами: для путей, за которыми немедленно следует ЗАПИСЬ того же файла.
///
/// 🔴 Внешний аудит 2026-07-30, поправка 1 к контракту (F-12). Асимметрия была перевёрнута: замку
/// давалось много попыток, а отказу чтения — ни одной, хотя замок мы создаём сами и держим
/// миллисекунды, а файл истории открывают все подряд — индексация, антивирус, резервное
/// копирование, второе окно. Именно у него отказ чаще всего мгновенный и проходящий, и отказывать
/// клиенту в сохранении из-за сорокамиллисекундного касания антивируса — не защита, а её
/// видимость. Повторяется ТОЛЬКО отказ чтения: `Absent` и `Quarantined` — окончательные ответы,
/// ждать по ним нечего. Чтению «на показ» повторы не нужны — там за отказом не следует запись, и
/// лишняя задержка экрана хуже, чем пустой список с предупреждением в журнале.
pub fn load_json_for_update<T: serde::de::DeserializeOwned>(path: &Path) -> Result<LoadOutcome<T>> {
    let mut last_err = None;
    for attempt in 0..STATE_RETRY_ATTEMPTS {
        match load_json(path) {
            Ok(outcome) => return Ok(outcome),
            Err(e) => {
                last_err = Some(e);
                if attempt + 1 < STATE_RETRY_ATTEMPTS {
                    std::thread::sleep(STATE_RETRY_PAUSE);
                }
            }
        }
    }
    Err(last_err
        .unwrap_or_else(|| anyhow::anyhow!("файл состояния {} не прочитан", path.display()))
        .context(format!(
            "файл состояния {} не удалось прочитать за {} попыток — запись отменена, чтобы не \
             затереть данные клиента пустотой",
            path.display(),
            STATE_RETRY_ATTEMPTS
        )))
}

/// Хвост имени карантинной копии. Общий для записи (`quarantine_path`) и поиска
/// (`quarantine_copies_of`) — чтобы «очистить историю» не разошлась с тем, что кладёт карантин.
const QUARANTINE_SUFFIX: &str = ".corrupt.bak";

/// Имя карантинной копии: `<кабинет>.<отметка времени>.corrupt.bak`.
///
/// 🔴 Внешний аудит 2026-07-30 (Medium, C7): карантин всегда писался в ОДИН путь
/// `<имя>.corrupt.bak`, а `rename` на Windows заменяет цель — вторая порча молча уничтожала первую
/// карантинную копию клиента. Отметка времени с миллисекундами разводит заходы; на случай двух
/// порч в одну миллисекунду имя досчитывается суффиксом-номером до свободного.
fn quarantine_path(path: &Path) -> PathBuf {
    let stem = path
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "state".to_string());
    let stamp = chrono::Local::now().format("%Y%m%d-%H%M%S%3f");
    let mut candidate = path.with_file_name(format!("{stem}.{stamp}{QUARANTINE_SUFFIX}"));
    let mut n = 1u32;
    while candidate.exists() {
        candidate = path.with_file_name(format!("{stem}.{stamp}-{n}{QUARANTINE_SUFFIX}"));
        n += 1;
    }
    candidate
}

/// Увести испорченный файл в карантин. Отказ самого переноса больше не глотается молча
/// (`let _ =`) — иначе «данные клиента сохранены» остаётся обещанием без подтверждения.
fn quarantine(path: &Path, reason: &str) {
    let bak = quarantine_path(path);
    match std::fs::rename(path, &bak) {
        Ok(()) => warn!(
            "durable_store: {} испорчен → карантин {} ({reason})",
            path.display(),
            bak.display()
        ),
        Err(e) => warn!(
            "durable_store: {} испорчен ({reason}), но НЕ уведён в карантин {}: {e} — \
             следующая запись может затереть исходник",
            path.display(),
            bak.display()
        ),
    }
}

/// Карантинные копии ТОГО ЖЕ файла состояния: `<кабинет>.*.corrupt.bak` рядом с ним.
/// Нужны «очистке истории» (C8): без этого полная переписка клиента оставалась на диске
/// бессрочно, а продукт при этом сообщал об успешной очистке. Копии прежнего формата
/// (`<кабинет>.corrupt.bak`, без отметки времени) под тот же образец подходят и тоже находятся.
pub fn quarantine_copies_of(path: &Path) -> Vec<PathBuf> {
    let (Some(dir), Some(stem)) = (path.parent(), path.file_stem()) else {
        return vec![];
    };
    let prefix = format!("{}.", stem.to_string_lossy());
    let read_dir = match std::fs::read_dir(dir) {
        Ok(rd) => rd,
        Err(_) => return vec![],
    };
    read_dir
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| {
            p.is_file()
                && p.file_name()
                    .and_then(|n| n.to_str())
                    .is_some_and(|n| n.starts_with(&prefix) && n.ends_with(QUARANTINE_SUFFIX))
        })
        .collect()
}

/// Прочитать JSON; битый файл НЕ теряется молча — уводится в карантин с warn.
///
/// 🔴 Тонкая обёртка над `load_json`, оставленная для совместимости. Она ТЕРЯЕТ различие
/// «отказ чтения / законная пустота»: и то, и другое отдаётся как `None`. Не использовать на
/// путях, за которыми следует ЗАПИСЬ того же файла — там нужен `load_json`, чтобы отказ прервал
/// запись, а не превратился в пустой список поверх нечитаемой переписки клиента.
pub fn read_json_or_quarantine<T: serde::de::DeserializeOwned>(path: &Path) -> Option<T> {
    match load_json(path) {
        Ok(outcome) => outcome.into_value(),
        Err(e) => {
            warn!("durable_store: не прочитан {}: {e:#}", path.display());
            None
        }
    }
}

/// Расхождение базы состояния с тем, что фактически считает своим каталогом Tauri.
/// Чистое сравнение двух путей (без единого обращения к диску и к глобальному `BASE_DIR`) —
/// чтобы сторож не жил в системе координат самого дефекта: `build_identifier_matches_tauri_conf`
/// сверяет идентификатор ТЕМ ЖЕ рукописным разбором `tauri.conf.json`, что и `build.rs`, и на
/// одинаковой ошибке разбора остаётся зелёным. Внешний источник правды — `app_local_data_dir()`,
/// он доступен в `.setup()` (см. `lib.rs`). Возвращает описание расхождения или `None`.
///
/// 🔴 У Econometrica это единственная проверка, которая покрывает ОБЕ редакции разом: локальная
/// собирается с оверлеем `TAURI_CONFIG` (identifier `com.aurora.econometrica.local`), и
/// `app_local_data_dir()` в ней вернёт каталог по слитой конфигурации — тот же, что вычислил
/// `tauri_build`. Если разбор оверлея в `build.rs` когда-нибудь отвалится, локальная редакция
/// начнёт писать в каталог облачной, и увидим это ЗДЕСЬ, а не по жалобе клиента.
///
/// Сравнение нечувствительно к регистру и к завершающему разделителю: на Windows путь профиля
/// приходит в разном регистре из разных источников, и ложное предупреждение обесценило бы сторож.
pub fn describe_base_mismatch(actual: &Path, resolved: &Path) -> Option<String> {
    fn normalize(p: &Path) -> String {
        let s = p.to_string_lossy().replace('/', "\\");
        let s = s.trim_end_matches('\\').to_string();
        if cfg!(windows) { s.to_lowercase() } else { s }
    }
    if normalize(actual) == normalize(resolved) {
        return None;
    }
    Some(format!(
        "база состояния разошлась с каталогом приложения: Tauri отдаёт '{}', durable_store пишет \
         в '{}' — история, метрики и сессии уходят не туда, где лежат остальные данные приложения, \
         и деинсталлятор их не вычистит",
        actual.display(),
        resolved.display()
    ))
}

/// Ротация лог-файла: при превышении лимита текущий уходит в `<имя>.1` (одно поколение).
pub fn rotate_if_large(path: &Path, max_bytes: u64) {
    if let Ok(md) = std::fs::metadata(path) {
        if md.len() > max_bytes {
            let rolled = path.with_extension("log.1");
            let _ = std::fs::remove_file(&rolled);
            if std::fs::rename(path, &rolled).is_ok() {
                info!("durable_store: ротация {} (> {} байт)", path.display(), max_bytes);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_file(dir: &Path, name: &str, content: &str) {
        std::fs::create_dir_all(dir).unwrap();
        std::fs::write(dir.join(name), content).unwrap();
    }

    /// 🔴 Внешний аудит 2026-07-29, вторая волна (Critical). Идентификатор приложения, вшитый
    /// в бинарь, обязан совпадать с тем, что стоит в `tauri.conf.json`. Прежняя правка читала
    /// `option_env!("TAURI_ENV_IDENTIFIER")` — переменную, которую НЕ выставляет никто, поэтому
    /// условие инициализации не выполнялось ни разу, и состояние молча уходило в запасной
    /// каталог по имени пакета (`%LOCALAPPDATA%\aurora-econometrica-gui` вместо
    /// `…\com.aurora.econometrica`).
    ///
    /// Сторож намеренно сверяет ЗНАЧЕНИЕ, а не наличие имени переменной в исходнике: проверка
    /// «имя упоминается» зеленела бы ровно в том случае, ради которого её заводят, — когда
    /// значение не доехало. `env!` (а не `option_env!`) выбран сознательно: если `build.rs`
    /// перестанет класть идентификатор, сборка упадёт на компиляции, а не подсунет молчаливый
    /// запасной путь.
    ///
    /// 🔴 Батч C, C10: прежняя редакция теста сверяла ТОЛЬКО базовый `tauri.conf.json` и честно
    /// это признавала — «`TAURI_CONFIG`-оверлей локальной редакции этим тестом не покрыт». То
    /// есть у Econometrica ровно одна из двух поставляемых редакций (локальная, `com.aurora.
    /// econometrica.local`, где лежат ПДн клиента по 152-ФЗ) не была покрыта ничем. Теперь тест
    /// сверяет идентификатор с ТОЙ конфигурацией, по которой собран ЭТОТ бинарь: собран с
    /// оверлеем — сверяется с оверлеем, без него — с базовым файлом.
    ///
    /// Признак редакции берётся не из вывода `build.rs`, а из того же внешнего источника, что
    /// читает сам `tauri_build`, — переменной `TAURI_CONFIG` (её выставляет tauri-cli при
    /// `tauri build --config tauri.local.conf.json`). Иначе тест сверял бы решение `build.rs`
    /// с ним же самим.
    ///
    /// Остаточная слабость названа прямо: разбор JSON здесь СВОЙ, и одинаковая ошибка разбора
    /// тут и в `build.rs` оставила бы тест зелёным. Поэтому она закрыта не тестом, а
    /// `describe_base_mismatch` в `.setup()` (`lib.rs`): там фактический `app_local_data_dir()`
    /// от Tauri сверяется с базой `durable_store` уже в бою — и в обеих редакциях.
    fn identifier_in(json_text: &str) -> Option<String> {
        let idx = json_text.find("\"identifier\"")?;
        let after_key = &json_text[idx + "\"identifier\"".len()..];
        let after_colon = after_key.trim_start().strip_prefix(':')?.trim_start();
        let after_quote = after_colon.strip_prefix('"')?;
        let end = after_quote.find('"')?;
        Some(after_quote[..end].to_string())
    }

    #[test]
    fn build_identifier_matches_tauri_conf() {
        let embedded = env!("AURORA_APP_IDENTIFIER");
        let cloud = identifier_in(include_str!("../tauri.conf.json"))
            .expect("в tauri.conf.json не найдено поле identifier — разметка конфигурации переехала");
        let local = identifier_in(include_str!("../tauri.local.conf.json")).expect(
            "в tauri.local.conf.json не найдено поле identifier — оверлей локальной редакции \
             перестал задавать свой каталог приложения, и ПДн локальной редакции лягут в каталог \
             облачной",
        );

        assert!(!cloud.is_empty(), "identifier в tauri.conf.json пуст");
        assert_ne!(
            cloud, local,
            "у облачной и локальной редакций обязаны быть РАЗНЫЕ идентификаторы: одинаковые \
             означают общий каталог состояния, то есть CPD-30 внутри одного продукта"
        );

        // Какая редакция собрана — говорит `TAURI_CONFIG`, тот же оверлей, из которого берёт
        // итоговый identifier сам `tauri_build` (и который затем вернёт `app_local_data_dir()`).
        let expected = option_env!("TAURI_CONFIG")
            .and_then(identifier_in)
            .unwrap_or_else(|| cloud.clone());

        assert_eq!(
            embedded, expected,
            "идентификатор в бинаре разошёлся с конфигурацией этой сборки: состояние уйдёт не в \
             тот каталог приложения, а деинсталлятор его не вычистит"
        );
    }

    /// Отображение `sub → каталог` и `sub → legacy-каталог` (внешний аудит, Medium: подмена
    /// этой строки не красила ничего). Тест не трогает диск и не зависит от того, вызывал ли
    /// кто-то `init()` в этом процессе, — сверяются только хвосты пути.
    #[test]
    fn resolve_maps_sub_to_subdirectory_of_base() {
        let base = base_dir();
        assert_eq!(resolve_path(""), base, "пустой sub — это сам каталог приложения");
        assert_eq!(
            resolve_path("history"),
            base.join("history"),
            "sub обязан становиться подкаталогом базы"
        );
        assert!(
            resolve_path("history").starts_with(&base),
            "резолв увёл путь за пределы базы"
        );
    }

    /// Конкретно-типизированная обёртка над `std::fs::copy` — generic fn-item напрямую как
    /// `impl Fn(&Path, &Path) -> ...` не проходит из-за HRTB-инференции лайфтаймов.
    fn real_copy(s: &Path, d: &Path) -> std::io::Result<u64> {
        std::fs::copy(s, d)
    }

    /// 🔴 Регресс внешнего аудита 2026-07-29 (High): обрыв ВНУТРИ копирования не должен
    /// оставлять усечённый файл в целевом каталоге. Прежде копирование шло прямо в цель, и
    /// оборванный файл на следующем запуске выглядел как уже перенесённый (`dst.exists()` →
    /// пропуск НАВСЕГДА), маркер записывался, legacy-оригинал больше не читался — клиент
    /// получал обрезанную историю без единого признака сбоя.
    #[test]
    fn interrupted_copy_leaves_no_truncated_file_and_resumes_next_run() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let new_dir = tmp.path().join("new");
        write_file(&legacy, "history.json", "полное содержимое истории клиента");

        // Первый заход: копирование записывает ЧАСТЬ и падает — ровно как обрыв питания.
        fn truncating_copy(s: &Path, d: &Path) -> std::io::Result<u64> {
            let content = std::fs::read(s)?;
            std::fs::write(d, &content[..content.len() / 2])?;
            Err(std::io::Error::new(
                std::io::ErrorKind::WriteZero,
                "обрыв на середине копирования",
            ))
        }
        assert!(
            migrate_into(&new_dir, &legacy, "history", truncating_copy).is_err(),
            "обрыв копирования — неполный перенос, он обязан вернуть ошибку"
        );
        assert!(
            !new_dir.join("history.json").exists(),
            "усечённого файла в целевом каталоге быть не должно — иначе следующий запуск примет \
             его за перенесённый и пропустит навсегда"
        );
        assert!(
            !new_dir.join(MIGRATION_MARKER).exists(),
            "маркера после отказа копирования быть не должно"
        );

        // Второй заход: копирование исправно — файл обязан доехать ЦЕЛИКОМ.
        migrate_into(&new_dir, &legacy, "history", real_copy).unwrap();
        assert_eq!(
            std::fs::read_to_string(new_dir.join("history.json")).unwrap(),
            "полное содержимое истории клиента",
            "после дозавершения в целевом каталоге обязан лежать ПОЛНЫЙ файл"
        );
        assert!(new_dir.join(MIGRATION_MARKER).exists());
    }

    /// (а) Перенос при пустом новом каталоге переносит файлы.
    #[test]
    fn migration_copies_files_into_empty_new_dir() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let new_dir = tmp.path().join("new");
        write_file(&legacy, "a.json", "A");
        write_file(&legacy, "b.json", "B");

        migrate_into(&new_dir, &legacy, "test", real_copy).unwrap();

        assert_eq!(std::fs::read_to_string(new_dir.join("a.json")).unwrap(), "A");
        assert_eq!(std::fs::read_to_string(new_dir.join("b.json")).unwrap(), "B");
        assert!(new_dir.join(MIGRATION_MARKER).exists(), "маркер обязан быть записан после успешного переноса");
    }

    /// (б) Повторный запуск ничего не дублирует и не перезаписывает.
    #[test]
    fn second_run_does_not_duplicate_or_overwrite() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let new_dir = tmp.path().join("new");
        write_file(&legacy, "a.json", "legacy-A");

        migrate_into(&new_dir, &legacy, "test", real_copy).unwrap();
        // Продукт поработал — файл в новом каталоге изменился своей жизнью.
        std::fs::write(new_dir.join("a.json"), "fresh-A-after-first-run").unwrap();
        std::fs::write(legacy.join("a.json"), "legacy-A-changed-later").unwrap();

        migrate_into(&new_dir, &legacy, "test", real_copy).unwrap();

        assert_eq!(
            std::fs::read_to_string(new_dir.join("a.json")).unwrap(),
            "fresh-A-after-first-run",
            "повторный вызов после маркера не имеет права трогать файлы"
        );
    }

    /// (в) ГЛАВНЫЙ тест: оборванный перенос (маркера нет, часть файлов уже на месте)
    /// дозавершается при следующем запуске — ради этого весь контракт.
    #[test]
    fn interrupted_migration_resumes_on_next_run() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let new_dir = tmp.path().join("new");
        write_file(&legacy, "a.json", "A");
        write_file(&legacy, "b.json", "B");
        write_file(&new_dir, "a.json", "A"); // уже скопирован до "обрыва питания"
        assert!(!new_dir.join(MIGRATION_MARKER).exists(), "маркера после обрыва быть не должно");

        migrate_into(&new_dir, &legacy, "test", real_copy).unwrap();

        assert_eq!(
            std::fs::read_to_string(new_dir.join("b.json")).unwrap(), "B",
            "недостающий файл обязан докопироваться при следующем запуске"
        );
        assert!(new_dir.join(MIGRATION_MARKER).exists(), "после дозавершения маркер обязан появиться");
    }

    /// (г) Существующий в новом каталоге файл не затирается legacy-версией.
    #[test]
    fn existing_file_in_new_dir_is_not_overwritten_by_legacy() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let new_dir = tmp.path().join("new");
        write_file(&legacy, "a.json", "legacy-version");
        write_file(&new_dir, "a.json", "fresh-product-version");

        migrate_into(&new_dir, &legacy, "test", real_copy).unwrap();

        assert_eq!(
            std::fs::read_to_string(new_dir.join("a.json")).unwrap(),
            "fresh-product-version",
            "свежая история продукта важнее legacy-копии"
        );
    }

    #[test]
    fn no_legacy_dir_still_marks_migration_done() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("does-not-exist");
        let new_dir = tmp.path().join("new");

        migrate_into(&new_dir, &legacy, "test", real_copy).unwrap();
        assert!(new_dir.join(MIGRATION_MARKER).exists());
    }

    /// Отказ копирования ОДНОГО файла — маркер не пишется, следующий вызов (уже без отказа)
    /// докапирует недостающее. Отказ смоделирован инъецированным `copier`, а не порчей ФС —
    /// детерминированно и кроссплатформенно.
    #[test]
    fn one_failed_file_blocks_marker_and_retries_next_run() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let new_dir = tmp.path().join("new");
        write_file(&legacy, "a.json", "A");
        write_file(&legacy, "b.json", "B"); // этот "не скопируется"

        let failing_copier = |src: &Path, dst: &Path| -> std::io::Result<u64> {
            if src.file_name().and_then(|n| n.to_str()) == Some("b.json") {
                return Err(std::io::Error::new(std::io::ErrorKind::PermissionDenied, "смоделированный отказ"));
            }
            std::fs::copy(src, dst)
        };

        // 🔴 Внешний аудит 2026-07-29 (Critical): неполный перенос теперь ОШИБКА. Раньше здесь
        // возвращался Ok, и потребитель работал с пустым местом непереехавшего файла — создавал
        // новый файл поверх, а следующий заход навсегда закрывал дорогу оригиналу.
        let outcome = migrate_into(&new_dir, &legacy, "test", failing_copier);
        assert!(
            outcome.is_err(),
            "перенос с отказавшим файлом обязан вернуть ошибку, а не тихий успех"
        );

        assert_eq!(std::fs::read_to_string(new_dir.join("a.json")).unwrap(), "A", "успешный файл обязан скопироваться");
        assert!(!new_dir.join("b.json").exists(), "провалившийся файл не должен появиться");
        assert!(!new_dir.join(MIGRATION_MARKER).exists(), "хотя бы один отказ — маркер не пишется");

        // Следующий запуск — уже без отказа — обязан докопировать недостающее.
        migrate_into(&new_dir, &legacy, "test", real_copy).unwrap();
        assert_eq!(std::fs::read_to_string(new_dir.join("b.json")).unwrap(), "B", "повтор обязан докопировать после отказа");
        assert!(new_dir.join(MIGRATION_MARKER).exists());
    }

    /// Файлы прямо в legacy-корне (`sub=""`, случай audit.log) — join("") не должен ломать путь.
    #[test]
    fn empty_sub_targets_base_dir_itself() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy-root");
        let new_dir = tmp.path().join("new-root");
        write_file(&legacy, "audit.log", "log-line-1\n");

        migrate_into(&new_dir, &legacy, "", real_copy).unwrap();

        assert_eq!(std::fs::read_to_string(new_dir.join("audit.log")).unwrap(), "log-line-1\n");
        assert!(new_dir.join(MIGRATION_MARKER).exists());
    }

    // ── Внешний аудит 2026-07-29 (High): три защитных примитива, возвращённые из донора выше
    // (write_atomic / read_json_or_quarantine / rotate_if_large).

    /// Бюллет 3 задачи: после атомарной записи в целевом файле лежит ЦЕЛИКОМ новое содержимое,
    /// а временные файлы не остаются валяться в каталоге.
    ///
    /// 🔴 Правка батча C (C6): имя временного файла больше не фиксированное
    /// (`<имя>.tmp.write`) — оно несёт идентификатор процесса и монотонный счётчик, поэтому
    /// проверка одного конкретного имени стала бы зелёной тавтологией. Теперь каталог
    /// проверяется на ЛЮБЫЕ остатки `*.tmp.write`.
    #[test]
    fn atomic_write_replaces_existing_and_leaves_no_tmp_file() {
        let tmp = tempfile::tempdir().unwrap();
        let f = tmp.path().join("x.json");
        write_atomic(&f, b"[1]").unwrap();
        write_atomic(&f, b"[1,2]").unwrap();
        assert_eq!(std::fs::read_to_string(&f).unwrap(), "[1,2]", "содержимое обязано быть целиком новым");

        let leftovers: Vec<String> = std::fs::read_dir(tmp.path())
            .unwrap()
            .filter_map(|e| e.ok())
            .map(|e| e.file_name().to_string_lossy().to_string())
            .filter(|n| n.ends_with(".tmp.write"))
            .collect();
        assert!(
            leftovers.is_empty(),
            "временные файлы не должны оставаться после успешного переименования: {leftovers:?}"
        );
    }

    /// Бюллет 1 задачи (на уровне примитива): битый JSON не подменяется молча пустым значением —
    /// уходит в карантин.
    ///
    /// 🔴 Правка батча C (C7): имя карантинной копии теперь несёт отметку времени, поэтому
    /// проверяется НАЛИЧИЕ копии через `quarantine_copies_of`, а не фиксированное имя
    /// `<имя>.corrupt.bak`. Прежняя формулировка «копия лежит по фиксированному пути» отменена
    /// намеренно: именно фиксированное имя и уничтожало первую копию при второй порче.
    #[test]
    fn corrupt_json_goes_to_quarantine_not_silence() {
        let tmp = tempfile::tempdir().unwrap();
        let f = tmp.path().join("h.json");
        std::fs::write(&f, "{битый").unwrap();
        let r: Option<Vec<u32>> = read_json_or_quarantine(&f);
        assert!(r.is_none());
        assert!(!f.exists(), "битый файл должен уйти в карантин");
        assert_eq!(
            quarantine_copies_of(&f).len(),
            1,
            "карантин-копия обязана существовать рядом с исходным файлом"
        );
    }

    /// Бюллет 2 задачи: после карантина исходное содержимое битого файла сохранено дословно —
    /// данные клиента не уничтожены, их можно восстановить вручную из карантинной копии.
    #[test]
    fn quarantine_preserves_original_corrupt_content() {
        let tmp = tempfile::tempdir().unwrap();
        let f = tmp.path().join("h.json");
        let garbage = "{битый json, не список сообщений клиента";
        std::fs::write(&f, garbage).unwrap();
        let r: Option<Vec<u32>> = read_json_or_quarantine(&f);
        assert!(r.is_none());
        let copies = quarantine_copies_of(&f);
        assert_eq!(copies.len(), 1, "карантинная копия обязана быть ровно одна: {copies:?}");
        assert_eq!(
            std::fs::read_to_string(&copies[0]).unwrap(),
            garbage,
            "карантинная копия обязана содержать ИСХОДНЫЕ байты без искажения"
        );
    }

    /// Бюллет 4 задачи: ротация срабатывает при превышении порога и не теряет содержимое —
    /// текущий файл уходит в `<имя>.1` целиком, а не обрезается и не отбрасывается.
    #[test]
    fn rotate_rolls_over_and_preserves_content() {
        let dir = std::env::temp_dir().join(format!("ds_test_r_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let f = dir.join("a.log");
        let content = vec![b'x'; 100];
        std::fs::write(&f, &content).unwrap();
        rotate_if_large(&f, 10);
        assert!(!f.exists(), "текущий путь обязан освободиться для нового лога");
        assert_eq!(
            std::fs::read(f.with_extension("log.1")).unwrap(), content,
            "содержимое ротированного файла обязано остаться полным — не потеряны свежие записи"
        );
        // Ниже порога — ротации не происходит (файла для сравнения ещё нет).
        std::fs::write(&f, vec![b'y'; 5]).unwrap();
        rotate_if_large(&f, 10);
        assert!(f.exists(), "файл ниже порога не должен ротироваться");
        let _ = std::fs::remove_dir_all(&dir);
    }

    // ── Батч C (2026-07-30): различение отказа чтения и пустоты, упрочнение атомарной записи,
    // запоминание переноса, сверка базы состояния.

    /// 🔴 Сторож C1 №1. Файл с ВАЛИДНЫМ JSON, усечённый посреди двухбайтового русского символа,
    /// — ровно тот отказ, ради которого вводили атомарную запись. `read_to_string` отдаёт на нём
    /// `InvalidData`, и это ПОРЧА: файл обязан уйти в карантин ПОБАЙТОВО, а последующая запись —
    /// не уничтожить исходник. Раньше эта ветка молча давала `None`, вызывающий делал
    /// `unwrap_or_default()` и затирал переписку клиента одним новым сообщением.
    #[test]
    fn truncated_utf8_is_quarantined_byte_for_byte_and_survives_next_write() {
        let tmp = tempfile::tempdir().unwrap();
        let f = tmp.path().join("econometrist.json");

        let full = r#"["Здравствуйте, нужна оценка медиабюджета"]"#.as_bytes().to_vec();
        let cut = full.len() - 9; // приходится на середину многобайтового символа
        let truncated = &full[..cut];
        assert!(
            std::str::from_utf8(truncated).is_err(),
            "предпосылка теста: обрезка обязана попасть в середину многобайтового символа"
        );
        std::fs::write(&f, truncated).unwrap();

        let outcome: LoadOutcome<Vec<String>> = load_json(&f).expect(
            "усечение — это порча, а не отказ чтения: функция обязана вернуть Ok(Quarantined), \
             а не ошибку",
        );
        assert!(
            matches!(outcome, LoadOutcome::Quarantined),
            "усечённый на многобайтовом символе файл обязан быть распознан как порча и уведён \
             в карантин"
        );

        let copies = quarantine_copies_of(&f);
        assert_eq!(copies.len(), 1, "карантинная копия обязана появиться рядом: {copies:?}");
        assert_eq!(
            std::fs::read(&copies[0]).unwrap(),
            truncated,
            "в карантине обязаны лежать ИСХОДНЫЕ байты клиента, побайтово"
        );

        // Последующая запись идёт на освободившийся путь и НЕ трогает карантин.
        write_atomic(&f, "[\"новое сообщение\"]".as_bytes()).unwrap();
        assert_eq!(
            std::fs::read(&copies[0]).unwrap(),
            truncated,
            "последующая запись не имеет права уничтожить карантинную копию"
        );
    }

    /// 🔴 Сторож C1 №2. Файл, занятый монопольно (так его держит живое второе окно продукта), —
    /// это ОТКАЗ чтения, а не пустота: `load_json` обязана вернуть `Err`, карантин НЕ делать и
    /// файл не тронуть. Зонд на этой машине: такой файл даёт `kind = Uncategorized`,
    /// `raw_os_error = 32` (отказ разделения доступа), а вовсе не `PermissionDenied` — поэтому
    /// правило отнесения построено «InvalidData → порча, ВСЁ остальное → отказ», а не наоборот.
    #[cfg(windows)]
    #[test]
    fn exclusively_locked_file_is_read_failure_not_empty_and_is_left_untouched() {
        use std::os::windows::fs::OpenOptionsExt;

        let tmp = tempfile::tempdir().unwrap();
        let f = tmp.path().join("econometrist.json");
        let original = r#"["переписка клиента"]"#;
        std::fs::write(&f, original).unwrap();

        let held = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .share_mode(0)
            .open(&f)
            .unwrap();

        let outcome: Result<LoadOutcome<Vec<String>>> = load_json(&f);
        assert!(
            outcome.is_err(),
            "занятый монопольно файл — это отказ чтения, а не пустая история: `None` здесь \
             означал бы, что следующая запись затрёт переписку клиента"
        );

        drop(held);
        assert!(f.exists(), "файл обязан остаться на месте — карантин при отказе чтения запрещён");
        assert_eq!(
            std::fs::read_to_string(&f).unwrap(),
            original,
            "содержимое обязано остаться нетронутым"
        );
        assert!(
            quarantine_copies_of(&f).is_empty(),
            "отказ чтения — не порча: карантинных копий появляться не должно"
        );
    }

    /// 🔴 Сторож C1 №3 (негативный контроль): отсутствующий файл — это `Absent`, законная
    /// пустота, и запись создаёт его заново. Без этого случая контракт «отказ прерывает запись»
    /// можно было бы удовлетворить, отказывая всегда.
    #[test]
    fn missing_file_is_absent_and_first_write_creates_it() {
        let tmp = tempfile::tempdir().unwrap();
        let f = tmp.path().join("econometrist.json");

        let outcome: LoadOutcome<Vec<String>> =
            load_json(&f).expect("отсутствие файла не ошибка — это законная пустота");
        assert!(matches!(outcome, LoadOutcome::Absent));

        write_atomic(&f, b"[\"first\"]").unwrap();
        assert_eq!(std::fs::read_to_string(&f).unwrap(), "[\"first\"]");
    }

    /// 🔴 C7: вторая порча не имеет права уничтожить ПЕРВУЮ карантинную копию. Раньше карантин
    /// всегда писался в `<имя>.corrupt.bak`, а `rename` на Windows заменяет цель — переписка из
    /// первой копии исчезала молча.
    #[test]
    fn second_corruption_keeps_the_first_quarantine_copy() {
        let tmp = tempfile::tempdir().unwrap();
        let f = tmp.path().join("econometrist.json");

        std::fs::write(&f, "{первая порча, тут была переписка клиента").unwrap();
        let _: Option<Vec<String>> = read_json_or_quarantine(&f);
        // Отметка времени в имени идёт с миллисекундами — разводим заходы гарантированно.
        std::thread::sleep(std::time::Duration::from_millis(5));
        std::fs::write(&f, "{вторая порча, тут была ДРУГАЯ переписка").unwrap();
        let _: Option<Vec<String>> = read_json_or_quarantine(&f);

        let copies = quarantine_copies_of(&f);
        assert_eq!(
            copies.len(),
            2,
            "обе карантинные копии обязаны лежать рядом: вторая порча не уничтожает первую. \
             Найдено: {copies:?}"
        );
        let contents: Vec<String> = copies
            .iter()
            .map(|p| std::fs::read_to_string(p).unwrap())
            .collect();
        assert!(
            contents.iter().any(|c| c.contains("первая порча")),
            "первая карантинная копия обязана уцелеть: {contents:?}"
        );
        assert!(
            contents.iter().any(|c| c.contains("вторая порча")),
            "вторая карантинная копия обязана появиться: {contents:?}"
        );
    }

    /// 🔴 C6: имя временного файла атомарной записи содержит идентификатор процесса и растёт
    /// монотонно. Фиксированное имя означало, что два процесса, пишущих один файл истории,
    /// пишут в ОДИН временный файл, и `rename` кладёт на место цели смесь двух JSON.
    #[test]
    fn tmp_write_name_is_unique_per_call_and_carries_process_id() {
        let target = Path::new("X:").join("history").join("econometrist.json");

        let first = tmp_write_path(&target);
        let second = tmp_write_path(&target);

        assert_ne!(
            first, second,
            "два вызова обязаны дать РАЗНЫЕ временные файлы — иначе конкурентные записи смешиваются"
        );
        for p in [&first, &second] {
            let name = p.file_name().unwrap().to_string_lossy().to_string();
            assert!(
                name.contains(&std::process::id().to_string()),
                "имя временного файла обязано нести идентификатор процесса: {name}"
            );
            assert!(name.ends_with(".tmp.write"), "хвост имени сохраняется: {name}");
            assert_eq!(
                p.parent(),
                target.parent(),
                "временный файл обязан лежать РЯДОМ с целью — переименование атомарно только \
                 в пределах одного каталога"
            );
        }
    }

    /// 🔴 C5: сброс временного файла на диск ДО переименования. Проверить это поведением
    /// нельзя — разница видна только при обрыве питания, — поэтому сторож читает САМ КОД
    /// `write_atomic` и требует, чтобы `sync_all` стоял в нём ДО `rename`. Комментарии из тела
    /// вырезаются: иначе достаточно было бы упомянуть `sync_all` в комментарии, и сторож
    /// зеленел бы ровно в том случае, ради которого его заводят.
    #[test]
    fn write_atomic_syncs_tmp_file_before_rename() {
        // Файл лежит с CRLF — приводим к одному виду, иначе поиск конца тела ("\n}\n") молча не
        // найдёт ничего и сторож упадёт не по делу.
        let src = include_str!("durable_store.rs").replace("\r\n", "\n");
        let from = src
            .find("pub fn write_atomic")
            .expect("в файле не найдена функция write_atomic — сторож смотрит не туда");
        let body = &src[from..];
        let body = &body[..body.find("\n}\n").expect("не найден конец тела write_atomic")];
        let code: String = body
            .lines()
            .map(str::trim_start)
            .filter(|l| !l.starts_with("//"))
            .collect::<Vec<_>>()
            .join("\n");

        let sync_at = code.find("sync_all").expect(
            "write_atomic обязана сбрасывать временный файл на диск (sync_all) ДО переименования: \
             без этого при обрыве питания метаданные rename ложатся раньше содержимого, и целевой \
             файл существует, но обрезан",
        );
        let rename_at = code
            .find("rename")
            .expect("в write_atomic не найдено переименование — функция переехала, сторож устарел");
        assert!(
            sync_at < rename_at,
            "sync_all обязан стоять ДО rename, иначе он ничего не гарантирует"
        );

        // 🔴 Поправка внешнего аудита к контракту: запасная ветка «удалить цель → переименовать»
        // создавала окно, в котором файла истории на диске НЕТ, а `load_json` в этот миг честно
        // отвечает `Absent` — то есть отделение отказа от пустоты обходилось с фланга. Замена и
        // так атомарна (`MoveFileEx` с `MOVEFILE_REPLACE_EXISTING`), удалять цель незачем.
        assert!(
            !code.contains("remove_file(path)"),
            "write_atomic не имеет права удалять целевой файл: между удалением и переименованием \
             истории клиента на диске не существует, и чтение в этот миг вернёт законную пустоту"
        );
    }

    /// 🔴 Поправка 1 внешнего аудита к контракту (C1): отказ ЧТЕНИЯ на пути записи повторяется —
    /// файл состояния кратко держат индексатор, антивирус, второе окно, и такой отказ проходит за
    /// миллисекунды. Отказывать клиенту в сохранении из-за мгновенного касания — не защита, а её
    /// видимость. Проверяется поведением: файл отпускают из другого потока через 250 мс, и чтение
    /// с повторами обязано его дождаться, тогда как чтение без повторов на том же файле падает.
    #[cfg(windows)]
    #[test]
    fn read_for_update_waits_out_a_transient_lock_while_plain_read_fails() {
        use std::os::windows::fs::OpenOptionsExt;

        let tmp = tempfile::tempdir().unwrap();
        let f = tmp.path().join("usage.json");
        std::fs::write(&f, "[1,2,3]").unwrap();

        let held = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .share_mode(0)
            .open(&f)
            .unwrap();

        let immediate: Result<LoadOutcome<Vec<u32>>> = load_json(&f);
        assert!(
            immediate.is_err(),
            "чтение БЕЗ повторов на занятом файле обязано отказать — иначе тест ниже ничего не \
             доказывает"
        );

        let releaser = std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(250));
            drop(held);
        });

        let outcome: LoadOutcome<Vec<u32>> = load_json_for_update(&f)
            .expect("кратковременный захват файла обязан пережидаться повторами, а не отказом");
        assert_eq!(
            outcome.into_value(),
            Some(vec![1, 2, 3]),
            "дождавшись освобождения, чтение обязано вернуть НАСТОЯЩЕЕ содержимое"
        );
        releaser.join().unwrap();
    }

    /// 🔴 C9: успешный перенос запоминается на процесс — `app_state_dir` вызывается на КАЖДОЕ
    /// сохранение сообщения и каждый инкремент счётчика, и пересканировать legacy-каталог каждый
    /// раз значит держать открытым окно гонки «`dst.exists()` ↔ `rename`».
    #[test]
    fn successful_migration_is_remembered_and_not_repeated_in_process() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let dir = tmp.path().join("state-remembered");
        write_file(&legacy, "a.json", "A");

        let calls = std::sync::atomic::AtomicUsize::new(0);
        let counting = |s: &Path, d: &Path| -> std::io::Result<u64> {
            calls.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            std::fs::copy(s, d)
        };

        migrate_once(&dir, &legacy, "test", &counting).unwrap();
        assert_eq!(calls.load(std::sync::atomic::Ordering::Relaxed), 1);

        // Убираем ДИСКОВЫЙ признак «перенос выполнен» и сам перенесённый файл: если бы кэша не
        // было, следующий вызов пересканировал бы legacy и скопировал заново.
        std::fs::remove_file(dir.join(MIGRATION_MARKER)).unwrap();
        std::fs::remove_file(dir.join("a.json")).unwrap();

        migrate_once(&dir, &legacy, "test", &counting).unwrap();
        assert_eq!(
            calls.load(std::sync::atomic::Ordering::Relaxed),
            1,
            "перенос обязан выполняться не чаще одного УСПЕШНОГО раза на каталог в пределах \
             процесса — иначе каждое сохранение сообщения снова сканирует legacy"
        );
    }

    /// 🔴 C9, правка к самому эталону: кэшируется факт переноса, но НЕ существование каталога.
    /// Иначе удаление каталога во время работы (чистильщик, антивирус, ручная уборка) роняло бы
    /// следующую запись «путь не найден», тогда как раньше каталог восстанавливался сам.
    #[test]
    fn state_dir_is_recreated_even_after_migration_was_remembered() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let dir = tmp.path().join("state-recreated");
        write_file(&legacy, "a.json", "A");

        prepare_state_dir(&dir, &legacy, "history", real_copy).unwrap();
        assert!(dir.exists(), "первый вызов обязан создать каталог состояния");

        std::fs::remove_dir_all(&dir).unwrap();

        prepare_state_dir(&dir, &legacy, "history", real_copy)
            .expect("подготовка каталога обязана пережить его удаление во время работы");
        assert!(
            dir.exists(),
            "каталог обязан быть восстановлен на КАЖДЫЙ вызов — иначе следующая запись истории \
             падает «путь не найден», а клиент теряет сообщение"
        );
    }

    /// 🔴 Обратная сторона того же контракта: запоминается ТОЛЬКО успех. Неудачный перенос
    /// возвращает ошибку и обязан пробоваться снова — иначе один сбой навсегда отрезал бы
    /// данные клиента в legacy-каталоге.
    #[test]
    fn failed_migration_is_not_remembered_and_retries_next_call() {
        let tmp = tempfile::tempdir().unwrap();
        let legacy = tmp.path().join("legacy");
        let dir = tmp.path().join("state-retried");
        write_file(&legacy, "a.json", "A");

        let failing_copier = |_: &Path, _: &Path| -> std::io::Result<u64> {
            Err(std::io::Error::new(
                std::io::ErrorKind::PermissionDenied,
                "смоделированный отказ",
            ))
        };
        assert!(
            migrate_once(&dir, &legacy, "test", failing_copier).is_err(),
            "неполный перенос обязан вернуть ошибку"
        );

        migrate_once(&dir, &legacy, "test", real_copy)
            .expect("после устранения причины перенос обязан пробоваться СНОВА, а не считаться выполненным");
        assert_eq!(
            std::fs::read_to_string(dir.join("a.json")).unwrap(),
            "A",
            "повторный вызов обязан докопировать данные клиента"
        );
    }

    /// 🔴 C10: расхождение базы состояния с каталогом, который отдаёт Tauri, обязано быть видно,
    /// а разница в регистре и в виде разделителя — НЕ обязана порождать ложное предупреждение
    /// (путь профиля приходит в разном регистре из разных источников, и ложный warn на каждом
    /// запуске обесценил бы сторож).
    #[cfg(windows)]
    #[test]
    fn base_mismatch_is_reported_and_case_or_slash_differences_are_not() {
        let actual = Path::new("C:\\Users\\x\\AppData\\Local\\com.aurora.econometrica");
        let same_written_differently =
            Path::new("c:/users/x/appdata/local/com.aurora.econometrica/");
        assert!(
            describe_base_mismatch(actual, same_written_differently).is_none(),
            "один и тот же путь, записанный иначе, расхождением не является"
        );

        let fallback = Path::new("C:\\Users\\x\\AppData\\Local\\aurora-econometrica-gui");
        let msg = describe_base_mismatch(actual, fallback)
            .expect("уход состояния в запасной каталог по имени пакета обязан быть замечен");
        assert!(
            msg.contains("aurora-econometrica-gui") && msg.contains("com.aurora.econometrica"),
            "в предупреждении обязаны быть ОБА пути, иначе по журналу нечего чинить: {msg}"
        );
    }
}
