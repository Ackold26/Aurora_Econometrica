---
tags: [session, compressed, s10, help-system, ui-polish, sidecar, cabinet-redesign]
type: session
updated: 2026-04-20
---

# Quick Reference

Сессия S10 Aurora AI Econometrica: критичные S9-fixes, 4 мини-технических улучшения, полный редизайн справочной системы под Econometrica-only с sanitize секретов, UI polish (единая кнопка «?» в header, редизайн кабинета под pipeline-стиль, управляемый UnitCostsPanel, реалистичная MCMC-оценка для JAX, значки «?» на терминах), удалён нестабильный «Спросить AI», пропатчен hover-bug в navbar-меню всех 12 help-систем.

**Topic:** s10-help-ux-cabinet-polish
**Key files:**
- Rust: `src-tauri/src/econ_sidecar.rs`, `commands/project.rs` (+`project_load_results`), `commands/econometrica.rs`, `lib.rs`, `Cargo.toml` (+`wait-timeout`)
- Frontend stores: `src/lib/project-state.js` (+`restoreProjectResults` + `reconcileStepMetaFromDisk`)
- Components: StepWrapper, OptimizeStep, OptimizeOnboarding, ScenarioPlayground, UnitCostsPanel, MQSBadge, ConvergenceDashboard, ConfigPanel, ReportStep, InsightsPanel
- Routes: `/+page.svelte`, `/pipeline/+layout.svelte`, `/cabinet/+page.svelte`
- Help: `src-tauri/help-econometrica/*` (9 HTML + econ-nav.js)
- Python: `sidecar/econometrica/engines/scenario.py`, `server.py`
- Prompts: `New_AI_Agency/econometrist/.claude/commands/*.md` (6 новых)
- Всех 12 navbar'ов help-систем: `nav.js` / `econ-nav.js` в каждом продукте

**Status:**
- ✅ Закоммичено: `0be2bba`, tag `v1.0.7-s10-help-ux-polish`, pushed `origin/master`
- 📋 Cabinet redesign (3 блока: Data-Prep / Awareness / Consumption) — отложен, план в `~/.claude/projects/D--Docs-Aurora-Ai/memory/project_econometrica_cabinet_redesign.md`
- ⏳ Live-тест S10 — на Антоне

---

## Learnings

### Архитектурные паттерны

1. **Синхронизация stepMeta с диском — stores в памяти + localStorage кеш расходятся**
   - Проблема: `pipelineStepMeta` сохраняется в localStorage (survives restart), `modelData`/`decomposeData`/`optimizeData` — только в памяти. После рестарта stepper показывает `error`/`complete` а данных нет.
   - Решение: на активацию проекта `project_load_results` читает `results/*.json` → заполняет сторы → `reconcileStepMetaFromDisk` пересобирает stepMeta по фактам (есть файл → complete, нет → ready/locked, `error` без подкрепления → сбрасываем).
   - Принцип: stepMeta — derived от реального наличия данных, не первичный источник истины.

2. **Single source of truth для tooltip-текстов**
   - Один `HELP` объект в `ExpertModelPanel.svelte` — текст терминов (R²/MAPE/R-hat/Divergences/Ratio/α/γ/β/ROI/CI) написан один раз, переиспользуется в `MQSBadge` и `ConvergenceDashboard`. Унификация слов для одних и тех же терминов.

3. **Нейтральная терминология в пользовательской справке**
   - «Вычислительный модуль» вместо «Python sidecar»
   - «Папка проекта» вместо `%APPDATA%/aurora-econometrica-gui/projects/…`
   - «С защитой от подделки» вместо «Ed25519 подпись»
   - Не раскрываем архитектуру (Tauri/SvelteKit/WebView2), технологию называем только там где она — методологическое преимущество (JAX/NumPyro для скорости).

4. **Управляемое добавление > жёсткий автодетект** для неоднородных данных
   - UnitCostsPanel старая версия: regex `TRP|GRP|OTS|РЕЙТИНГ|ОХВАТ|ПОКАЗ|ПРОСМОТР|КЛИК|ВИЗИТ|ПУНКТ|IMPRESSION|CLICK` → ловил лишнее, не ловил «статьи/спецпроекты».
   - Новая: autodetect только `TRP|GRP|OTS|РЕЙТИНГ|ОХВАТ` (чистые ТВ-единицы). Остальное — dropdown «+ Добавить канал» + manual input. Одна hint-ссылка «Обнаружено N TRP/GRP/OTS — добавить все» только когда список пустой.

5. **Tokio context в Tauri setup()**
   - `tokio::spawn` в setup callback **паникует** с `no reactor running`. Рутайм ещё не привязан к main thread.
   - Решение: `tauri::async_runtime::spawn` — роутится в Tauri managed runtime, работает всегда.

### UI/UX

6. **Hover-dropdown bug pattern**
   - `margin-top` на dropdown + `position: relative` на parent = «мёртвая зона» между ними. Когда курсор её пересекает, `:hover` у parent теряется, dropdown исчезает.
   - Fix: `padding-bottom: 6px; margin-bottom: -6px` на parent (расширяет hover-зону, компенсирует layout) + `margin-top: 0` на dropdown (бесшовный стык).
   - Применено ко всем 12 nav.js в 10 продуктах Aurora AI.

7. **Scroll race в overlay tours**
   - `scrollIntoView({behavior: 'smooth'})` длится ~300мс, `requestAnimationFrame` даёт 1 кадр (~16мс). Замер rect попадает на половину анимации → spotlight дрожит.
   - Fix: если блок уже в viewport (`rect.top < 0.8 * vh && rect.bottom > 0.2 * vh`) → замер моментально; иначе smooth scroll + RAF polling (2 стабильных кадра подряд или cap 500мс).

8. **Onboarding gate — проверка готовности DOM**
   - Onboarding тур с `document.querySelector('.block-status')` запускался до того как блоки появлялись в DOM (до train модели, channels пустой).
   - Fix: `$effect` с флагом `onboardingChecked` ждёт `channels.length > 0` перед `showOnboarding = true`.

### Стиль коммуникации с LLM-агентом

9. **«Ask и дай default»** — компактный шаблон для вопросов
   - Вопрос с чётким предложенным вариантом + «дай добро или скорректируй» экономит время. Использовано дважды за сессию (при compress, при cabinet redesign scope).

10. **Антон предпочитает реалистичную оценку > приукрашенную**
    - Старая оценка MCMC времени `mediaCount * 3.5 + 3` минут (→ 31 мин на 8 каналов, под Metropolis/PyMC) — он увидел и сказал «у меня моделирование занимает секунды». Новая под JAX/NumPyro `0.3 * mediaCount + 1` → 3 мин на 8 каналов + объяснение JIT XLA compile. Больше доверия.

### Безопасность

11. **PID owner verification в kill_on_port**
    - Исходный `kill_on_port` убивал ВСЕ процессы на порту 7430 по netstat. Если чужой процесс занял порт (теоретически) — снесём.
    - Fix: `is_our_sidecar_process(pid)` через `tasklist /FI "PID eq X" /FO CSV /NH` → имя содержит `python` или `econometrica-sidecar`. Иначе warn + skip.

12. **Приватные данные MMM-проектов в .gitignore**
    - До S10 `sidecar/econometrica/<projectname>/` содержал `data/`, `models/latest.pkl`, `results/*.json`, `exports/*` и `project.json` — **реальные данные клиентов** (Кагоцел, венарус-ммх).
    - Добавлено в .gitignore:
      ```
      sidecar/econometrica/*/data/
      sidecar/econometrica/*/models/
      sidecar/econometrica/*/results/
      sidecar/econometrica/*/exports/
      sidecar/econometrica/*/project.json
      sidecar/econometrica/1test/
      sidecar/econometrica/венарус-ммх-*/
      sidecar/econometrica/mmx-*/
      ```

---

## Decisions

### Принято в диалоге

1. **Кабинет econometrist — не дублировать pipeline, а дополнять**
   - Удалены 7 старых mmm-* команд из UI (но `.md` остаются для ручного ввода).
   - Добавлены 6 новых команд-консультантов: `/interpret-model`, `/why-channel`, `/explain-ratio`, `/pilot-design`, `/next-quarter-plan`, `/data-gaps`.
   - Плюс awareness-forecast и awareness-to-sales остаются.

2. **Полный редизайн кабинета на 3 раздела — отложен**
   - Новое понимание: кабинет должен стать главной → 3 крупных блока, каждый открывает свой специализированный UI (не command-grid):
     - Мастер подготовки данных (wizard с XLSX-шаблоном на выходе)
     - Прогноз awareness (из медиаплана)
     - Прогноз потребления от знания (Mediascope awareness → consumption, S-curve)
   - Только `interpret-model` мигрирует в pipeline (inline-action в шаг «Отчёт»). Остальные 5 старых кабинетных команд (why-channel/explain-ratio/pilot-design/next-quarter-plan/data-gaps) — **удаляются**.
   - Mixed frequency (месячный awareness + квартальный consumption): MVP = агрегация до квартала, Expert mode = MIDAS.
   - План на 6 этапов (~10-13ч) в `project_econometrica_cabinet_redesign.md`.

3. **«Спросить AI» в InsightsPanel удалён**
   - Был нестабилен (требовал `open_cabinet('econometrist')` предварительно — без него «Cabinet session not open»). Lazy-открытие добавил, но Антон решил убрать полностью.

4. **Справочная система — Econometrica-only, sanitized**
   - Удалены все упоминания других продуктов (Insights Hub, Creative, Legal, Docu-master, Brand Hub) и сервисов (Mediascope, Nielsen, Wordstat).
   - Удалены секреты: vault, AES-256-GCM, Ed25519, APPDATA paths, aurora-econometrica-gui, localhost:7430, pickle, Python sidecar, Tauri, SvelteKit, WebView2.
   - Оставлены методологические открытия: JAX 0.7.2, NumPyro 0.20.1, Python 3.12 (рекламируются как преимущество в system-requirements).

5. **Visual Pipeline на главной: «Перейти к командам» пока disabled**
   - Badge «скоро». Кабинет будет открыт после завершения редизайна на 3 раздела.

6. **Поведенческую психологию / celebrations / empathetic errors — пока не внедряем**
   - Были предложены из аудита (peak-end, variable reward, goal-gradient, empathetic errors) — Антон сказал «не применяй пока».

---

## Pending

### Отложенные задачи (в памяти)

1. **Редизайн кабинета на 3 раздела** — `project_econometrica_cabinet_redesign.md`
   - Этап 1 — расчистка (удалить 5 старых .md, оставить interpret-model, cabinet.rs минимум) — ~30 мин
   - Этап 2 — миграция interpret-model в ReportStep как inline-action — ~1ч
   - Этап 3 — редизайн главной кабинета в 3 блока pipeline-стиля — ~1-2ч
   - Этап 4 — Мастер подготовки данных (Svelte wizard, генерация XLSX-шаблона) — ~2-3ч
   - Этап 5 — Прогноз awareness (UI + уже готовый `engines/awareness.py`) — ~2ч
   - Этап 6 — Прогноз потребления от знания (новый `consumption.py` + mixed-frequency UI) — ~3ч

### Открытые вопросы до старта Cabinet redesign

- **Mediascope XLSX формат** — Антон пришлёт пример реальной выгрузки (нужно для парсера)
- **Типы awareness** — spontaneous / aided / top-of-mind: одна метрика или multi-target?
- **Mixed frequency** — MVP = quarterly aggregation, Expert = MIDAS. Подтвердить.

### Долгосрочные

- **OLS-fallback для <20 точек** — 6-8ч (`project_econometrica_ols_fallback.md`)
- **Trust Level 3: Brand vs Performance MMM split** — 12-20ч (`project_econometrica_brand_perf_split.md`)
- **Hill backend: учёт media_means/stds** — pre-existing issue
- **Interpret-model как button в ReportStep** — часть Этапа 2 редизайна

### Мелочи

- **Feedback-форма уходит в Google Forms** (`feedback.rs:11`, obfuscated URL). Если нужно сменить адресата — создать новую Google Forms с 3 полями и заменить URL + entry IDs.
- **Live-тест S10** — не сделан, остался на Антона.

---

## Full Session Notes

### 1. Критичные S9-fixes (утренние — после аудита)

**Баг 1: Onboarding запускался до train модели**
- `OptimizeStep.svelte` — `$effect` проверял localStorage и сразу ставил `showOnboarding = true`. Но блоки A-E скрыты за `{#if channels.length > 0}` → `document.querySelector('.block-status')` возвращал null → 6 модалок без spotlight.
- Fix: добавил `onboardingChecked` флаг + условие `channels && channels.length > 0`. `restartOnboarding()` даёт alert если блоков нет.

**Баг 2: Scroll race в spotlight**
- `OptimizeOnboarding.svelte` делал `scrollIntoView({behavior: 'smooth'})` + `requestAnimationFrame` → замер rect на середине анимации → spotlight прыгал.
- Fix: проверка viewport (частично виден → замер моментально), иначе RAF polling с детекцией стабильности rect (2 кадра с `Math.abs(r.top - prevTop) < 0.5` или cap 500мс).

**Баг 3: unit_costs guard**
- `scenario.py` не фильтровал отрицательные/NaN/нечисленные значения unit_costs → bogus ROAS.
- Fix: helper `_sanitize_unit_costs(raw)` в scenario.py проверяет `val > 0 and val == val` (NaN-safe).

### 2. 4 мини-технических улучшения

**1. Human-readable scenario names**
- `ScenarioPlayground.svelte` использовал `${Date.now()}` → `current-1713523847293` (ужасно).
- Fix: `autoTimestamp()` даёт `dd.MM HH:mm` → `Текущий 19.04 14:30` / `Оптимум 19.04 14:30`.

**2. `child.wait_timeout(3s)` вместо `child.wait()`**
- Блокирующий wait мог висеть бесконечно на зомби-процессе.
- Fix: добавлен крейт `wait-timeout = "0.2"` в Cargo.toml. `ChildExt::wait_timeout(Duration::from_secs(3))`.

**3. Backward compat старых сценариев**
- S8-сценарии сохранены без `total_spend_money` / `roas_money` — compare_scenarios показывал warn вместо money-mode.
- Fix: `compare_scenarios(unit_costs)` принимает unit_costs; `_migrate_money_fields(data, unit_costs)` пересчитывает money-поля на лету из `media_plan`. Файлы на диске НЕ переписываются. Server.py: новый `CompareRequest` class. Rust: `econ_compare` пробрасывает `unit_costs`. Frontend: ScenarioPlayground передаёт unitCosts из store.

**4. kill_on_port PID owner verify**
- `is_our_sidecar_process(pid)` через `tasklist /FI "PID eq X"`. Имя должно содержать `python` или `econometrica-sidecar`. Иначе warn + skip (не убиваем чужие процессы).

### 3. project_load_results + reconcileStepMetaFromDisk

**Новая Rust-команда `project_load_results(project_id) -> Value`** в `commands/project.rs`:
- Читает `results/validation.json`, `model-diagnostics.json`, `decomposition.json`, `optimization.json`
- Возвращает `{validation, modelDiagnostics, decomposition, optimization}` — null для отсутствующих

**Frontend — `restoreProjectResults(pid)` в project-state.js:**
- Подписка на `activeProjectId.subscribe` — при смене/активации заполняет сторы `validateData`, `modelData.diagnostics`, `decomposeData`, `optimizeData`
- Флаг `_lastRestoredPid` — один раз per pid
- Ограничение: `channelParams` и `normalization` лежат в pickle (не JSON) — не восстанавливаются. Для Report + Insights хватает `diagnostics`. Re-train нужен для повторной оптимизации.

**`reconcileStepMetaFromDisk({hasValidation, hasModel, hasDecompose, hasOptimize})`:**
- Пересобирает stepMeta: шаг с данными → `complete`; без данных но предшественник `complete` → `ready`; остальные → `locked`
- Все остаточные `error`-статусы без подкрепления сбрасываются
- Если `currentStep` на locked-шаге → `findLastIndex` для усабельного шага

Фиксит баг: **«Декомпозиция ❌ пока пользователь на Валидации»** — status error от прошлой упавшей попытки висит в localStorage.

### 4. Справочная система — полный редизайн

**Удалено:**
- `econometrist.html` (дублировал функциональность кабинета)

**Новые файлы:**
- `data-preparation.html` — структура данных, FMCG (пиво, помесячные) + Pharma (OTC, недельные) примеры, Ratio 2/4/6 пороги, unit_costs таблица, частые ошибки валидации
- `pipeline.html` — 5 шагов с input/output/time-tag
- `methodology.html` — Bayesian MMM, Adstock (Geometric/Weibull), Hill, NUTS, MQS, Trust Levels 1/2/3, сравнение с Robyn/LightweightMMM
- `faq.html` — 10+ QA с `<details>` аккордеоном
- `user-guide.html` — навигационная хаб-страница
- `system-requirements.html` — ОС, железо (Минимум / Рекомендация / Для больших моделей), bundled зависимости (Python 3.12 / JAX 0.7.2 / NumPyro 0.20.1), оффлайн-работа, время обучения по CPU

**Переписано:**
- `about.html` — только Econometrica-контент, без других продуктов
- `error-codes.html` — убраны VT (vault), CL (Claude CLI); добавлены EC (вычислительный модуль), DP (данные). Title → «Aurora AI Econometrica».
- `index.html` — новые ссылки, обновлённый tips, hero с полным логотипом `logo-full.png` (96px) слева + заголовок/tagline справа (выровнены по левому краю)

**econ-nav.js:**
- Добавлен `system-requirements`, убран `econometrist`
- Navbar теперь с `logo-wordmark.png` (22px) + текст «Econometrica» (11px uppercase)
- **Hover-bug fix:** `margin-top: 4px` на dropdown убран → `.anav-group { padding-bottom: 6px; margin-bottom: -6px; }` — бесшовная hover-зона.
- Тот же fix применён ко всем 12 nav.js в других продуктах (AI_APP_AGENCY, Creative_Hub, Oracle, Parser, PR_Master, ROSST_Creative/DocMaster/Legal/Media, Aurora_Econometrica/src-tauri/help/nav.js + econ-nav.js). Python-скрипт batch-патчинга в одном Bash-вызове.

### 5. Rust расширения

**`open_help(cabinet_id)` переписан:**
- Sanitize: только `[A-Za-z0-9_-]` в имени
- 3-level fallback:
  1. content_pack/help_file_path
  2. resource_dir/help-econometrica/ или resource_dir/help/
  3. dev fallback: `CARGO_MANIFEST_DIR/help-econometrica/`
- Дубликатная моя функция `open_help(page_id)` была удалена — слилась с существующей.

**Новые команды:**
- `econ_sidecar_restart` — force_restart из UI (для «Перезапустить модуль»)
- `project_load_results` — чтение results/*.json

### 6. UI polish

**Header pipeline (`/pipeline/+layout.svelte`):**
- Кнопка «?» справа от settings, динамически выбирает раздел help:
  - steps 0, 1 → `data-preparation`
  - step 2 → `methodology`
  - steps 3, 4, 5 → `pipeline`
- `HELP_PAGES = ['data-preparation', 'data-preparation', 'methodology', 'pipeline', 'pipeline', 'pipeline']`
- `openStepHelp()` → `invoke('open_help', { cabinetId: HELP_PAGES[$pipelineCurrentStep] ?? 'index' })`

**Удалена кнопка `.step-help` из StepWrapper** — теперь единая в header. Prop `helpPage` сохранён для обратной совместимости, но не рендерится.

**Кнопка «Назад» на шаге 0 pipeline:**
- Было: `disabled={$pipelineCurrentStep === 0}`
- Стало: `goBack()` на шаге 0 вызывает `goto('/')` → главная. Title динамический.

**Главная `/+page.svelte`:**
- Добавлена кнопка «?» в topbar-right после settings → `invoke('open_help', { cabinetId: 'index' })`.
- Visual Pipeline карточка: «Перейти к командам» disabled + `.coming-soon-badge` «СКОРО».

**Редизайн cabinet econometrist (`/cabinet/+page.svelte`):**
- Breadcrumb-logo с 36px → использование topbar-left + topbar-logo (26px) + brand-product (15px uppercase) — как в главном меню `/`
- Убрана back-btn из header (дублировала footer-back-btn)
- Добавлен `footer-back-btn` слева от `selection-input` (симметрия с pipeline footer)
- Project-chip рядом с логотипом, показывает активный проект

**6 новых команд консультанта** в `New_AI_Agency/econometrist/.claude/commands/`:
- `interpret-model.md` — объяснение результатов руководству
- `why-channel.md` — разбор одного канала (saturation, adstock, unit mixing)
- `explain-ratio.md` — что значит Ratio, как улучшить
- `pilot-design.md` — 4-6-недельный пилот, параметры, критерии
- `next-quarter-plan.md` — план на квартал + точки пересмотра
- `data-gaps.md` — приоритизированный список пробелов в данных

**cabinet.rs:** econometrist теперь 8 команд (3 «Смысл» + 3 «Стратегия» + 2 «Awareness»). 7 старых mmm-* команд убраны из UI list, но .md файлы остаются для ручного ввода. Тест `get_commands_for_cabinet("econometrist") == 8`.

### 7. «Спросить AI» удалён из InsightsPanel

- Ранее: `askAI()` собирал контекст (MQS/R²/channels/base_pct/lift), строил prompt, вызывал `send_message({cabinetId: 'econometrist', message, suppressExport: true})`.
- Проблема: требовал активную cabinet session (workspace распакован). В pipeline сессия не открыта → «Cabinet session not open».
- Попытка фикса: lazy `invoke('open_cabinet', ...)` на первый запрос → работало.
- Решение Антона: убрать полностью.
- Удалено: input `.ask-input`, карточка `.ai-response`, state (question/aiLoading/aiResponse/aiAvailable/econSessionOpened), `onMount` с проверкой, `buildContext()`, `askAI()`, CSS `.ai-response/.ai-label/.ai-text/.ai-dismiss/.ai-spinner/.ask-section/.ask-input/@keyframes spin`.

### 8. UnitCostsPanel — управляемое добавление

- `UNIT_HINT` сужен до `/TRP|GRP|OTS|РЕЙТИНГ|ОХВАТ/i` (чистые ТВ-единицы).
- `allMediaChannels` = все с `role === 'media'`.
- `selectedNames` = Set имён, managed by пользователем.
- `nonMoneyChannels` = derived от selectedNames (рендерим).
- `availableToAdd` = all − selected.
- `autoUnselected` = autodetect matches − selected.
- `addChannel(name) / removeChannel(name) / addAllAutoDetected()`.
- UI: dropdown с ★ для autodetected + кнопка «Добавить» + кнопка ✕ на каждой строке + hint «Обнаружено N — добавить все» только если selected пустой.
- **Панель активна только при `$analysisObjective === 'roi'`**.

Preview row_meta: теперь всегда показывает «N юнит (в загруженных данных)» + дефолт + «Эквивалент: N × цена = ₽» даже для вручную добавленных каналов.

### 9. MQSBadge + ConvergenceDashboard — значки «?»

- **MQSBadge:** HELP-объект (rSq/mape/rHat/divs/ratio/block) с tooltip-текстом из ExpertModelPanel. Значок `?` после «Техническая диагностика» и после каждого термина в metric-rows.
- **ConvergenceDashboard:**
  - HELP.rhatChart / HELP.avpChart — описание графиков.
  - Значки `?` на `<h4>` заголовках.
  - **R²/MAPE overlay в правом верхнем углу** графика «Факт vs Прогноз» через ECharts `graphic: [{type: 'text', right: 14, top: 6, style: {text: 'R² = X · MAPE = Y%'}}]`. Монoшириный Consolas, 11px.

### 10. Реалистичная MCMC-оценка времени

- **Было:** `mediaCount * 3.5 + 3` → 31 мин на 8 каналов (формула под PyMC/Metropolis).
- **Стало:**
  - `ConfigPanel.svelte`: `secPerSample = 0.005 + enabledCount * 0.0008; totalSec = totalSamples * secPerSample + 20 (JIT)` → для 8 каналов 16 000 samples: ~202 сек = 4 мин.
  - `insights-rules.js`: `estimatedMinutes = Math.max(1, Math.round(0.3 * mediaCount + 1))` → 3 мин на 8 каналов.
  - Tip текст дополнен: «JAX/NumPyro NUTS. Первый запуск включает ~20 сек JIT-компиляции XLA — далее каждый sample занимает миллисекунды.»

### 11. Форматы экспорта — без цифр

- Убраны «8 слайдов» и «7 листов» из инсайта «📤 Форматы экспорта» (`insights-rules.js`) и карточек PPTX/XLSX в `ReportStep.svelte`. Осталось содержательное описание разделов.

### 12. Session tasks расчистка

В ходе сессии закрыты:
- Task #5 (critical fixes), #9 (names), #10 (wait_timeout), #11 (backward compat), #12 (PID verify), #13 (Rust help backend), #14 (HTML help content), #15 (help UI buttons), #16 (restore pipeline state), #17 (cabinet commands), #18 (cabinet prompts), #19 (cabinet redesign UI), #20 (commit + push + memory).
- Удалены как «не применяем пока»: #6 (empathetic errors), #7 (celebrations), #8 (collapsible insights).

### 13. Git

**Коммит:** `0be2bba` — `feat(econometrica): S9 sidecar recovery + S10 help system + UI polish`
- 207 файлов в staging (после .gitignore среза 39)
- Pushed: `origin/master`
- Tag: `v1.0.7-s10-help-ux-polish`

Предыдущие S9-изменения (uncommitted на начало сессии) вошли в этот же коммит — отдельного S9-коммита не было.

### 14. Memory обновлён

- Создан `project_econometrica_session10.md` (полная сводка)
- `MEMORY.md` индекс обновлён: S9 помечен как «вошёл в 0be2bba», S10 добавлен
- `project_econometrica_cabinet_redesign.md` уже был создан ранее в сессии (отложенный план)

---

## Errors & Workarounds

| Ошибка | Где | Обход |
|--------|-----|-------|
| `thread 'main' panicked: no reactor running` | `econ_sidecar::spawn_watchdog()` в Tauri setup() | Заменить `tokio::spawn` на `tauri::async_runtime::spawn` |
| «Cabinet session not open» при askAI | `send_message` требует workspace | Lazy `open_cabinet('econometrist')` перед первым запросом — потом удалено с фичей |
| Spotlight дрожит на onboarding | RAF-замер на середине scroll-анимации | Viewport check + RAF polling с stable-rect detection |
| Stepper `error` без данных после рестарта | stepMeta из localStorage, сторы пусты | `reconcileStepMetaFromDisk` пересобирает по фактам |
| Dropdown меню схлопывается при переходе к пункту | `margin-top: 4px` + `:hover` на parent | `padding-bottom + negative margin-bottom` на `.anav-group` (12 файлов) |
| HMR не подхватил изменения insights-rules.js | Svelte кеш | Ctrl+R в окне приложения |
| `type 'string' is not assignable to type 'StepStatus'` | TS-check | Cast через `/** @type {StepStatus[]} */` |
| `Cannot find module '$lib/types'` | Поиск typedef | Использовать local `@typedef` из project-state.js |

---

## Setup & Config Changes

**`.gitignore` дополнен:**
```
sidecar/econometrica/*/data/
sidecar/econometrica/*/models/
sidecar/econometrica/*/results/
sidecar/econometrica/*/exports/
sidecar/econometrica/*/project.json
sidecar/econometrica/1test/
sidecar/econometrica/венарус-ммх-*/
sidecar/econometrica/mmx-*/
```

**`src-tauri/Cargo.toml`:**
```toml
# Non-blocking child.wait — защита от зависания shutdown на зомби-процессе
wait-timeout = "0.2"
```

**Нет миграций БД, нет схем, нет env.**

---

## Commit Reference

```
0be2bba feat(econometrica): S9 sidecar recovery + S10 help system + UI polish
4fd0684 feat(econometrica): Reports — rich insights, format cards, MQS-cap, PPTX-fix (S8)
d11678b feat(econometrica): Phase 3 What-if + Phase 4 Forecast + аудит-фиксы (S7)
19d4ca7 feat(econometrica): Trust Level 1+2 — smell-banner + CPP-нормализация + live-fixes
5998b8b feat(econometrica): Optimize UX overhaul Phase 1+1B+2 + KPI denormalization (S6)
```

Tag: `v1.0.7-s10-help-ux-polish`
