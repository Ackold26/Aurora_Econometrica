fn main() {
    tauri_build::build();
    // Embed build timestamp (Unix seconds) - used for system clock sanity check
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    println!("cargo:rustc-env=BUILD_TIMESTAMP={secs}");

    // 🔴 Внешний аудит 2026-07-29, вторая волна (Critical): идентификатор приложения обязан
    // попадать в бинарь ИМЕННО ОТСЮДА. Прежде `lib.rs` читал `option_env!("TAURI_ENV_IDENTIFIER")`,
    // считая её переменной, которую выставляет сборщик Tauri. Она такой НЕ является: сборщик
    // задаёт TAURI_ENV_ARCH, TAURI_ENV_DEBUG, TAURI_ENV_FAMILY, TAURI_ENV_PLATFORM,
    // TAURI_ENV_PLATFORM_TYPE, TAURI_ENV_PLATFORM_VERSION и TAURI_ENV_TARGET_TRIPLE — и НИКОГДА
    // TAURI_ENV_IDENTIFIER (проверено перечислением строк в самом сборщике и подтверждено на
    // диске: каталог `%LOCALAPPDATA%\aurora-econometrica-gui` — это запасной путь по имени
    // пакета, куда и уходило состояние). Поэтому имя своё, не «как у Tauri»: чтобы никто снова
    // не решил, будто её кто-то выставляет снаружи.
    let manifest_dir = std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR");
    let conf_path = std::path::Path::new(&manifest_dir).join("tauri.conf.json");
    let conf = std::fs::read_to_string(&conf_path)
        .unwrap_or_else(|e| panic!("не прочитан {}: {e}", conf_path.display()));
    let mut identifier = extract_identifier(&conf)
        .unwrap_or_else(|| panic!("в {} не найдено поле identifier", conf_path.display()));

    // Econометрика — единственный из форков, что собирается в ДВУХ редакциях с разным
    // identifier: облачная читает базовый tauri.conf.json как есть, а `npm run
    // tauri:build:local` вызывает `tauri build --config tauri.local.conf.json`, и tauri-cli в
    // этом случае выставляет env `TAURI_CONFIG` — JSON merge-patch поверх базового конфига,
    // ИМЕННО из него `tauri_build::build()` выше в этой же функции берёт итоговый identifier
    // (см. `tauri-build::try_build`, `json_patch::merge`), и ИМЕННО его Tauri runtime
    // впоследствии вернёт из `app_local_data_dir()`. Если прочитать только файл
    // `tauri.conf.json` и проигнорировать этот оверлей, локальная редакция получит в бинарь
    // идентификатор облачной (`com.aurora.econometrica` вместо `.local`) — расхождение с тем,
    // что реально вернёт `app_local_data_dir()`, и durable_store снова уедет не в тот каталог,
    // хоть и не в прежний фолбэк по имени пакета. Оверлей побеждает намеренно — он и есть
    // «последнее слово» при выставленном TAURI_CONFIG, как и для самого tauri_build.
    if let Ok(tauri_config_env) = std::env::var("TAURI_CONFIG") {
        if let Some(overridden) = extract_identifier(&tauri_config_env) {
            identifier = overridden;
        }
    }

    assert!(
        !identifier.is_empty(),
        "identifier пуст — состояние ушло бы в запасной каталог по имени пакета"
    );
    println!("cargo:rustc-env=AURORA_APP_IDENTIFIER={identifier}");

    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=tauri.conf.json");
    // 🔴 Батч C (C10): оверлей локальной редакции читает СТОРОЖ
    // `durable_store::tests::build_identifier_matches_tauri_conf` через `include_str!`. Без этой
    // строки правка `tauri.local.conf.json` не пересобирала бы крейт, и сторож сверял бы
    // устаревший текст — то есть молчал бы ровно тогда, когда идентификатор локальной редакции
    // разъехался.
    println!("cargo:rerun-if-changed=tauri.local.conf.json");
    println!("cargo:rerun-if-env-changed=TAURI_CONFIG");
}

/// Достаёт значение поля `"identifier"` из JSON-текста — форматно-агностично (годится и для
/// многострочного `tauri.conf.json`, и для компактной однострочной строки `TAURI_CONFIG`,
/// которую tauri-cli сериализует без переносов; построчный разбор «одна пара на строку» тут
/// не подошёл бы). Полноценный serde_json не подключаем — build-dependencies продукта его не
/// тянут, а искомое значение плоское и в обоих источниках не встречается как под-объект.
fn extract_identifier(json_text: &str) -> Option<String> {
    let idx = json_text.find("\"identifier\"")?;
    let after_key = &json_text[idx + "\"identifier\"".len()..];
    let after_colon = after_key.trim_start().strip_prefix(':')?.trim_start();
    let after_quote = after_colon.strip_prefix('"')?;
    let end = after_quote.find('"')?;
    Some(after_quote[..end].to_string())
}
