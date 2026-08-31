# Пульс: инвентаризация исходящих сетевых обращений (Aurora Econometrica thinwt)

## Задача своими словами
Team-lead просит разведку только на чтение: найти ВСЕ точки исходящего сетевого трафика в `src-tauri/src` (Rust) и `sidecar/` (Python), понять для каждой — куда идёт, внешний хост или локальная петля, когда срабатывает, уходят ли данные пользователя, стоят ли гейты `local_only`/`ensure_cloud_consent`. Отдельно глубоко разобрать 4 чувствительных файла (online_auth.rs, updater.rs+content_updater.rs, feedback.rs, parser.rs+econ_sidecar/sidecar_runtime.rs), проверить что реально отключается в 152-ФЗ редакции (`cfg(feature = "cloud_advisors")`), и сверить текст тумблера «только локально» в settings/+page.svelte (630-670) с фактическим охватом гейта `ensure_not_local_only` (который стоит только в claude.rs:158 и rag_client.rs:86). Ничего не менять, не коммитить.

## План
1. Grep по всему src-tauri/src на сетевые паттерны (reqwest, hyper, ureq, TcpStream, Client::new, .get(, .post() — построить полный список точек выхода.
2. Проверить sidecar/ (Python) на requests/httpx/urllib/openai/anthropic.
3. Прочитать полностью 4 чувствительных файла: online_auth.rs, updater.rs, content_updater.rs, feedback.rs, parser.rs, econ_sidecar.rs, sidecar_runtime.rs.
4. Проверить cfg(feature = "cloud_advisors") на каждой найденной точке.
5. Прочитать settings/+page.svelte строки ~600-700 (тумблер local_only) — дословный текст.
6. Собрать таблицу + разбор + вердикт, вернуть как финальный ответ (без файла-отчёта).

СТАРТ: 2026-08-09 (время сессии, локальное)

## Прогресс
1. ✅ Grep по src-tauri/src на сетевые паттерны — 22 файла-кандидата, все проверены на ложные срабатывания (report.rs, session/manager.rs, session/history.rs, durable_store.rs, user_config.rs, fingerprint.rs, pptx_processor.rs, project.rs, diagnostics.rs — ложные, только .get()/.post() на коллекциях/serde_json).
2. ✅ sidecar/ (Python econometrica) — grep на requests/httpx/urllib/openai/anthropic — только build_sidecar.py (build-time скрипт, urllib на 127.0.0.1 health-check), рантайм-код (aurora_html/aurora_pptx/charts/data/engines/optimize/tools/utils) чист.
3. ✅ Прочитаны целиком: online_auth.rs, rag_client.rs, updater.rs, feedback.rs, content_updater.rs (первые ~1290 строк, весь сетевой код), parser.rs, econ_sidecar.rs, sidecar_runtime.rs, execution_mode.rs, gateway_executor.rs (весь, 1761 строк), claude.rs (гейты + ветвление local/cloud), econometrica.rs (grep+заголовок), brand.rs (grep).
4. ✅ cfg(feature = "cloud_advisors") найден ровно в 3 файлах: claude.rs, rag_client.rs, cabinet.rs (последний — видимость кабинета в UI, не сеть). Остальные сетевые модули безусловны.
5. ✅ commands/mod.rs — только gateway_executor.rs под cfg(feature = "thin").
6. ✅ settings/+page.svelte строки 590-753 прочитаны дословно.

СТОП: инвентаризация завершена, отчёт отправлен team-lead.

## Фаза 2 — правка текста (2026-08-09, постфактум)
Задача: по мотивам инвентаризации привести к факту текст тумблера «Только локально» в `settings/+page.svelte` (район 608-670). Опорную формулировку дал team-lead, с условием проверить упоминание hostname фактом и поправить при расхождении.
1. ✅ Перечитан текущий текст (строки 605-674) — подтверждено расхождение из отчёта.
2. ✅ Grep на дословные фрагменты старого текста по `src/` и `tests/` — тестов, сверяющих текст дословно, не найдено. Найден похожий, но отдельный текст в `src/lib/components/pipeline/InsightsPanel.svelte:460` («Локальная редакция: ИИ-ассистент отключён (данные не уходят).») — вне заявленного скоупа (это про 152-ФЗ редакцию, не про тумблер), не трогала, сообщила team-lead.
3. ✅ Подпись тумблера (640) и пояснение (661-664) переписаны — hostname назван прямо («имя компьютера») по факту из `online_auth.rs::AuthRequest`.
4. ✅ `npm run check` + `npm test` → `Projects/gate_front_3text.log`, grep без `| tail`: `0 ERRORS` (svelte-check, 177 warnings — существовавшие, не мои), `Tests 1445 passed (1445)`, `Test Files 97 passed (97)`.
5. ✅ Коммит узким pathspec (`src/routes/settings/+page.svelte` только) — `1934e1a fix(honesty): текст режима «только локально» приведён к фактическому охвату`. Не пушила. Соседние изменённые файлы в рабочем дереве (content_updater.rs, lib.rs, sidecar/*, tools/*) — чужие, не мои, не подмешаны (staged только 1 файл, 6+/3-).

СТОП фаза 2: правка внесена, гейты зелёные, отчёт отправлен team-lead.

## Фаза 3 — вычистка класса по всему фронту + список за пределами (2026-08-09, постфактум)
Задача: починить `InsightsPanel.svelte:460` (тот же класс, что фаза 2), пройти весь фронт (`.svelte`/`.js`) широким поиском на абсолютные обещания про сеть/приватность, почистить найденные, за пределами интерфейса (Rust bail!/anyhow!, docs/) — только список.
1. ✅ Широкий grep по `src/` (не только точные слова team-lead, ещё синонимы: «покидают/покидает», «изолирован», «остаётся на машине» и т.д.) — 2 новых проблемных места нашлись: `settings/+page.svelte:100` (toast после переключения тумблера) и `InsightsPanel.svelte:460` (error message econ_ask_insight) — оба переписаны тем же приёмом («данные» → «ваши материалы»).
2. ✅ Проверены и оставлены без правки как точные: `CloudConsentOverlay.svelte:98,117`, `settings/+page.svelte:703,721-723,876,892`, `data-chat/+page.svelte:184`, toasts про согласие — нигде абсолютных обещаний, кроме двух починенных.
3. ✅ Найдено неочевидное место — `ChatPanel.svelte:920-922`, универсальный passthrough `Ошибка: ${err}` любой Rust-ошибки в чат; для кодов `[CL-LOCAL-ONLY]`/`[CL-LOCAL]` это означает, что абсолютный текст из `claude.rs:159` реально долетает до пользователя. Правка потребовала бы новой условной логики (не просто слов) → вынесено в отчёт team-lead как «предлагаю так, решай ты», не трогала.
4. ✅ За пределами интерфейса — grep по `src-tauri/src`, `content-packs/`, `New_AI_Agency/`, `docs/`: 2 Rust-места (`claude.rs:159`, `rag_client.rs:87`, оба «данные не уходят», не правила) + 3 markdown-документа (`docs/audits/D1_ZERO_EGRESS_PROTOCOL.md`, `docs/DATA_FLOW.md`, `docs/PRD_COMMERCIAL_READINESS.md`) — все три технически честны, уже делают то же разделение «данные клиента vs служебные соединения», что я предложила для UI.
5. ✅ Проверила потребителя `econ_rag_search` на фронте (`InsightsPanel.svelte:403-407`) — ошибка (включая текст `rag_client.rs:87`) там проглатывается молча (`catch {}`), пользователю не показывается — снижает критичность этой конкретной Rust-строки.
6. ✅ `npm run check` + `npm test` → `Projects/gate_front_3text2.log`: `0 ERRORS` (177 warnings, существовавшие), `Tests 1458 passed (1458)`, `Test Files 98 passed (98)` (числа выросли против фазы 2 — чужие параллельные линии добавляли тесты в это же время, не я).
7. ✅ Коммит узким pathspec (2 файла: `settings/+page.svelte`, `InsightsPanel.svelte`) — `e9a4ef7 fix(honesty): обещания про сеть в интерфейсе приведены к факту`. Не пушила.

СТОП фаза 3: класс дефекта вычищен по всему проверенному фронту, находки за пределами переданы списком, отчёт отправлен team-lead.
