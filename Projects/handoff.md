# Handoff для внешнего аудитора — полировка Econometrica v2.3.1

База diff: `4c1afc0` (начало сессии; hook-файл base-sha сдвинулся на 67ca785 → база оценочная,
взята по родителю первого коммита блока ea78812). HEAD: `6aa266b`.

## 1. Цель блока
Автономная «полировочная» сессия поверх уже завершённого аудита промптов кабинета econometrist.
Три направления: (а) разблокировать CI clippy-гейт; (б) внешний diff-аудит ранее закоммиченных
Батчей 0-5 → починка найденных дефектов; (в) сделать эвал-харнес кабинета доказанным гейтом
качества. Код-правки хирургические, семантику существующей логики менять не должны (кроме явно
исправляемых дефектов).

## 2. Ключевые инварианты
- **INV-50 честность метрик:** прод-страж `src/lib/insights-grounding.js` НЕ трогать. `numbers_grounded`
  в эвале — прямой импорт из него, не копия.
- **Нулевая регрессия доставки:** правки `content_updater.rs`/`lib.rs` НЕ должны менять поведение при
  старом сервере (без поля `vault_versions`) — только при его наличии. Fallback обязан совпадать с
  прежним поведением (запись глобального content_version).
- **Клиентский текст:** короткое тире «–» (U+2013), не «—» (U+2014); без англицизмов; без slash-команд.
- **Семантическая эквивалентность clippy-правок:** `is_some_and(f)` ≡ `map_or(false, f)`; `map` ≡
  `filter_map` только когда замыкание всегда возвращает `Some`.
- **Линтеры-стражи должны реально падать** на нарушении (не «мёртвый обвес»): ложное «OK» опаснее
  отсутствия проверки.
- **JS+JSDoc, не TS**; svelte-check (checkJs) 0 ошибок.

## 3. Осознанные компромиссы
- **B (per-cabinet версия) — латентная:** сервер `vault_versions` пока не шлётся (2c не реализовано),
  блок `if let Some(online.vault_versions)` спит. Фикс клиентской записи сделан заранее, вживую в окне
  НЕ проверялся (только юнит-тест + компиляция). Причина: активируется ровно при 2c, чинить лучше до.
- **B: `#[allow(clippy::too_many_arguments)]`** на download_updates (8 параметров) вместо рефактора в
  struct. Причина: все 8 — данные докачки, внутренняя функция с 4 фиксированными call-site; struct-рефактор
  вышел бы за scope починки латентного бага.
- **C (NFKC): channelNames НЕ санитизируются** (осталось в отчёт). Причина: риск рассинхрона матчинга
  (LLM вернёт искажённое имя ≠ оригинал), вектор смягчён JSON.stringify; полный фикс = рефактор scenario-пути.
- **2a: 5 test-only clippy-warnings оставлены** (внутри `#[cfg(test)]`: items_after_test_module ×3,
  field-assign, Range::contains). Причина: CI гоняет clippy без `--all-targets` → их не видит, гейт не блокируют.
- **Рычаг 1: полную многоитерационную эвал-петлю на живых прогонах НЕ гоняла.** Причина: недетерминированно,
  жжёт квоту подписки; детерминированные юнит-тесты грейдеров дают гейт надёжнее.
- **checksum vault пустой** (`json!({})` в lib.rs) — предсуществующее by-design, не трогала.

## 4. Зоны неуверенности (проверить прицельно)
1. **B call-site выбор (lib.rs:92/113/311/458):** правильно ли, что 458 (missing-gate, open_cabinet
   auto-download) передаёт `online.vault_versions.as_ref()`? `online` в scope (используется .content_version
   рядом), но уверенности, что для впервые-скачиваемого missing-кабинета запись server-версии корректна
   (а не должна быть fallback), нет на 100%. 311 (update_content) → `None`: команда «мёртвая» по SKEPTIC_S3,
   но если её кто-то вызовет — per-cabinet версия не запишется совсем (fallback на content_version отработает).
2. **B resolve_vault_version:** `content_version.trim_start_matches('c').parse().unwrap_or(0)` — корректно
   ли для всех форматов версии сервера? Если версия придёт как «c5c6» или не-«cN» — поведение (0 → запись
   пропускается). Проверить, что это безопасная деградация, а не потеря учёта версии.
3. **C NFKC:** `.normalize('NFKC')` применяется к ЛЮБОМУ тексту, идущему в промпт (вопрос пользователя,
   методология, имена каналов из tier1). Не меняет ли NFKC непреднамеренно легитимный контент — например
   надстрочные цифры/спецсимволы в числах-фактах, которые потом сверяет grounding? Заявлено «grounding не
   задет» (сверяет числа из JSON-фактов, не из промпта), но перепроверить, что NFKC не втягивается в путь
   grounding-чисел.
4. **A orphan-проверка:** `parse_legacy_command_stems` regex `/(mmm-[\w\-]+)` по всему тексту
   LEGACY_COMMANDS.md. Ловит ровно 9 legacy сейчас, но при упоминании `/mmm-*` в новом контексте файла
   (пример, changelog) может втянуть лишнее → пропустит реальный orphan. Оценить хрупкость SSOT-парсинга.
5. **Рычаг 1 маркер «оцен»:** расширение `оценк`→`оцен` в JUSTIFY_MARKERS (эвал, не прод). Не снимает ли
   ложно флаг INV-50 в эвале, если слово на «оцен» (оценивать/оценка) окажется в ±45 символов от РЕАЛЬНО
   выдуманного числа? Компромисс точности vs полноты.

## 5. Затронутые файлы
- `src-tauri/src/commands/online_auth.rs` — 2a: doc-quote `>24h`→«дольше 24 ч» (docstring, 1 строка).
- `src-tauri/src/crypto/fingerprint.rs` — 2a: 3× `map_or(false,·)`→`is_some_and(·)` (disk_is_fixed_internal).
- `src-tauri/src/commands/report.rs` — 2a: `filter_map`→`map` (замыкание всегда Some).
- `tools/lint_prompt_commands.py` — A: scoped `(?i:·)` на «довер…интервал» в CI_TERM_RE + CI_TERM_QUOTED_RE.
- `tools/check_help_consistency.py` — A: двусторонняя orphan-проверка + parse_legacy_command_stems (SSOT).
- `lefthook.yml` — A: сами линтеры + LEGACY_COMMANDS.md добавлены в glob соответствующих хуков.
- `src/lib/tier2-context.js` — C: `.normalize('NFKC')` первой в sanitizePromptFragment.
- `New_AI_Agency/econometrist/.claude/commands/next-quarter-plan.md` — D: секция «что собрать» из
  «Опционально» в обязательный костяк (пункт 5); помесячная разбивка осталась единственной опциональной.
- `src/lib/__tests__/econ-project-context.test.js` — D: тест проброса warnings/high_correlations в [validation].
- `src-tauri/src/commands/content_updater.rs` — B: resolve_vault_version + параметр vault_versions в
  download_updates + `#[allow(too_many_arguments)]` + юнит-тест.
- `src-tauri/src/lib.rs` — B: 4 call-site download_updates (передача vault_versions/None).
- `tools/cabinet_eval/graders.mjs` — Рычаг1: маркер «оценк»→«оцен»; перенос JSDoc к numbersGrounded +
  типизация стрелок (для svelte-check).
- `src/lib/__tests__/graders-eval.test.js` — Рычаг1: 15 юнит-тестов 6 грейдеров (позитив+негатив).
