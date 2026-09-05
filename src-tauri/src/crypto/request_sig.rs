//! Подпись ИСХОДЯЩЕГО запроса протоколом `AURORA-REQ-v1` (CPD-141, ступень 2).
//!
//! Не путать с соседним `auth_sig.rs`: там проверяется подпись ОТВЕТА сервера (`AUTHSIG-v1`),
//! здесь клиент подписывает СВОЙ запрос. Разные протоколы, разные ключи, разные направления.
//!
//! # Зачем
//!
//! Сегодня дверь входа открывается знанием одного отпечатка машины (CPD-141): отпечаток
//! невращаем и однажды утёк в журнал. Подпись добавляет второй множитель — закрытый ключ,
//! который лежит только на этой машине и в журнал не попадает никогда. Сервер уже умеет
//! проверять эту подпись (ступень 1 в бою с 31.08); здесь появляется вторая половина.
//!
//! 🔴 **Отказа эта ступень не создаёт.** Сервер принимает неподписанный запрос как прежде, а
//! негодную подпись пишет полем в журнал, а не отвечает отказом. Клиент, у которого ключ не
//! завёлся, обязан продолжить работу без подписи — отказ невиновному дороже пропуска виноватого.
//!
//! # Каноническая строка — третья реализация одной и той же
//!
//! Семь полей, склейка ОДНИМ переводом строки, завершающего перевода НЕТ, кодировка UTF-8:
//!
//! ```text
//! AURORA-REQ-v1\n{МЕТОД}\n{ПУТЬ}\n{МЕТКА}\n{ОДНОРАЗОВОЕ}\n{СВЁРТКА_ТЕЛА}\n{ОТПЕЧАТОК}
//! ```
//!
//! Обязана совпадать байт в байт с двумя работающими реализациями: Rust-клиент шлюза
//! (`aurora_gateway/src/cloud/protocol.rs`) и проверка на сервере
//! (`supabase/functions/*/index.ts`, встроенный модуль). Сверяется 75 эталонными векторами
//! (`aurora-meta/Projects/CPD141_step1/vectors/vectors.json`) — именно они, а не общий крейт,
//! удерживают три копии в согласии.
//!
//! # 🔴 Два отличия от шлюза, из-за которых дословный перенос сломал бы подпись
//!
//! 1. **Приставка `/functions/v1` в подпись НЕ входит.** Шлюз подписывает путь так, как тот
//!    записан в адресе (`parsed.path()`), и для узла Б это верно: там приставка `/cloud`
//!    доезжает до сервера. Здесь посредник Supabase срезает `/functions/v1` ДО функции —
//!    сервер видит `/auth`, а не `/functions/v1/auth`. Замерено боем 30.08, из кода и
//!    документации не выводится. Подпишем как шлюз — не сойдётся у всех клиентов разом.
//! 2. **Процентные тройки — ВЕРХНИМ регистром.** Посредник приводит `%d0%be` к `%D0%BE` до
//!    того, как запрос дойдёт до функции. Отменить это нельзя, значит клиент обязан кодировать
//!    верхним регистром сам, иначе подпишет одну строку, а проверена будет другая.

use base64::{engine::general_purpose::STANDARD, Engine};
use ed25519_dalek::{Signer, SigningKey};
use sha2::{Digest, Sha256};

/// Приставка канонической строки. Меняется только вместе с сервером.
pub const REQUEST_PREFIX: &str = "AURORA-REQ-v1";

/// Приставка адреса, которую посредник Supabase срезает до функции.
/// В подписываемую строку не подставляется никогда — см. отличие №1 в шапке модуля.
pub const EDGE_PREFIX: &str = "/functions/v1";

/// Имена заголовков протокола. Контракт с сервером: имена сверены с `HEADER` в
/// `supabase/functions/content/index.ts` и с клиентом шлюза.
pub const HEADER_DEVICE: &str = "x-aurora-device";
pub const HEADER_TIMESTAMP: &str = "x-aurora-timestamp";
pub const HEADER_NONCE: &str = "x-aurora-nonce";
pub const HEADER_SIGNATURE: &str = "x-aurora-signature";

/// Свёртка тела запроса — SHA-256, шестнадцатеричными строчными.
///
/// 🔴 Считать ОБЯЗАТЕЛЬНО от тех самых байт, которые уйдут в сеть. Пустое тело хешируется
/// как пустой вход (это не «пустое поле»): сервер поступает так же, и расхождение здесь даёт
/// негодную подпись при внешне верном коде.
pub fn body_sha256_hex(body: &[u8]) -> String {
    let digest = Sha256::digest(body);
    let mut out = String::with_capacity(64);
    for byte in digest {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

/// Привести процентные тройки к ВЕРХНЕМУ регистру — форма, в которой запрос доедет до функции.
///
/// Трогает ровно тройки `%XY`, остальной путь остаётся как есть: приводить к верхнему регистру
/// путь целиком нельзя, имена файлов и кабинетов регистрозависимы.
pub fn percent_triples_to_upper(path: &str) -> String {
    let bytes = path.as_bytes();
    let mut out = String::with_capacity(path.len());
    let mut i = 0usize;
    while i < bytes.len() {
        let is_triple = bytes[i] == b'%'
            && i + 2 < bytes.len()
            && bytes[i + 1].is_ascii_hexdigit()
            && bytes[i + 2].is_ascii_hexdigit();
        if is_triple {
            out.push('%');
            out.push(bytes[i + 1].to_ascii_uppercase() as char);
            out.push(bytes[i + 2].to_ascii_uppercase() as char);
            i += 3;
        } else {
            // Идём по байтам, а собираем строку — поэтому переносим символ целиком,
            // иначе многобайтовый символ распался бы на части.
            let ch_len = utf8_char_len(bytes[i]);
            let end = (i + ch_len).min(bytes.len());
            out.push_str(&path[i..end]);
            i = end;
        }
    }
    out
}

fn utf8_char_len(first: u8) -> usize {
    match first {
        0x00..=0x7F => 1,
        0xC0..=0xDF => 2,
        0xE0..=0xEF => 3,
        0xF0..=0xF7 => 4,
        _ => 1,
    }
}

/// Путь для подписи из полного адреса — ровно то, что увидит функция Supabase.
///
/// Отрезает схему и домен, снимает приставку `/functions/v1`, приводит процентные тройки к
/// верхнему регистру. Возвращает `None`, если в адресе нет пути: подписывать пустоту нельзя,
/// вызывающий в этом случае просто не подписывает запрос.
pub fn signed_path_for_edge(url: &str) -> Option<String> {
    // Якорь в сеть не уходит НИКОГДА — сервер его не увидит. Подписать путь вместе с якорем
    // значит подписать не то, что будет проверено: подпись не сойдётся на каждом таком запросе.
    // Найдено внешним аудитом 05.09.
    let url = match url.find('#') {
        Some(pos) => &url[..pos],
        None => url,
    };
    let after_scheme = match url.find("://") {
        Some(pos) => &url[pos + 3..],
        // Некоторые вызывающие уже дают относительную цель — она годится как есть.
        None => {
            return if url.starts_with('/') {
                Some(percent_triples_to_upper(strip_edge_prefix(url)))
            } else {
                None
            }
        }
    };
    // Пути в адресе может не быть (`https://домен` или `https://домен?x=1`), но сервер всё равно
    // увидит `/` — и подпишет его. Без этой ветви клиент молча не подписывал бы такой запрос.
    // Найдено внешним аудитом 05.09.
    let path_with_query = match after_scheme.find('/') {
        Some(slash) => &after_scheme[slash..],
        None => match after_scheme.find('?') {
            Some(q) => return Some(percent_triples_to_upper(&format!("/{}", &after_scheme[q..]))),
            None => "/",
        },
    };
    Some(percent_triples_to_upper(strip_edge_prefix(path_with_query)))
}

/// Годится ли поле для канонической строки: перевод строки внутри поля сдвинул бы разбор на
/// стороне сервера — он получил бы восемь полей вместо семи и сверял бы не то.
///
/// Через сеть такое недостижимо (транспорт отвергает голый перевод строки в цели запроса), но
/// путь может собираться из имени файла или кабинета, и тогда расхождение возникло бы тихо, без
/// отказа и без следа. Найдено внешним аудитом 05.09.
fn поле_годно(значение: &str) -> bool {
    !значение.contains('\n') && !значение.contains('\r')
}

/// Снять приставку посредника. `/functions/v1/auth` → `/auth`.
///
/// Без пути после приставки (сам `/functions/v1`) вернуть `/` — иначе строка осталась бы
/// пустой и подпись считалась бы от «ничего».
fn strip_edge_prefix(path: &str) -> &str {
    match path.strip_prefix(EDGE_PREFIX) {
        Some("") => "/",
        Some(rest) if rest.starts_with('/') => rest,
        // Совпало начало, но дальше не косая черта (`/functions/v1x`) — это другой путь,
        // резать нельзя.
        Some(_) => path,
        None => path,
    }
}

/// Собрать каноническую строку запроса. Семь полей, один перевод строки между ними,
/// завершающего перевода нет.
///
/// Метод поднимается в верхний регистр ПО-ASCII нарочно: так делают обе соседние реализации,
/// и локальные правила регистра здесь были бы расхождением.
pub fn build_request_payload(
    method: &str,
    path: &str,
    timestamp: &str,
    nonce: &str,
    body_sha256_hex: &str,
    fingerprint_hash: &str,
) -> String {
    debug_assert!(
        [method, path, timestamp, nonce, body_sha256_hex, fingerprint_hash]
            .iter()
            .all(|поле| поле_годно(поле)),
        "перевод строки внутри поля сдвинул бы разбор на сервере — см. `поле_годно`"
    );
    format!(
        "{}\n{}\n{}\n{}\n{}\n{}\n{}",
        REQUEST_PREFIX,
        method.to_ascii_uppercase(),
        path,
        timestamp,
        nonce,
        body_sha256_hex,
        fingerprint_hash
    )
}

/// Ключ устройства: закрытый ключ Ed25519, живущий на этой машине.
///
/// 🔴 Создаётся ОДИН раз и хранится. Новый ключ при каждом запуске — ровно то, от чего защита
/// и стоит: сервер закрепляет ключ за парой «лицензия и машина», и клиент получил бы законный
/// отказ «запрос пришёл с другого устройства». На этом уже споткнулся зонд приёмки шлюза.
///
/// **Осознанный предел, названный честно.** Ключ лежит файлом рядом с настройками программы,
/// а не в хранилище ключей операционной системы. Это защищает от чужого пользователя на той же
/// машине, но не от вредоносной программы, запущенной от имени самого пользователя. Усиление
/// требует разных механизмов на каждой платформе — отдельная работа; до тех пор предел записан
/// здесь, а не подразумевается.
pub struct DeviceKey {
    signing: SigningKey,
}

/// Имя файла с ключом устройства.
pub const DEVICE_KEY_FILE: &str = "device.key";

const SEED_LEN: usize = 32;

impl DeviceKey {
    /// Взять ключ из каталога, создав при первом обращении.
    ///
    /// Возвращает один и тот же ключ при каждом вызове. Повреждённый файл (не 32 байта) —
    /// это НЕ повод молча завести новый: молчаливая замена выглядела бы как «подпись вдруг
    /// перестала совпадать» и разбиралась бы неделями. Возвращаем ошибку, вызывающий работает
    /// без подписи и пишет это в журнал.
    pub fn load_or_create(dir: &std::path::Path) -> Result<Self, String> {
        let path = dir.join(DEVICE_KEY_FILE);
        if path.exists() {
            let bytes = std::fs::read(&path).map_err(|e| format!("ключ устройства не читается: {e}"))?;
            let seed: [u8; SEED_LEN] = bytes
                .as_slice()
                .try_into()
                .map_err(|_| format!("ключ устройства повреждён: длина {} вместо {SEED_LEN}", bytes.len()))?;
            return Ok(Self { signing: SigningKey::from_bytes(&seed) });
        }
        std::fs::create_dir_all(dir).map_err(|e| format!("каталог для ключа не создан: {e}"))?;
        let mut seed = [0u8; SEED_LEN];
        getrandom_seed(&mut seed)?;
        write_private(&path, &seed)?;
        Ok(Self { signing: SigningKey::from_bytes(&seed) })
    }

    /// Открытый ключ в base64 стандартного алфавита с набивкой — ровно в том виде, в каком его
    /// ждёт таблица закрепления на сервере (проверка формата `^[A-Za-z0-9+/]{43}=$`).
    pub fn public_b64(&self) -> String {
        STANDARD.encode(self.signing.verifying_key().to_bytes())
    }

    /// Подписать каноническую строку. base64 стандартного алфавита с набивкой: сервер отвергает
    /// base64url и отсутствие набивки на разборе, а не на сверке.
    pub fn sign(&self, payload: &str) -> String {
        STANDARD.encode(self.signing.sign(payload.as_bytes()).to_bytes())
    }
}

/// Записать закрытый ключ файлом, доступным только владельцу.
///
/// На Windows права файла не выставляются: там это делается списками доступа, а не режимом, и
/// половинчатая попытка создала бы ложное чувство защиты. Предел назван в шапке `DeviceKey`.
fn write_private(path: &std::path::Path, bytes: &[u8]) -> Result<(), String> {
    std::fs::write(path, bytes).map_err(|e| format!("ключ устройства не записан: {e}"))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600));
    }
    Ok(())
}

/// Случайное зерно ключа из системного источника.
fn getrandom_seed(out: &mut [u8; SEED_LEN]) -> Result<(), String> {
    use rand::RngCore;
    rand::rngs::OsRng
        .try_fill_bytes(out)
        .map_err(|e| format!("системный источник случайности недоступен: {e}"))
}

/// Метка времени — секунды эпохи, десятичной строкой.
pub fn now_unix_string() -> String {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs().to_string())
        .unwrap_or_else(|_| "0".to_string())
}

/// Одноразовое число — 32 шестнадцатеричных знака из системного источника случайности.
pub fn new_nonce() -> String {
    use rand::RngCore;
    let mut bytes = [0u8; 16];
    if rand::rngs::OsRng.try_fill_bytes(&mut bytes).is_err() {
        // Источник случайности недоступен — годного одноразового числа не собрать.
        // Пустая строка заставит вызывающего не подписывать вовсе, вместо предсказуемого
        // значения, которое давало бы ложное чувство защиты от повтора.
        return String::new();
    }
    let mut out = String::with_capacity(32);
    for byte in bytes {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn каноническая_строка_семь_полей_без_завершающего_перевода() {
        let s = build_request_payload("get", "/content?a=1", "1788000000", "abc", "ff00", "FP");
        assert_eq!(s, "AURORA-REQ-v1\nGET\n/content?a=1\n1788000000\nabc\nff00\nFP");
        assert!(!s.ends_with('\n'), "завершающего перевода строки быть не должно");
        assert_eq!(s.matches('\n').count(), 6, "ровно шесть переводов между семью полями");
    }

    #[test]
    fn метод_поднимается_в_верхний_регистр() {
        let s = build_request_payload("post", "/auth", "1", "n", "h", "f");
        assert!(s.starts_with("AURORA-REQ-v1\nPOST\n"));
    }

    #[test]
    fn приставка_посредника_в_подпись_не_входит() {
        // 🔴 Главное отличие от шлюза. Сервер видит `/auth`, значит подписываем `/auth`.
        assert_eq!(
            signed_path_for_edge("https://ref.supabase.co/functions/v1/auth").as_deref(),
            Some("/auth")
        );
        assert_eq!(
            signed_path_for_edge("https://ref.supabase.co/functions/v1/content?product=x").as_deref(),
            Some("/content?product=x")
        );
    }

    #[test]
    fn похожий_путь_не_режется() {
        // `/functions/v1x` — другой путь, приставкой не является.
        assert_eq!(
            signed_path_for_edge("https://h/functions/v1x/auth").as_deref(),
            Some("/functions/v1x/auth")
        );
    }

    #[test]
    fn голая_приставка_даёт_косую_черту_а_не_пустоту() {
        assert_eq!(signed_path_for_edge("https://h/functions/v1").as_deref(), Some("/"));
    }

    #[test]
    fn процентные_тройки_поднимаются_в_верхний_регистр() {
        // Посредник приводит их к верхнему до нас — клиент обязан подписать ту же форму.
        assert_eq!(percent_triples_to_upper("/c?f=%d0%be"), "/c?f=%D0%BE");
        // Не-тройки не трогаются: имена регистрозависимы.
        assert_eq!(percent_triples_to_upper("/Cab/File.MD"), "/Cab/File.MD");
        // Хвост, похожий на тройку, но неполный — оставить как есть, не портить строку.
        assert_eq!(percent_triples_to_upper("/a%d"), "/a%d");
    }

    #[test]
    fn многобайтовый_символ_в_пути_не_разваливается() {
        assert_eq!(percent_triples_to_upper("/кабинет?x=%2f"), "/кабинет?x=%2F");
    }

    #[test]
    fn свёртка_пустого_тела_считается_а_не_пустует() {
        // Пустое тело хешируется как пустой вход — так же поступает сервер.
        assert_eq!(
            body_sha256_hex(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
    }

    #[test]
    fn свёртка_известного_тела_совпадает_с_эталоном() {
        assert_eq!(
            body_sha256_hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn ключ_устройства_переживает_повторное_обращение() {
        let dir = std::env::temp_dir().join(format!("aurora_devkey_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let first = DeviceKey::load_or_create(&dir).expect("ключ создаётся");
        let second = DeviceKey::load_or_create(&dir).expect("ключ читается повторно");
        assert_eq!(
            first.public_b64(),
            second.public_b64(),
            "🔴 ключ обязан быть тем же: новый при каждом запуске = законный отказ сервера"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn открытый_ключ_в_формате_который_ждёт_таблица_закрепления() {
        let dir = std::env::temp_dir().join(format!("aurora_devkey_fmt_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let key = DeviceKey::load_or_create(&dir).expect("ключ создаётся");
        let pub_b64 = key.public_b64();
        assert_eq!(pub_b64.len(), 44, "32 байта в base64 с набивкой — 44 знака");
        assert!(pub_b64.ends_with('='), "набивка обязательна: сервер отвергает её отсутствие");
        assert!(
            pub_b64[..43].chars().all(|c| c.is_ascii_alphanumeric() || c == '+' || c == '/'),
            "стандартный алфавит, не base64url: сервер отвергает base64url разбором"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn подпись_проверяется_своим_же_открытым_ключом() {
        use ed25519_dalek::{Signature, Verifier, VerifyingKey};
        let dir = std::env::temp_dir().join(format!("aurora_devkey_sig_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let key = DeviceKey::load_or_create(&dir).expect("ключ создаётся");
        let payload = build_request_payload("POST", "/auth", "1788000000", "n1", "ff", "FP");
        let sig_b64 = key.sign(&payload);

        let pub_bytes: [u8; 32] = STANDARD.decode(key.public_b64()).unwrap().try_into().unwrap();
        let sig_bytes: [u8; 64] = STANDARD.decode(&sig_b64).unwrap().try_into().unwrap();
        let verifying = VerifyingKey::from_bytes(&pub_bytes).unwrap();
        assert!(verifying.verify(payload.as_bytes(), &Signature::from_bytes(&sig_bytes)).is_ok());

        // Контроль: проверка обязана падать на изменённой строке, иначе она ничего не значит.
        let tampered = build_request_payload("POST", "/auth", "1788000001", "n1", "ff", "FP");
        assert!(
            verifying.verify(tampered.as_bytes(), &Signature::from_bytes(&sig_bytes)).is_err(),
            "🔴 подпись обязана не сойтись на другой строке"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn одноразовое_число_не_повторяется() {
        let a = new_nonce();
        let b = new_nonce();
        assert_eq!(a.len(), 32);
        assert_ne!(a, b, "повтор одноразового числа снял бы защиту от воспроизведения");
    }

    // ── Приёмка эталонными векторами ────────────────────────────────────────────────────────
    //
    // 🔴 Это единственная проверка, которая доказывает совместимость с сервером. Все тесты выше
    // сверяют реализацию с собственным пониманием автора; векторы порождены ДРУГИМИ реализациями
    // (Rust-тест шлюза и Python-сервер узла Б) и потому ловят расхождение, которого автор не
    // видит.
    //
    // Источник: `aurora-meta/Projects/CPD141_step1/vectors/vectors.json`, 75 векторов.
    // Значения вписаны сюда ДОСЛОВНО, а не читаются из файла: чтение чужого репозитория по
    // относительному пути ломает сборку у всякого, кто просто склонировал проект, — это уже
    // случилось однажды и записано решением ADR-048. Цена такого переноса — обязанность
    // обновить эти константы, если векторы пересчитают; id вектора указан у каждой.

    /// Вектор A1, группа `canonical_request_string`.
    /// Источник: `aurora_gateway/src/cloud/protocol.rs:1144-1161`,
    /// тест `canonical_request_matches_server_side`.
    /// Ловит: состав, порядок полей, разделитель, приставку протокола, приведение метода.
    #[test]
    fn вектор_a1_каноническая_строка_совпадает_с_эталоном() {
        let полученная = build_request_payload(
            "post",
            "/v1/jobs?after=3",
            "1785000000",
            "nonce-0001",
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "a6a64d59ca6d5ab8dccfe9556fa82c81ae90ab01051b0d44c8726ba9f533f5f0",
        );
        let эталон = "AURORA-REQ-v1\nPOST\n/v1/jobs?after=3\n1785000000\nnonce-0001\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\na6a64d59ca6d5ab8dccfe9556fa82c81ae90ab01051b0d44c8726ba9f533f5f0";
        assert_eq!(полученная, эталон, "строка обязана совпасть с эталоном посимвольно");
        assert_eq!(полученная.as_bytes().len(), 187, "эталонная длина в байтах из вектора A1");
    }

    /// Вектор A3: регистр метода на строку не влияет.
    #[test]
    fn вектор_a3_регистр_метода_не_меняет_строку() {
        let a = build_request_payload("get", "/p", "1", "n", "h", "f");
        let b = build_request_payload("GET", "/p", "1", "n", "h", "f");
        assert_eq!(a, b);
        assert_eq!(a, "AURORA-REQ-v1\nGET\n/p\n1\nn\nh\nf", "эталон строки из вектора A3");
    }

    /// Вектор A2: строка параметров входит в подпись — иначе посредник подменил бы параметр,
    /// а подпись осталась бы верной.
    #[test]
    fn вектор_a2_параметры_входят_в_подпись() {
        let a = build_request_payload("GET", "/v1/jobs/x?after=5", "1", "n", "h", "f");
        let b = build_request_payload("GET", "/v1/jobs/x?after=6", "1", "n", "h", "f");
        assert_ne!(a, b, "разные параметры обязаны давать разную строку");
    }

    /// Вектор A7 (отрицательный, расхождение реализаций): не-ASCII метод.
    /// Rust поднимает только ASCII (`poſt` → `POſT`), Python — по правилам Unicode (`POST`).
    /// Здесь закрепляется поведение Rust: расхождение существует, и мы обязаны знать, на чьей
    /// мы стороне. Живого случая нет — методы приходят из нашего же кода списком.
    #[test]
    fn вектор_a7_не_ascii_метод_ведёт_себя_как_rust_эталон() {
        let s = build_request_payload("poſt", "/p", "1", "n", "h", "f");
        assert!(
            s.starts_with("AURORA-REQ-v1\nPOſT\n"),
            "🔴 приведение обязано быть ASCII-только, как в шлюзе: расхождение с Python записано в векторе A7"
        );
    }

    /// Векторы C1–C3, группа `body_hash`.
    #[test]
    fn векторы_c1_c3_свёртка_тела_совпадает_с_эталонами() {
        assert_eq!(
            body_sha256_hex("".as_bytes()),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "C1: пустое тело"
        );
        assert_eq!(
            body_sha256_hex("{}".as_bytes()),
            "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
            "C2: пустой объект"
        );
        assert_eq!(
            body_sha256_hex("{\"cabinet\": \"копирайтер\", \"prompt\": \"Ответь одним словом\"}".as_bytes()),
            "5ceccd51d3f6e0652b2ba6592722ae23c7dd59dcf53c1e6c74d036accb051703",
            "C3: кириллица в теле — считается по байтам UTF-8, а не по символам"
        );
    }

    // ── Находки внешнего аудита 05.09 ───────────────────────────────────────────────────────

    #[test]
    fn якорь_в_подпись_не_попадает() {
        // Якорь в сеть не уходит: сервер увидит `/content`, значит подписывать надо его.
        assert_eq!(
            signed_path_for_edge("https://h/functions/v1/content#top").as_deref(),
            Some("/content")
        );
        assert_eq!(
            signed_path_for_edge("https://h/functions/v1/content?a=1#top").as_deref(),
            Some("/content?a=1")
        );
    }

    #[test]
    fn адрес_без_пути_всё_равно_подписывается() {
        // Сервер увидит `/`, и раньше клиент такой запрос молча не подписывал.
        assert_eq!(signed_path_for_edge("https://ref.supabase.co").as_deref(), Some("/"));
        assert_eq!(signed_path_for_edge("https://ref.supabase.co?x=1").as_deref(), Some("/?x=1"));
    }

    #[test]
    fn не_адрес_вовсе_подписывать_нечего() {
        // Единственный случай, где `None` правилен: разобрать нечего.
        assert_eq!(signed_path_for_edge("не-адрес"), None);
        assert_eq!(signed_path_for_edge(""), None);
    }

    #[test]
    fn повреждённый_ключ_даёт_ошибку_а_не_новый_ключ() {
        // 🔴 Инвариант 7.3 handoff, который не стерёг НИ ОДИН тест (находка аудита): молчаливая
        // замена повреждённого ключа новым выглядела бы как «подпись вдруг перестала совпадать»
        // и разбиралась бы неделями.
        let dir = std::env::temp_dir().join(format!("aurora_devkey_bad_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join(DEVICE_KEY_FILE), b"korot").unwrap();

        match DeviceKey::load_or_create(&dir) {
            Ok(_) => panic!("повреждённый ключ обязан дать ошибку, а не новый ключ"),
            Err(причина) => assert!(
                причина.contains("повреждён"),
                "причина обязана называть повреждение, иначе оператор не поймёт: {причина}"
            ),
        }
        // И файл не подменён втихую.
        assert_eq!(std::fs::read(dir.join(DEVICE_KEY_FILE)).unwrap(), b"korot");
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Вектор A6: кодированное имя в пути остаётся дословно, тройки — ВЕРХНИМ регистром.
    ///
    /// 🔴 Вектор писался для шлюза, где приставка входа (`/cloud`) входит в подпись. У нас
    /// приставка посредника срезается — это НАШЕ отличие, проверенное отдельным тестом выше.
    /// Здесь берётся ровно та часть вектора, которая общая: форма процентных троек.
    #[test]
    fn вектор_a6_кодированное_имя_сохраняется_верхним_регистром() {
        let путь = signed_path_for_edge(
            "https://ref.supabase.co/functions/v1/content/files/%D0%BE%D1%82%D1%87%D1%91%D1%82.txt",
        )
        .expect("путь разбирается");
        assert!(путь.contains("%D0"), "тройки обязаны быть верхним регистром");
        assert!(!путь.contains("%d0"), "строчных троек быть не должно — посредник их поднимет");
        assert_eq!(путь, "/content/files/%D0%BE%D1%82%D1%87%D1%91%D1%82.txt");
    }
}
