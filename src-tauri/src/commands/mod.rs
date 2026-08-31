pub mod brand;
pub mod cabinet;
pub mod campaign;
pub mod content_pack;
pub mod claude;
pub mod diagnostics;
pub mod data_migration;
pub mod content_updater;
pub mod econometrica;
/// Выбор режима исполнения советника во время работы (ADR-049): свой Claude Code
/// клиента или шлюз Авроры. Собирается ВСЕГДА — в сборке без облачного пути модуль
/// честно отвечает, что облачного режима нет, вместо того чтобы исчезнуть и заставить
/// вызывающий код снова ветвиться условной компиляцией.
pub mod execution_mode;
pub mod feedback;
#[cfg(feature = "thin")]
pub mod gateway_executor;
pub mod license;
pub mod mqs_tiers;
pub mod online_auth;
pub mod parser;
pub mod pptx_processor;
pub mod project;
pub mod rag_client;
pub mod report;
pub mod updater;
pub mod user_config;
pub mod vault;

use std::path::{Path, PathBuf};

/// Свободное имя файла рядом с `path` — CPD-70: готовый документ клиента (docx/xlsx/md-отчёт)
/// не должен молча затираться повторным экспортом в тот же каталог под тем же именем.
/// Свободное имя возвращается как есть. Занятое — получает суффикс-счётчик перед
/// расширением: `отчёт.docx` занято → `отчёт (2).docx` → `отчёт (3).docx` и так далее, пока
/// не найдётся свободное. Файл на диск не создаётся — только вычисляется путь, запись
/// остаётся на вызывающей стороне (TOCTOU-окно между вызовом и записью неизбежно при таком
/// API, но устраняет РЕГУЛЯРНЫЙ случай — повторный ручной экспорт, а не гонку потоков).
pub fn unique_export_path(path: &Path) -> PathBuf {
    if !path.exists() {
        return path.to_path_buf();
    }
    let mut n: u32 = 2;
    loop {
        let candidate = numbered_variant(path, n);
        if !candidate.exists() {
            return candidate;
        }
        n += 1;
    }
}

/// Тот же путь с номером перед расширением: `отчёт.docx` + 2 → `отчёт (2).docx`.
///
/// Вынесено из `unique_export_path` ради ЕДИНОГО правила именования: доставка выгрузок
/// (`session/manager.rs`) обязана узнавать свои же прежние копии рядом с файлом клиента, а
/// собственная сборка имени там означала бы вторую копию правила — расходятся такие копии
/// молча (CPD-71).
pub(crate) fn numbered_variant(path: &Path, n: u32) -> PathBuf {
    let parent = path.parent().unwrap_or_else(|| Path::new(""));
    let stem = path.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
    let ext = path.extension().map(|e| e.to_string_lossy().to_string());
    let name = match &ext {
        Some(ext) => format!("{stem} ({n}).{ext}"),
        None => format!("{stem} ({n})"),
    };
    parent.join(name)
}

/// Куда лёг только что собранный файл выдачи — CPD-70.
#[derive(Debug, PartialEq, Eq)]
pub enum PlacedExport {
    /// Прежнего файла не было — новый занял своё имя.
    Created,
    /// Прежний файл байт в байт совпал с новым — он НЕ тронут, время изменения прежнее.
    Unchanged,
    /// Прежний файл отличается — он оставлен как есть, новый лёг рядом под этим путём.
    SavedAside(PathBuf),
}

/// Положить собранный файл в папку выдачи, не потеряв прежний — CPD-70.
///
/// 🔴 Почему не хватает одного `unique_export_path`. Он умеет ровно уникализацию имени:
/// путь занят — приписать `(2)`. Генераторы выдачи (`_commented.pptx`, `_commentary.docx`)
/// дают имя, вычисленное из имени входного файла, и повторный прогон над той же
/// презентацией пишет ПО ТОМУ ЖЕ пути. Голая уникализация закрыла бы потерю, но платой
/// стала бы гряда `имя (2)`, `имя (3)`, `имя (4)` при каждом прогоне — в том числе когда
/// человек ничего не менял и файл вышел прежним. Поэтому решение принимается по
/// СОДЕРЖИМОМУ, а не по факту занятости имени.
///
/// Сборка идёт в служебный каталог (`preprocessed`), сюда приходит готовый файл:
/// содержимое нельзя сравнить до записи, потому что оно и получается записью.
///
/// Три исхода:
/// * приёмника нет — файл занимает своё имя (`Created`);
/// * приёмник байт в байт такой же — новый файл удаляется, прежний НЕ трогается вовсе,
///   и время изменения у него остаётся прежним (`Unchanged`);
/// * приёмник отличается — прежний остаётся нетронутым, новый ложится рядом под
///   свободным именем от `unique_export_path` (`SavedAside`).
pub fn place_generated_export(produced: &Path, dest: &Path) -> std::io::Result<PlacedExport> {
    if !dest.exists() {
        move_file(produced, dest)?;
        return Ok(PlacedExport::Created);
    }
    if same_bytes(produced, dest)? {
        // Приёмник не открывается на запись вовсе: единственный способ гарантировать,
        // что время изменения прежнего файла не сдвинется.
        std::fs::remove_file(produced)?;
        return Ok(PlacedExport::Unchanged);
    }
    let aside = unique_export_path(dest);
    move_file(produced, &aside)?;
    Ok(PlacedExport::SavedAside(aside))
}

/// Разложить собранные файлы по папке результатов — CPD-70. Пары «собранный файл →
/// его место в папке результатов». Возвращает ИМЕНА тех, что пришлось сохранить рядом
/// под другим именем: их обязан увидеть человек, журнала здесь мало.
///
/// Файл, которого нет, пропускается молча: значит, генератор до него не дошёл, и об этом
/// отказе уже сказано там, где он произошёл, — второе сообщение о том же было бы шумом.
pub fn place_generated_exports(pairs: &[(PathBuf, PathBuf)]) -> Vec<String> {
    let mut saved_aside = Vec::new();
    for (produced, dest) in pairs {
        if !produced.exists() {
            continue;
        }
        match place_generated_export(produced, dest) {
            Ok(PlacedExport::Created) | Ok(PlacedExport::Unchanged) => {}
            Ok(PlacedExport::SavedAside(path)) => {
                log::info!(
                    "CPD-70: прежний {} отличается от нового и оставлен нетронутым, новый сохранён как {}",
                    dest.display(),
                    path.display()
                );
                if let Some(name) = path.file_name() {
                    saved_aside.push(name.to_string_lossy().to_string());
                }
            }
            Err(e) => log::warn!(
                "Не удалось положить файл в папку результатов ({}): {e}",
                dest.display()
            ),
        }
    }
    saved_aside
}

/// Что показать человеку, когда прежний файл сохранён, а новый лёг рядом.
///
/// Один источник текста на все три точки выдачи: разъехавшиеся формулировки об одном и
/// том же событии — самостоятельный дефект, человек читает их как разные события.
pub fn saved_aside_notice(names: &[String]) -> String {
    format!(
        "В папке результатов уже лежали файлы с такими же именами, и содержимое у них другое. \
         Прежние файлы оставлены без изменений, новые сохранены рядом: {}. \
         Сверьте оба варианта и удалите лишний сами – программа ваши файлы не удаляет.",
        names.join(", ")
    )
}

/// Перенести файл. `rename` внутри одного тома дёшев и атомарен; на отказ (иной том,
/// приёмник занят) — копирование с последующим удалением источника.
fn move_file(from: &Path, to: &Path) -> std::io::Result<()> {
    match std::fs::rename(from, to) {
        Ok(()) => Ok(()),
        Err(_) => {
            std::fs::copy(from, to)?;
            // Источник — служебная копия в каталоге сборки; неудача удаления оставляет
            // мусор, но не теряет результат, поэтому отказом не считается.
            let _ = std::fs::remove_file(from);
            Ok(())
        }
    }
}

/// Совпадают ли файлы побайтно. Сначала длина (дёшево и отсекает почти всё),
/// затем потоковое сравнение — файлы выдачи бывают в десятки мегабайт, читать их
/// в память целиком незачем.
pub(crate) fn same_bytes(a: &Path, b: &Path) -> std::io::Result<bool> {
    if std::fs::metadata(a)?.len() != std::fs::metadata(b)?.len() {
        return Ok(false);
    }
    let mut ra = std::io::BufReader::new(std::fs::File::open(a)?);
    let mut rb = std::io::BufReader::new(std::fs::File::open(b)?);
    let mut ba = [0u8; 64 * 1024];
    let mut bb = [0u8; 64 * 1024];
    loop {
        let na = read_full(&mut ra, &mut ba)?;
        let nb = read_full(&mut rb, &mut bb)?;
        if na != nb {
            return Ok(false);
        }
        if na == 0 {
            return Ok(true);
        }
        if ba[..na] != bb[..nb] {
            return Ok(false);
        }
    }
}

/// Набрать полный буфер, не полагаясь на то, что одно чтение вернёт его целиком:
/// короткое чтение посреди файла законно, и наивное сравнение приняло бы за
/// расхождение простой сдвиг границ чтения.
fn read_full<R: std::io::Read>(r: &mut R, buf: &mut [u8]) -> std::io::Result<usize> {
    let mut filled = 0;
    while filled < buf.len() {
        match r.read(&mut buf[filled..]) {
            Ok(0) => break,
            Ok(n) => filled += n,
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }
    Ok(filled)
}

#[cfg(test)]
mod unique_export_path_tests {
    use super::unique_export_path;
    use std::fs;

    #[test]
    fn free_name_returned_as_is() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("отчёт.docx");
        assert_eq!(unique_export_path(&path), path);
    }

    #[test]
    fn one_collision_gets_counter_two() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("отчёт.docx");
        fs::write(&path, b"existing").unwrap();
        let expected = tmp.path().join("отчёт (2).docx");
        assert_eq!(unique_export_path(&path), expected);
    }

    #[test]
    fn two_collisions_get_counter_three() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("отчёт.docx");
        fs::write(&path, b"existing").unwrap();
        fs::write(tmp.path().join("отчёт (2).docx"), b"existing2").unwrap();
        let expected = tmp.path().join("отчёт (3).docx");
        assert_eq!(unique_export_path(&path), expected);
    }
}

/// Структурный сторож CPD-70: генераторы выдачи не пишут прямо в папку результатов.
///
/// Поведенческие проверки ниже держат саму функцию размещения, но не её ПРИМЕНЕНИЕ:
/// вернуть `exports_dir.join(...)` в качестве приёмника генератора можно одной правкой,
/// и все они останутся зелёными (урок Ф-04 — вынесенная функция покрыта, а её вызов нет).
/// Живьём эти места вызовом не проверить: они внутри `send_message`, которому нужен
/// живой `AppHandle`.
///
/// 🔴 Разбор идёт по СУТИ вызова — «последний аргумент генератора», а не по имени
/// переменной: имя можно поменять, роль нельзя. Переводы строк нормализуются до
/// разбора, и пустой результат разбора считается ОТКАЗОМ, а не чистотой (CPD-89).
#[cfg(test)]
mod cpd70_generators_write_to_staging_guard {
    /// Генераторы, у которых приёмник — последний аргумент.
    const GENERATORS: &[&str] = &[
        "pptx_processor::inject_notes(",
        "pptx_processor::generate_docx(",
        "pptx_processor::generate_docx_with_synthesis(",
        "pptx_processor::inject_summary_slides(",
    ];

    /// Последние аргументы всех вызовов генераторов в `lib.rs`.
    fn destination_arguments() -> Vec<String> {
        let src = include_str!("../lib.rs").replace("\r\n", "\n");
        let mut found = Vec::new();
        for name in GENERATORS {
            let mut from = 0;
            while let Some(at) = src[from..].find(name) {
                let open = from + at + name.len();
                let close = src[open..]
                    .find(')')
                    .unwrap_or_else(|| panic!("вызов {name} без закрывающей скобки — разбор сломан"));
                let args = &src[open..open + close];
                let last = args
                    .rsplit(',')
                    .next()
                    .unwrap_or_default()
                    .trim()
                    .to_string();
                found.push(last);
                from = open + close;
            }
        }
        found
    }

    #[test]
    fn every_generator_writes_into_the_staging_directory() {
        let destinations = destination_arguments();
        assert!(
            destinations.len() >= 6,
            "разбор нашёл {} приёмников вместо шести и более — сторож ослеп, а не код очистился: {destinations:?}",
            destinations.len()
        );
        let straight_to_exports: Vec<&String> = destinations
            .iter()
            .filter(|arg| !arg.starts_with("&staged_"))
            .collect();
        assert!(
            straight_to_exports.is_empty(),
            "генератор пишет мимо служебного каталога прямо в папку результатов — это регресс CPD-70, \
             готовый документ клиента будет затёрт: {straight_to_exports:?}"
        );
    }

    /// Собрать в служебный каталог мало — надо ещё положить в папку результатов.
    /// Без этой половины выдача просто перестала бы доходить до человека.
    #[test]
    fn every_generating_site_places_what_it_built() {
        let src = include_str!("../lib.rs").replace("\r\n", "\n");
        let places = src.matches("place_generated_exports(").count();
        assert_eq!(
            places, 3,
            "точек выдачи три (конвейер, авто-постобработка, отдельная команда), \
             а размещение вызывается {places} раз"
        );
    }
}

/// CPD-70: три исхода размещения собранного файла в папке выдачи.
///
/// 🔴 Проверки идут на НАСТОЯЩЕЙ файловой системе, а не на подменённом слое: предмет
/// проверки — сохранность файла клиента и время его изменения, то есть ровно то, чего
/// у подделки нет. Ось мутации для всех трёх: заменить тело `place_generated_export`
/// на безусловное `std::fs::rename(produced, dest)` — поведение ДО правки; краснеют
/// второй и третий тесты, первый остаётся зелёным (он и не про потерю).
#[cfg(test)]
mod place_generated_export_tests {
    use super::{place_generated_export, PlacedExport};
    use std::fs;
    use std::path::{Path, PathBuf};

    /// Пара «служебный каталог сборки» + «папка выдачи» — как в бою.
    fn staged_and_exports(root: &Path) -> (PathBuf, PathBuf) {
        let staging = root.join("preprocessed");
        let exports = root.join("exports");
        fs::create_dir_all(&staging).unwrap();
        fs::create_dir_all(&exports).unwrap();
        (staging, exports)
    }

    fn mtime(path: &Path) -> std::time::SystemTime {
        fs::metadata(path).unwrap().modified().unwrap()
    }

    #[test]
    fn missing_destination_gets_the_file() {
        let tmp = tempfile::tempdir().unwrap();
        let (staging, exports) = staged_and_exports(tmp.path());
        let produced = staging.join("Презентация_commented.pptx");
        let dest = exports.join("Презентация_commented.pptx");
        fs::write(&produced, b"first run").unwrap();

        let placed = place_generated_export(&produced, &dest).unwrap();

        assert_eq!(placed, PlacedExport::Created);
        assert_eq!(fs::read(&dest).unwrap(), b"first run");
        assert!(!produced.exists(), "служебная копия не остаётся в каталоге сборки");
    }

    #[test]
    fn identical_content_leaves_the_previous_file_untouched() {
        let tmp = tempfile::tempdir().unwrap();
        let (staging, exports) = staged_and_exports(tmp.path());
        let produced = staging.join("Презентация_commented.pptx");
        let dest = exports.join("Презентация_commented.pptx");
        fs::write(&dest, b"same bytes").unwrap();
        let before = mtime(&dest);
        // Гарантия, что совпадение времени — не следствие слишком грубых часов файловой
        // системы: без паузы перезапись могла бы попасть в ту же отметку и тест не
        // отличил бы «не тронут» от «переписан».
        std::thread::sleep(std::time::Duration::from_millis(1100));
        fs::write(&produced, b"same bytes").unwrap();

        let placed = place_generated_export(&produced, &dest).unwrap();

        assert_eq!(placed, PlacedExport::Unchanged);
        assert_eq!(mtime(&dest), before, "прежний файл переписан, хотя содержимое то же");
        assert_eq!(fs::read(&dest).unwrap(), b"same bytes");
        assert!(!produced.exists());
        let names: Vec<String> = fs::read_dir(&exports).unwrap()
            .map(|e| e.unwrap().file_name().to_string_lossy().to_string())
            .collect();
        assert_eq!(names.len(), 1, "лишняя копия при совпадающем содержимом: {names:?}");
    }

    #[test]
    fn different_content_keeps_the_previous_file_and_saves_aside() {
        let tmp = tempfile::tempdir().unwrap();
        let (staging, exports) = staged_and_exports(tmp.path());
        let produced = staging.join("Презентация_commented.pptx");
        let dest = exports.join("Презентация_commented.pptx");
        fs::write(&dest, b"the deliverable the client already has").unwrap();
        let before = mtime(&dest);
        std::thread::sleep(std::time::Duration::from_millis(1100));
        fs::write(&produced, b"a different, newer deliverable").unwrap();

        let placed = place_generated_export(&produced, &dest).unwrap();

        let aside = exports.join("Презентация_commented (2).pptx");
        assert_eq!(placed, PlacedExport::SavedAside(aside.clone()));
        assert_eq!(
            fs::read(&dest).unwrap(),
            b"the deliverable the client already has",
            "прежний файл клиента изменился — это и есть потеря данных из CPD-70"
        );
        assert_eq!(mtime(&dest), before, "прежний файл тронут");
        assert_eq!(fs::read(&aside).unwrap(), b"a different, newer deliverable");
        assert!(!produced.exists());
    }

    /// Расхождение при одинаковой длине: сравнение по размеру такой случай пропустит,
    /// а именно он и типичен для повторного прогона над теми же данными.
    #[test]
    fn same_length_but_different_bytes_is_a_divergence() {
        let tmp = tempfile::tempdir().unwrap();
        let (staging, exports) = staged_and_exports(tmp.path());
        let produced = staging.join("отчёт.docx");
        let dest = exports.join("отчёт.docx");
        fs::write(&dest, b"budget 100000").unwrap();
        fs::write(&produced, b"budget 999999").unwrap();

        let placed = place_generated_export(&produced, &dest).unwrap();

        assert_eq!(placed, PlacedExport::SavedAside(exports.join("отчёт (2).docx")));
        assert_eq!(fs::read(&dest).unwrap(), b"budget 100000");
    }

    /// Файл крупнее буфера сравнения (64 КБ): расхождение в самом хвосте обязано
    /// находиться — иначе сравнение молча закончилось бы на первом куске.
    #[test]
    fn divergence_beyond_the_compare_buffer_is_found() {
        let tmp = tempfile::tempdir().unwrap();
        let (staging, exports) = staged_and_exports(tmp.path());
        let produced = staging.join("большой.pptx");
        let dest = exports.join("большой.pptx");
        let mut old = vec![7u8; 200 * 1024];
        let mut new = old.clone();
        *new.last_mut().unwrap() = 9;
        fs::write(&dest, &old).unwrap();
        fs::write(&produced, &new).unwrap();
        old.truncate(0);

        let placed = place_generated_export(&produced, &dest).unwrap();

        assert!(matches!(placed, PlacedExport::SavedAside(_)));
        assert_eq!(fs::read(&dest).unwrap().last(), Some(&7u8), "прежний файл затёрт");
    }
}
