# Econometrica — роутер следующей сессии (после аудита+усиления промптов econometrist)

> Скопируй в начало новой сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_v230`
> (worktree релизной ветки `feat/econ-v2.3.0`). Обновлён 2026-07-13.

## Контекст — что сделано (НЕ переделывать)

**Аудит + методологическое усиление промптов кабинета econometrist ЗАВЕРШЕНЫ и ЗАПУШЕНЫ**
(`feat/econ-v2.3.0` @`a52b935`, origin синхронен). 13 коммитов:
- **Аудит промптов (5-фазный протокол), Фазы 0-4** — 9 коммитов: Батч0 доставка (`61a74ae`,
  version-канал vault оживлён + frontend min_core-защита) · Батч2 Аврора (`8c87ef3`, страж INV-50
  на сценарии + справка 7 шагов) · Батч1 множитель CLAUDE.md (`a1ff86c`, MQS/Ratio по движку,
  −33 строки дублей) · Батч3a фантомы (`af469a1`) · Батч3b UI/психо (`451a792`) · Батч4-active
  (`7ad7331`) · Батч4-legacy (`54ee67e`) · re-sign pack v7 (`5ce5547`) · Батч5 CI-линтеры (`d4a8049`).
- **aurora-upgrade (методология каноном)** — 2 коммита: приоритет 1 (`4d0d913`) + приоритет 2-3
  (`a52b935`). 9 промпт-находок применены (C1 ESOV INV-50, G1 TBR, G3 стационарность, C2 front-door,
  G2 CausalImpact, G6 петля, G5 Chan-Perry, G4 pretreatment, G8 rank plots). Канон уже был в
  RAG-библиотеке — докупка НЕ нужна.

**Гейты зелёные:** cargo 190 · svelte-check 0 · vitest 1263 · cabinet_eval --dry 6/6 · 3 линтера
промптов OK (lint_prompt_commands / check_help_consistency / check_content_pack_sync — в CI+lefthook,
проверены «внести-поймать-откатить») · content-pack v7 подпись валидна.

**Полная фактура:** `Projects/audit_prompts_2026-07-13/` — SUMMARY.md (аудит), PHASE2_PLAN.md (план),
AUTONOMOUS_STATE.md (трекер), IMPL_B*.md (реализация), CANON_*.md (aurora-upgrade срезы). Диф канона:
`D:\Docs\Knowledge_Library\Projects\skill_upgrades\econometrist_canon_diff_2026-07-13_full.md`.

## Задачи продолжения (приоритет)

### 1. 🔑 Публикация релиза 2.3.1 (главное, наружу — гейт Антона)
Регламент `aurora-release-update` + `aurora-fix` pre-build чеклист:
- ⚠️ **ОБЯЗАТЕЛЬНЫЙ живой прогон в окне ДО сборки** (`npm run tauri:dev` с мостом, окружение БЕЗ
  `ANTHROPIC_API_KEY` — баланс ключа исчерпан, egress через claude.ai-подписку). Зелёные гейты его
  НЕ заменяют. Пройти пайплайн до Отчёт → «Завершить анализ».
- Пересборка sidecar → installer (`CARGO_TARGET_DIR="D:/cargo-targets/ai-agency" npm run tauri build`).
- Supabase manifest + latest.json (облачная + ОТДЕЛЬНЫЙ манифест `aurora-econometrica-gui-local`).
- Content-pack v7 уже переподписан — при публикации залить + bump content_versions; vault пересобрать
  (промпт-правки доедут через vault-OTA, канал оживлён в Батче 0).
- Живой смоук установленного .exe.

### 2. clippy-долг 7 предсуществующих ошибок (первым, тривиально — разблокирует CI clippy)
НЕ мои, были до аудита: `online_auth.rs:26-28` (doc-quote без `>`), `report.rs:281` (filter_map→map),
`fingerprint.rs:27/31/34` (map_or). Блокируют CI-гейт `cargo clippy -D warnings` релиза. 5 минут.

### 3. Внешний diff-аудит кода Батчей 0-5 (НЕ прогонялся)
Wrap-up этой сессии аудировал только блок aurora-upgrade (base-sha сдвинут на `a34791d`). Код Батчей
0-5 (Rust-доставка version-канала в `lib.rs`/`online_auth.rs`/`content_updater.rs`, JS-Аврора страж
InsightsPanel) прошёл приёмку по батчам + гейты, но НЕ внешний diff-аудит. Самое рискованное — Батч 0
(механика доставки vault + frontend version-compare). Прогнать аудит `git diff <до-61a74ae>..a34791d`.

### 4. Справку econometrist переписать под 8 активных команд
`src-tauri/help/econometrist.html` документирует 9 СКРЫТЫХ legacy /mmm-* и не бандлится в Optimizer
(help-econometrica/). Батч 3b временно СКРЫЛ кнопки «Инструкция»/«Справка» для econometrist. Написать
help под 8 консультационных команд + положить в бандлируемую папку + вернуть кнопки.

### 5. Движковый бэклог aurora-upgrade (продуктовые, не текст промпта)
- **G7** — fake-data parameter recovery (SBC) до реальных данных в Python sidecar MMM (Gelman Workflow).
- **G9** — geo-уровневая иерархия GBHMMM (Sun 2017): новая секция контракта `[geo-decomposition]` +
  иерархическая модель PyMC + команда `/geo-breakdown`. Даёт tighter CI + меньше экстраполяции.
- **0.2 прямой frontend-сценарий** — константа `BUNDLED_FRONTEND_VERSION` на сборке (старый OTA-бандл
  сейчас может пережить апдейт .exe). Latent (frontend встроен), не срочно.
- **Серверная `vault_versions`** — Supabase Edge /auth должен слать карту версий (клиент готов, Батч 0);
  без неё version-докачка спит. Вне репо.

### 6. Мерж v2.3.0 → master (по решению Антона)
master древний. Релизная линия — кандидат в новый master. cabinet-drift-guard показывает расхождение
SSOT-пары `Aurora_Econometrica ↔ Aurora_Econometrica_avrora` (сверить при мерже). Shared-репо —
координировать с параллельными сессиями (Legal/Media Маши делали ТОТ ЖЕ аудит на своих продуктах).

### 7. Приоритет 2-3 aurora-upgrade — ПРИМЕНЁН весь; диф закрыт. Осталось опционально: перепроверить
живым прогоном, что канон-правки реально проявляются (страж INV-50 на ESOV, TBR-совет в pilot).

## Инварианты/правила
- INV-50 честность метрик (прод-страж `insights-grounding.js` НЕ трогать).
- Кабинет-эконометрист развивается ТОЛЬКО в Econometrica; Agency архивный.
- JS+JSDoc не TS. Клиентский текст: короткое тире «–», без англицизмов, без slash-команд.
- Релиз доезжает по СВОЕМУ каналу; content-pack из УСТАНОВЛЕННОГО (`%LOCALAPPDATA%`); после правки
  content-pack — `python tools/sign_content_pack.py --bump` ОБЯЗАТЕЛЕН (регламент CLAUDE.md репо §18).
- Правка промпта кабинета → `python tools/lint_prompt_commands.py` 0 FAIL + `cabinet_eval --dry`.
- Shared-репо: зонд HEAD/автора ДО коммита/тега; коммит узким pathspec.

## С чего начать
1. Прочитать `Projects/audit_prompts_2026-07-13/AUTONOMOUS_STATE.md` (трекер) + `INDEX_econometrica`
   (память, шапка) + этот роутер.
2. Уточнить у Антона: публикация 2.3.1 сейчас (нужен живой прогон), или clippy+аудит кода, или мерж.

## 🔴 Руководство по стилю действий (прочитать ПЕРВЫМ)
1. **Перед докупкой канона/книг — выжать проиндексированный корпус каталогом** (`lib_vec.py cats` +
   `ls books_md/<тема>/`), не беглым семантическим поиском: cos≠покрытие. В этой сессии Фаза-4
   рекомендация «достать Vaver-Koehler» оказалась ложной — книга уже в корпусе (утонула на cos 0.4).
   [[feedback_exhaust_indexed_corpus_before_recommending_purchase]].
2. **JSON сверять ПАРСЕРОМ, не grep.** В Фазе 0 grep дал ложный ноль на минифицированном
   command-meta-data.json — «команд econometrist нет» оказалось артефактом (они были). `python -c json.load`.
3. **Приёмка субагента = проверять ПОЛНОТУ, не только заявленное.** Субагент Батча 3b заменил 3 психо-фазы
   из 6, пропустил «Проверяю конвергенцию» (тоже врала про расчёт) + 32 U+2014 в insights-текстах psy-data.
   Линтер help-consistency поймал U+2014 — линтеры окупаются. Лично сверять диапазон, не финальную строку.
3. **content-pack правка → re-sign в ТОМ ЖЕ коммите** (иначе verify падёт, manifest устареет). Кейс
   themes.json (предсущ. рассинхрон) закрыт этим же re-sign. Инструмент `tools/sign_content_pack.py`,
   ключ `~/.secrets/rosst_content_private.key` (общий Aurora, совпал с content_sig.rs).
4. **base-sha wrap-up мог сдвинуться** (у меня покрыл только последний блок). Для аудита предыдущих
   блоков брать явную базу по `git log`, не полагаться на `.git/claude-session-base-sha`.
5. **cabinet-drift-guard в linked worktree НЕ блокирует** (строгую проверку откладывает до мержа) —
   информационный вывод про SSOT-пару нормален. Реальная сверка пары — при мерже v2.3.0.
6. **Живой прогон ловит проводку, юнит — функцию.** Перед релизом обязателен прогон в окне (Батч 0
   оживил доставку, но серверная часть vault_versions вне репо — правки промптов доедут только новым
   installer/vault, не OTA, пока сервер не шлёт версии).
