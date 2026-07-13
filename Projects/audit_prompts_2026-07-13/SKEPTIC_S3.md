# SKEPTIC S3 — адверсариальная перепроверка находок цепочки доставки промптов

Дата: 2026-07-13. Метод: личное чтение кода + граф вызовов + git-история + повторное хеширование. Read-only.

---

## Находка 1 — vault version-канал мёртв (lib.rs:69-87)

**Вердикт: CONFIRMED.**

Искала опровержение по всем веткам — не нашла:

1. **Триггеры download_updates в проде — только 2, оба missing-based:**
   - `get_cabinets` (lib.rs:69-96): фильтр `!path.exists()` ИЛИ `decrypt().is_err()`; при пустом `missing` скачивание пропускается (lib.rs:89 `if !missing.is_empty()`). Новая версия промпта не делает локальный vault ни missing, ни undecryptable → триггер не срабатывает.
   - `open_cabinet` (lib.rs:430-441): гейт `if !vault_path.exists()` — тоже только missing.
2. **`check_update_per_cabinet`** (content_updater.rs:197-214) — вызовы только из `#[cfg(test)]` (content_updater.rs:841,857,870,881). В прод-графе вызовов отсутствует. Подтверждаю аудитора.
3. **`vault_versions` из /auth** (online_auth.rs:111,159,352,400) — заполняется в структуру ответа и НИГДЕ не читается: единственные потребители `get_vault_versions()` — сама запись/миграция (content_updater.rs:72,201) и тесты; `check_update_per_cabinet` (единственный прод-кандидат-читатель) мёртв (п.2).
4. **Легаси version-канал `check_update`** (content_updater.rs:133, сравнение content_version) жив в Rust — но достижим ТОЛЬКО через Tauri-команду `check_content_update` (lib.rs:264-277, зарегистрирована в invoke_handler lib.rs:3216). **Фронтенд её не вызывает никогда:** grep `check_content_update|update_content|content_update` по всему `src/` — 0 совпадений. Единственный контент-вызов фронта — `get_local_content_version` (settings/+page.svelte:316) — чисто отображение версии.
5. **Обходные каналы, которые могли бы оживить доставку — проверены, нет:**
   - Обновление .exe (`updater.rs`) не трогает vaults (grep `vaults_dir|remove_dir_all|\.vault` — 0 совпадений) → после апдейта exe vault по-прежнему exists+decryptable.
   - `data_migration.rs` — копирует (не удаляет) vaults/content_version при смене identifier; idempotent, не форсит re-download.
   - Setup-хук (lib.rs:3146-3207): только `migrate_from_legacy` (запись vault-versions.json, не проверка) — фоновой задачи version-check нет.
   - Heartbeat / check_online_auth — download_updates не вызывают (все 3 вызова download_updates: lib.rs:92, 289 (мёртвая команда), 436 (missing-gate)).

Итог: у клиента с существующим расшифровываемым vault опубликованная новая версия промпта кабинета не доедет никаким путём кода. Находка верна as-is, severity high оправдана.

---

## Находка 2 — рассинхрон SHA-256 themes.json ↔ manifest.json

**Вердикт: DOWNGRADED (факт реален и закоммичен, но заявленный прод-механизм «провалит verify_manifest у клиента» преувеличен — все клиентские пути либо fail-safe, либо вообще не проверяют хеш).**

**Что подтвердила лично:**
- Перехешировала все 6 файлов manifest (PowerShell Get-FileHash): 5/6 сходятся; `themes.json` фактический `74d3f15e45bb22b290d7cda5e373bdea68d6e43e5439120ad88432c4bab0f366` ≠ manifest `3082ab5e...`. Расхождение подтверждено.
- **НЕ артефакт worktree:** `git status content-packs/` чист. themes.json правился коммитами f231053 (2026-06-13) и 9054f7f (2026-07-02), а manifest.json последний раз регенерирован в e3a7f9e «release: v2.1.0 + content-pack v5» (2026-06-14). Т.е. правка themes 2026-07-02 закоммичена БЕЗ re-sign — пропущенный шаг процесса, висит ~11 дней.

**Почему severity ниже заявленной (прод → процесс):**
1. **Клиентская верификация смотрит НЕ на репо и НЕ на бандл**, а на `%LOCALAPPDATA%/<id>/content-packs/` (content_pack.rs:14-29, verify at lib.rs:3161). Туда пак попадает только через OTA `download_content_pack`, который верифицирует manifest В STAGING до атомарного swap (content_updater.rs:467-485) → несогласованный пак отвергается, клиент остаётся на прежнем рабочем паке. Fail-safe, поломки нет.
2. **Бандл-канал (installer resources `../content-packs/*`, tauri.conf.json:36) хеш вообще не проверяет:** fallback `get_content_pack` (lib.rs:1722-1735) читает файл из ресурсов напрямую, без verify_manifest → на свежей установке НОВЫЙ themes.json доезжает несмотря на протухший manifest. Фронтенд зовёт его без гейта packs_ok (+layout.svelte:163-167, `.catch(() => null)`).
3. Никто не копирует бандл-пак в LOCALAPPDATA verbatim (только OTA-install и data_migration-копия ранее верифицированного пака) → протухший manifest в LOCALAPPDATA не окажется.

**Что остаётся реальным риском:** если из репо as-is собрать OTA-пак v6 без регенерации manifest — клиентский install отвергнет его (правка themes не доедет по OTA-каналу; тихо, только warn в лог). Это блокер БУДУЩЕЙ доставки + гигиена процесса (re-sign после 9054f7f не прогнан), не поломка живых клиентов. Если пак-сборщик релизного регламента регенерирует manifest из файлов при упаковке — рассинхрон в репо вообще не достигает клиентов.

---

## Находка 3 — внешний frontend-бандл перекрывает встроенный без version-compare (lib.rs:3174-3187)

**Вердикт: CONFIRMED (пыталась опровергнуть через download-этап — version-compare там есть, но сценарий находки он НЕ закрывает).**

**Load-этап — подтверждено лично:**
- lib.rs:3174-3187: выбор URL окна = `has_verified_external_frontend()` → aurora:// если true. Никакого сравнения версий.
- `has_verified_external_frontend` (lib.rs:2387-2406): читает `current_frontend_version.txt` + `verify_manifest(frontend-vN)` — проверяется ТОЛЬКО Ed25519-подпись/хеши, ни версия приложения, ни min_core_version.
- `handle_aurora_protocol` (lib.rs:2276-2374): отдаёт файлы из frontend-vN как есть, тоже без version-гейта.
- **min_core_version мёртв целиком:** grep по всему репо — поле объявлено (content_sig.rs:50), заполнено в manifest.json и тестовых фикстурах (content_sig.rs:200, content_updater.rs:901) — ни одного сравнения с `CARGO_PKG_VERSION` нигде. Подтверждаю аудитора.
- Ничто не сбрасывает `current_frontend_version.txt` при обновлении .exe: записи только в download-путях (content_updater.rs:538-544, 669); `cleanup_old_frontend_dirs` (lib.rs:2410-2436) чистит только версии СТАРШЕ текущей, текущую не трогает; updater.rs LOCALAPPDATA не трогает.

**Гипотеза-опровержение «version-compare есть на download-этапе» — проверена, канал существует, но сценарий не спасает:**
- `check_all_updates` (lib.rs:194-243): frontend-бандл качается при `server_fe_ver > local_ver` (lib.rs:219-240) — честный version-compare.
- НО: (а) он спавнится ТОЛЬКО из `check_online_auth` (lib.rs:179-187), которую фронтенд вызывает единственно со страницы настроек (settings/+page.svelte:313) — не при старте приложения; `get_cabinets`/`send_heartbeat` check_all_updates НЕ вызывают (проверено чтением lib.rs:56-110, 246-255);
- (б) в сценарии находки (обновился .exe с новыми встроенными JS-промптами, сервер bundle НЕ переопубликован) `server_fe_ver > local_ver` ложно → скачивания нет → старый внешний бандл продолжает перекрывать новый встроенный JS при каждом старте, бессрочно. Канал download-этапа лечит только ПОСЛЕ публикации нового бандла на сервере И визита пользователя в настройки.

Итог: находка верна as-is; смягчение — дисциплина «каждый exe-релиз с JS-правками = одновременная публикация frontend-бандла», но это процессный костыль, а min_core_version, спроектированный ровно под этот кейс, не подключён. Severity high оправдана.

---

## Сводка

| # | Вердикт | Ключевое |
|---|---|---|
| 1 | CONFIRMED | Оба прод-триггера download_updates — только missing/undecryptable (lib.rs:89, 430); check_update_per_cabinet только в тестах; vault_versions из /auth никем не читается; фронт не зовёт check_content_update/update_content (grep src/ = 0) |
| 2 | DOWNGRADED | Рассинхрон реален (74d3f15e ≠ 3082ab5e, воспроизведён Get-FileHash) и закоммичен (themes 9054f7f 2026-07-02 vs manifest e3a7f9e 2026-06-14, re-sign пропущен), но клиентские пути fail-safe: OTA-install верифицирует в staging и отвергает, бандл-fallback читает без проверки → живые клиенты не ломаются; блокируется лишь будущая OTA-доставка пака as-is |
| 3 | CONFIRMED | Load без version-compare (lib.rs:3176, 2387-2406 — только подпись); min_core_version нигде не потребляется; download-канал с version-compare есть (lib.rs:219-240), но гейтится визитом в настройки и публикацией сервера — сценарий exe-обновления не закрывает |

