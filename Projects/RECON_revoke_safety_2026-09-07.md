# RECON — безопасность отзыва прав anon/authenticated на licenses/activations/audit_log

Дата: 2026-09-07. Разведка read-only, к базе Supabase не подключалась, ничего не правила.
Область: весь `D:\Docs\Aurora_Ai\Dev\` — все найденные рабочие деревья продуктов (не только
Econometrica), включая worktree-копии `_wt_*`.

## ВЕРДИКТ: отзыв безопасен

Ни в одном клиентском коде (Rust/Tauri, Svelte/TS фронт, Python sidecar) и ни в одном
автоматизированном конвейере выпуска (CI, локальные release-тулы) не найдено прямого обращения
к `/rest/v1/licenses`, `/rest/v1/activations` или `/rest/v1/audit_log` публикуемым (anon) ключом.
Единственные места, где эти три таблицы вообще трогаются — серверные Edge Functions
(`supabase/functions/{auth,content,legal-rag}/index.ts`), и все они без исключения используют
`Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!` — роль `service_role`, на которую `revoke ... from
anon, authenticated` не действует (в Supabase `service_role` — отдельная роль с собственными
грантами, обычно с обходом RLS; наш отзыв её не касается).

Проверка «неделю назад» (30.08) подтверждена и усилена: тогда проверялась только Econometrica,
сейчас — все деревья, плюс явно разобрана ветка `feat/econ-canon-p0` (боевая версия
`content/index.ts`).

## Таблица находок

| Точка (путь:строка) | Тип кода | Таблица | Ключ | Ломается ли отзывом |
|---|---|---|---|---|
| `Aurora_Econometrica_thinwt\src-tauri\src\commands\online_auth.rs:18-19,518,1205` | клиент (Rust/Tauri) | нет прямого обращения к таблицам — только `/functions/v1/auth` и `/functions/v1/heartbeat` | заголовков apikey/Authorization в `check_auth()` нет вовсе | Нет — не REST, не таблицы |
| `Aurora_Econometrica_thinwt\src-tauri\src\commands\updater.rs:17-28,78-82` | клиент (Rust/Tauri) | нет — `/functions/v1/app-update` (платформенный verify_jwt гейт) | **anon** (JWT `role:"anon"`, зашит в коде) | Нет — не таблица, только auth-гейт функции; функция внутри service_role |
| `Aurora_Econometrica_thinwt\src-tauri\src\commands\content_updater.rs:18` | клиент (Rust/Tauri) | нет — `/functions/v1` | не проверялся детально (тот же паттерн, что у online_auth) | Нет — не REST |
| `Aurora_Econometrica_canon\supabase\functions\auth\index.ts:929-931,943,946,1158,1506,1583,1629,1655` | серверная функция | licenses (select), activations (select/insert/update/**delete**), audit_log (insert) | **service_role** | Нет |
| `Aurora_Econometrica_canon\supabase\functions\content\index.ts:683-685,690,898,925,958` и `Aurora_Econometrica_thinwt\supabase\functions\content\index.ts:99-101,106,152` | серверная функция | licenses (select), audit_log (insert) | **service_role** | Нет |
| `feat/econ-canon-p0:supabase/functions/content/index.ts` (через `git show`, 1016 строк) | серверная функция, боевая версия | licenses (select), audit_log (insert) | **service_role** (строка 685) | Нет — идентично canon |
| `Aurora_Creative_Hub\supabase\functions\legal-rag\index.ts:35,39,49,57,62` | серверная функция | licenses (select), activations (select), audit_log (insert) | **service_role** | Нет |
| `Aurora_Creative_Hub\tmp\sec3-work\supabase\functions\app-update\index.ts:16-22` | серверная функция | app_versions (не в списке отзыва) | **service_role** | Нет |
| `Aurora_Econometrica_thinwt\.github\workflows\ci.yml:233,253-259` | конвейер выпуска (CI) | app_versions (не в списке отзыва) | **SUPABASE_SERVICE_KEY** (secrets, не anon) | Нет |
| `_wt_oracle_master\tools\verify-content-pack.mjs:159-180` (и идентично в `_wt_oracle_gwsign`) | конвейер выпуска (локальный тул) | content_versions (не в списке отзыва), только **GET/select** | **anon** (тот же зашитый JWT, что в updater.rs) | Нет — не в списке отзыва, и только чтение |
| `ROSST_AI_DocMaster\CC-Sessions\2026-05-25-2258-...md:118,288-297` | ручная операция (не код, не конвейер) | licenses (POST/INSERT документирован явно; DELETE упомянут как pending-задача без явного ключа в тексте) | **SUPABASE_SERVICE_ROLE_KEY** из `~/.claude/aurora-secrets.env` (для POST; для DELETE ключ в заметке не указан, но контекст тот же ручной admin-workflow) | Нет по документированному POST; DELETE не удалось проверить напрямую — см. раздел ниже |

## Чего я НЕ смог проверить

- **Живое состояние грантов в самой БД Supabase** — к базе не подключалась (по прямому запрету
  задания). Весь вывод — из статического кода, не из `information_schema`/`pg_catalog` боевого
  проекта.
- **Деплой Edge Functions, для которых нет копии ни в одном локальном дереве** — если на сервере
  крутится функция, исходник которой не закоммичен ни в одну известную ветку/worktree, я её не
  увижу. Искала только по локальным деревьям в `D:\Docs\Aurora_Ai\Dev\`.
- **Точный ключ в ручной DELETE-операции** из `ROSST_AI_DocMaster` sessions-заметки
  (`DELETE /rest/v1/licenses?customer=eq.Влад&notes=eq.Тест`, пункт "Cleanup (optional)") — в
  тексте заметки явно указан ключ только для соседней POST-команды (SERVICE_ROLE_KEY из
  aurora-secrets.env). Для DELETE ключ не выписан отдельно; по контексту (тот же оператор, та же
  сессия, тот же секрет-файл) весьма вероятно тоже service_role, но это не факт с прямой цитатой.
  Задача — ручная, разовая, не автоматизирована — если она когда-либо выполнялась вручную
  оператором с собственным service_role доступом, отзыв прав у anon её не касается.
- **Ключ в ручной smoke-проверке** `GET /rest/v1/audit_log?event=eq.auth_signed` из
  `Aurora_Creative_Hub\Projects\audit_telemetry_findings.md` (аудит 2026-07-19) — ключ в заметке
  не зафиксирован. Разовая ручная проверка, не рабочий конвейер; даже будь она сделана anon-
  ключом, это SELECT — вне периметра предложенного `revoke` на DELETE/TRUNCATE/write.
- **Полный периметр «17 рабочих деревьев»** — в `D:\Docs\Aurora_Ai\Dev\` фактически более 70
  директорий (продуктовые деревья + `_wt_*` worktree-копии под конкретные задачи + архивы
  `_branch_archive_*`). Я програла грепы по ВСЕМ им без исключения, но если «17» — это конкретный
  закрытый список, а не всё содержимое `Dev\`, я не сверяла с этим списком поимённо — просто
  накрыла весь каталог целиком, что шире любого возможного списка из 17.

## Попутные наблюдения (не чинила, только фиксирую)

1. **Один и тот же публикуемый (anon) JWT-ключ зашит открытым текстом одновременно в клиентском
   бинарнике** (`updater.rs:28` во ВСЕХ продуктовых деревьях, где искала) **и в release-тулинге**
   (`tools/verify-content-pack.mjs:164`, только в Oracle-деревьях `_wt_oracle_master` /
   `_wt_oracle_gwsign`). Комментарии в обоих местах осознанно объясняют, что ключ публичный и
   не секрет — это соответствует модели Supabase (anon-ключ действительно предназначен для
   вшивания в клиент), риска в этом самом по себе нет. Отмечаю только как факт дублирования —
   если ключ когда-нибудь понадобится ротировать, менять придётся в обоих местах и во всех
   продуктовых деревьях, где встречается `updater.rs`.
2. **`ROSST_AI_DocMaster` сессионная заметка от 25.05.2026** документирует 3 дублирующиеся
   тестовые лицензии на живом клиенте («Влад», notes="Тест") как незакрытый "Cleanup (optional)"
   пункт — если это всё ещё актуально, это не относится к безопасности отзыва прав, но похоже на
   забытый техдолг в проде.
3. **`Aurora_Creative_Hub\Projects\SEC1_TELEMETRY_PATCH\`** содержит несколько файлов вида
   `auth_ROLLBACK_2026-08-23.ts`, `auth_ROLLBACK_2026-08-26.ts` и файл с именем
   `index.ts.ПЕРЕЕХАЛ_В_КАНОН` — похоже на историю миграции патча telemetry в auth-функцию с
   двумя точками отката. Не разбирала подробно (вне периметра задачи), но если планируется
   правка auth Edge Function в рамках этой же работы — стоит свериться, какая версия сейчас
   реально задеплоена (это как раз то, что просил перепроверить owner: `feat/econ-canon-p0`
   content-функция — разобрана выше и подтверждена).

## Итог одной строкой для передачи

Отзыв `revoke all on public.{licenses,activations,audit_log} from anon, authenticated` —
**безопасен**: весь найденный код, трогающий эти три таблицы (три Edge Functions: `auth`,
`content`, `legal-rag`, включая боевую `feat/econ-canon-p0` версию `content`), делает это
исключительно через `SUPABASE_SERVICE_ROLE_KEY`, роль которого отзыв не затрагивает. Anon-ключ
в клиентском коде используется только как платформенный auth-гейт для вызова Edge Functions
(`/functions/v1/*`) и для одного read-only `/rest/v1/content_versions` в release-тулинге — ни
то, ни другое не относится к отзываемым таблицам/правам.
