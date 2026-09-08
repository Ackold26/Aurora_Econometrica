# PULSE — разведка безопасности отзыва прав anon/authenticated (2026-09-07)

## Задача (своими словами)
Проверить, безопасно ли отозвать DELETE/TRUNCATE-права у ролей anon/authenticated на боевые
таблицы licenses/activations/audit_log в Supabase. Нужно доказать фактами (путь:строка), что
клиентский код Aurora НЕ ходит напрямую в /rest/v1/ этих таблиц публикуемым ключом — только
через Edge Functions под service_role. Отдельно проверить конвейеры выпуска и ветку
feat/econ-canon-p0 (боевая версия supabase/functions/content/index.ts, 1006 строк).
Работа read-only: ничего не редактировать, не коммитить, к БД не подключаться.

## План
1. Найти все рабочие деревья Aurora в D:\Docs\Aurora_Ai\Dev\ (17 деревьев).
2. Grep по всем деревьям (Rust/TS/Svelte/Python) на /rest/v1/, supabase.from(, createClient(,
   .from('licenses'|'activations'|'audit_log'), python supabase SDK, postgrest.
3. Для каждой находки — определить ключ (anon/publishable vs service_role).
4. Проверить конвейеры выпуска (tools/, scripts/, .github/, *.mjs/*.ps1/*.py вокруг release).
5. Проверить supabase/functions/ этого дерева — какие таблицы и каким ключом.
6. git show feat/econ-canon-p0:supabase/functions/content/index.ts — разобрать отдельно.
7. Записать вердикт в RECON_revoke_safety_2026-09-07.md.

## Ход работы
- 22:23 — старт, маячок создан, план зафиксирован.
== update pulse ==
- 22:26 — grep по /rest/v1/, supabase.from(/.from('licenses'|'activations'|'audit_log'), createClient(,
  postgrest/python supabase SDK по всему D:\Docs\Aurora_Ai\Dev выполнен. Совпадения ТОЛЬКО в:
  supabase/functions/**/index.ts (серверные Edge Functions — ожидаемо), .github/workflows/ci.yml,
  tools/verify-content-pack.mjs, docs/RUNBOOK, Projects/*.md (заметки сессий, не код).
  Ни одного совпадения в клиентском Rust/Svelte/TS фронте или python sidecar — по этим 4 паттернам.
  Далее: точечно проверить src-tauri (Rust) и src/ (Svelte/TS фронт) на другие формы вызова
  supabase (fetch к REST URL напрямую, .env ключи), затем разобрать ci.yml и verify-content-pack.mjs,
  затем supabase/functions/*/index.ts на ключи, затем feat/econ-canon-p0 content/index.ts.
- 22:35 — src-tauri/src/commands/online_auth.rs (thinwt): supabase_url() = https://.../functions/v1
  (Edge Functions), POST {url}/auth и {url}/heartbeat. Ни одного обращения к /rest/v1/. Заголовков
  apikey/Authorization в check_auth() НЕТ вообще (для heartbeat не проверял детально).
- 22:37 — updater.rs (thinwt): анонимный ключ (JWT role=anon) ЗАШИТ в коде (supabase_anon_key(),
  строка 28), используется ТОЛЬКО как Bearer/apikey к /functions/v1/app-update (платформенный
  verify_jwt гейт Supabase Edge Functions). Комментарий в коде прямо говорит: ключ публичный,
  доступ ограничивают RLS + логика функции. Скачивание .exe идёт с /storage/v1/object/public/
  (публичный бакет) или github.io — не /rest/v1/.
- 22:40 — content_updater.rs (thinwt): та же схема, {url}/functions/v1, без /rest/v1/.
- 22:42 — canon supabase/functions/auth/index.ts: createClient с
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, единственный ключ. Трогает licenses (select),
  activations (select/insert/update/delete — stale cleanup), audit_log (insert). Строка 929-931,
  943, 946, 1158, 1506, 1583, 1629, 1655.
- 22:44 — canon и thinwt supabase/functions/content/index.ts: тот же SERVICE_ROLE_KEY, трогает
  licenses (select), audit_log (insert). Идентично в обеих копиях.
- 22:46 — git show feat/econ-canon-p0:supabase/functions/content/index.ts (1016 строк) — та же
  схема, SERVICE_ROLE_KEY, licenses+audit_log. Подтверждено — боевая версия НЕ отличается по клю-
  чу/таблицам от canon.
- 22:48 — Aurora_Creative_Hub/supabase/functions/legal-rag/index.ts — тоже SERVICE_ROLE_KEY,
  трогает licenses (select), activations (select), audit_log (insert) — строки 35,39,49,57,62.
- 22:50 — Aurora_Creative_Hub/tmp/sec3-work/supabase/functions/app-update/index.ts —
  SERVICE_ROLE_KEY, трогает app_versions (не в списке отзыва).
- 22:52 — .github/workflows/ci.yml (thinwt) — POST /rest/v1/app_versions с SUPABASE_SERVICE_KEY
  (secrets.SUPABASE_SERVICE_KEY), НЕ anon. Таблица app_versions — вне списка отзыва.
- 22:54 — tools/verify-content-pack.mjs (Oracle-деревья) — ПРЯМОЙ GET /rest/v1/content_versions
  с тем же зашитым anon-ключом (комментарий в коде подтверждает: "read-only, no secret involved").
  Таблица content_versions — ВНЕ списка отзыва (не licenses/activations/audit_log). Только SELECT,
  без DELETE/write. Не задевается предложенным REVOKE.
- 22:57 — ROSST_AI_DocMaster/CC-Sessions/2026-05-25-...md — ручная сессионная заметка: POST
  /rest/v1/licenses через curl с $SUPABASE_SERVICE_ROLE_KEY (не anon), и пункт "cleanup DELETE
  /rest/v1/licenses" в том же ручном контексте (service_role из aurora-secrets.env). Не автомати-
  зированный конвейер, не клиентский код.
- 22:58 — Aurora_Creative_Hub/Projects/audit_telemetry_findings.md — ручная smoke-проверка
  GET /rest/v1/audit_log?event=eq.auth_signed при аудите 2026-07-19, ключ в заметке не указан
  (не найдено доказательств, что это был anon). Разовая проверка при аудите, не рабочий конвейер.
- 23:00 — поиск завершён, пишу RECON_revoke_safety_2026-09-07.md.
- 23:05 — RECON_revoke_safety_2026-09-07.md записан. ВЕРДИКТ: безопасно. Задача завершена.
