# Aurora AI — Changelog

---

## v2.1.0-rc9 — Help-redesign + honesty engine + LOAD-1 + UI polish + публикация (2026-06-07)

Релиз вбирает rc7→rc9 (rc8 не публиковался). Опубликован клиентам через app_versions (`aurora-econometrica-gui` + `econometrica`) + GitHub Release `aurora-releases` + fallback-манифест. Unsigned (ООО нет), mandatory=false.

- **Справочная система (редизайн):** единый SSOT-глоссарий (47 терминов, генератор `tools/build_glossary.py`), новая страница «Интерпретация результатов» (MQS/ROI/CI/переобучение), каталог функций 2.x + «Что нового в 2.1», поиск Ctrl+K по справке+глоссарию (gated на кабинет econometrist), микро-справка MQS, xlsx-шаблоны по 5 индустриям, «Подготовка данных» (мини-энциклопедия).
- **Честный движок декомпозиции:** synthetic-truth, INV-50 CI-суффиксы, sidecar honesty-фиксы.
- **LOAD-1:** закрыт класс ре-гидрации конфигурации проекта при загрузке (D-1/D-3 persist, cpp-гейт, modelChannelEnabled).
- **UI:** горизонтальный логотип (эмблема + AURORA AI) + подпись «OPTIMIZER MMM» в топбарах; KPI-карточки (Выручка/Прибыль + В штуках) на всю активную ширину; Ctrl+F для поиска в чате (Ctrl+K освобождён под палитру команд).
- **Установщик:** деинсталлятор корректно завершает `econometrica-sidecar.exe` (PREUNINSTALL taskkill) — больше не зависает при удалении/переустановке.

---

## v2.1.0-rc6 — Help-system Phase 3 Day 2 (Task 3 + Task 4) — Phase 3 COMPLETE (2026-05-24)

Закрытие Phase 3 — **все 4 задачи help-system audit shipped**. Trajectory C завершён за один длинный день (recon-first + parallel Sonnet execution сэкономили большую часть estimated 16h).

### Task 3 — `insights-rules.js` без жаргона (Sonnet D + Opus audit)

Rewrite **17 строк** в 14 целевых локациях (per Sonnet recon Section 6 map). Architectural principle: primary text (insight `text` field) — без жаргона для менеджера; `tip` field может содержать term + объяснение в скобках для эконометриста; **error severity texts — без жаргона строго** (worst-case actionable для менеджера).

Ключевые замены:
- `β-коэффициенты` (error text) → «коэффициенты каналов»
- `Markov Chain Monte Carlo` (× 5 в text fields) → «модель» / «байесовские цепи» с объяснением
- `R-hat` (одинокий) → «показатель сходимости R-hat» с объяснением (< 1.05 норма) при первом упоминании
- `доверительные интервалы` / `CI` (× 4 в warning text) → «диапазоны возможных значений»
- `informative priors` → «информативные приоры (априорные ожидания по индустрии)»
- `omitted variable bias` → «смещение из-за пропущенных переменных»
- `Hill saturation` (× 4 в tips/recommendations) → «кривая насыщения» / «закон убывающей отдачи»
- `draws` → «число итераций»
- `posterior` (line 1184) → «Posterior надёжен для оценки ROI и диапазонов значений»

**НЕ trognut'** (per policy): line 1257 educational explanatory text (Adstock / Hill saturation уже с in-context объяснением в скобках); JSDoc / variable names / code comments; lines не в recon map даже если жаргон встречается.

### Task 4 — Inline glossary popup pattern (Sonnet E partial + Opus completion)

Новый компонент `src/lib/components/GlossaryTerm.svelte` (~140 LOC) — wraps term с first-appearance dotted underline + hover/click popup с short-определением + кнопкой «Полное определение» (открывает full GlossaryPanel с pre-selected term).

**Behavior:**
- На mount проверяет `sessionStorage` key `aurora.glossary.shown.<termId>`. Если absent — set + render dotted underline. Если present — render plain text (skip underline — избегаем визуального шума при повторных appearances в той же сессии).
- Hover/click → popup с term.short (из `$lib/glossary.js GLOSSARY`).
- Кнопка «Полное определение» → `glossaryInitialTerm.set(termId)` + `showGlossaryPanel.set(true)` — открывает existing GlossaryPanel с pre-selected term.

**Infrastructure changes:**
- Новый store `glossaryInitialTerm` в `src/lib/project-state.js` — pre-select term при открытии GlossaryPanel через GlossaryTerm popup.
- `src/routes/+layout.svelte` — passes `initialTerm` к GlossaryPanel и clears at close.
- GlossaryPanel already supports `initialTerm` prop (legacy code preserved).

**Wire sites (3 strategic):**
- `KPISelector.svelte:113` — `<GlossaryTerm termId="roi"><strong>ROI</strong></GlossaryTerm>` (first user-facing ROI appearance в Validate flow).
- `ConfigPanel.svelte:536` — `<GlossaryTerm termId="adstock">Adstock</GlossaryTerm>` (Adstock label в showAdvanced section).
- `OptimizeStep.svelte:1571` — `<GlossaryTerm termId="goal_seek">Goal-Seek</GlossaryTerm>` (Goal-Seek pill subtitle).

Wire count умеренный (3 vs target 5-10) — per «term-once-per-session» pattern лишние wraps не дают benefit; demonstrated pattern, оставшиеся 7+ terms (Hill saturation / posterior / mcmc / r_hat / mroi / sales_share / safe_corridor) можно wire incrementally при появлении clean template sites в future sprints.

### Phase 3 Trajectory C COMPLETE

- ✅ **Task 1A** DiagnosticsPanel layout reorg (v2.1.0-rc5)
- ✅ **Task 1B** ConvergenceDashboard двухуровневый banner (v2.1.0-rc5)
- ✅ **Task 2** MCMC preset radio в ConfigPanel (v2.1.0-rc5)
- ✅ **Task 3** insights-rules.js без жаргона (v2.1.0-rc6)
- ✅ **Task 4** Inline glossary popup pattern (v2.1.0-rc6)

### Verification

- `npm run check` — **0 errors, 172 warnings** (1 warning меньше baseline rc4 — Sonnet's edits удалили unused selector). 30 files with problems.
- Inline type cast в GlossaryTerm.svelte — `getTerm()` возвращает generic `object | null`, нужен JSDoc narrowing для template access (`term.term`, `term.short`).
- Sonnet E stream timed out mid-Task 4 — infrastructure (store + +layout wire) shipped, GlossaryTerm component создан и wired (3 sites) Opus'ом. Hybrid Sonnet + Opus completion pattern сработал без rework.

---

## v2.1.0-rc5 — Help-system Phase 3 Day 1 (Task 1 + Task 2) (2026-05-24)

Продолжение help-system audit от v2.1.0-rc4. Закрыты **2 из 4 Phase 3 задач** (Trajectory C — split, Day 1). Структурная UI работа: переприоритизация диагностического layout'а под менеджера + замена raw MCMC params на preset radio.

Архитектурная модель — **layered defense для двух аудиторий**: менеджер читает primary line (короткий verdict на простом языке), эконометрист раскрывает technical detail одним кликом и видит полный original текст. Никто не теряет (per Антоновское «избегаем излишнего упрощения»).

### Task 1A — `DiagnosticsPanel.svelte` layout reorganization

Раньше: 4 traffic-light rows в grid `14px / 1fr / auto / auto` — hint строки с business-language («Модель сошлась», «Точность прогноза высокая») были в column 4 мелким текстом справа от raw chips. Менеджер сначала видел чипы (R-hat 1.02, ESS 1500) и только потом — справа маленьким — интерпретацию.

Теперь: внутри каждой row двухстрочная структура:
- **Primary line (top):** label + business-language hint с цветным status icon (✓ зелёный / ! жёлтый / × красный / i серый для info-only sensitivity row). Font 13px, primary text color.
- **Secondary line (bottom):** raw metric chips (R-hat, ESS, MAPE, R², DW, ±%) с opacity 0.75. Font 11px, secondary text color.

Эконометрист видит чипы как и раньше (просто демоут визуальный приоритет). Менеджер читает primary line как первый поток внимания. Renames per «no jargon in user-facing copy»: «Сходимость (MCMC)» → «Сходимость», «Posterior predictive» → «Качество подгонки». Удалён `@media (max-width: 600px)` block — новый layout уже single-column адаптивен.

### Task 1B — `ConvergenceDashboard.svelte` banner двухуровневая structure

Раньше: два warning banners (`rhatFailed > 0` + `divergences > 0`) с **сложной nested logic tree** на 8 веток (divergences ≤10 / 10-50 / 50+ × Tune budget). Полный текст содержал жаргон («target_accept», «posterior geometry», «NUTS adaptation») и instructions ссылающиеся на UI control'ы (`target_accept=0.99`) которых **нет в интерфейсе** (RF-3 из recon — `target_accept` отображается в banner но не редактируется).

Теперь:
- **Primary line (всегда видна):** короткий manager-friendly verdict + конкретное действие на простом языке для каждой из 8 веток. Без жаргона. Без ссылок на non-existent UI control'ы. Маркеры ✓/⚠ перед текстом для быстрого visual scan.
- **Технические детали (collapsible через `<details>` / `<summary>`):** original verbatim текст со всеми terminology preserved для эконометриста. Tune/Draws/target_accept ссылки остаются (они корректны как diagnostic display values).

Reasoning: 8-сценарийная differentiation полезна для эконометриста (cosmetic divergence vs posterior geometry problem требуют разных действий). Plain replacement banner стёр бы эту nuance. Двухуровневая структура сохраняет полную semantic depth + presents short verdict первым потоком.

### Task 2 — MCMC params → preset radio в `ConfigPanel.svelte`

Раньше: три bare number inputs (`<input type="number" bind:value={mcmcChains}>` + Draws + Tune) внутри `showAdvanced` (Эксперт-режим) gate. Менеджер, открывший «Расширенные настройки», видел raw поля без объяснения что такое Tune/Draws/Chains.

Теперь — **two-tier nested gate**:
- `showAdvanced=true` (как раньше) → разворачивает MCMC section с **3 preset radio**:
  - «Стандартный» (Tune 2000 · Draws 2000 · Chains 4) — для большинства задач
  - «Высокая точность» (Tune 4000 · Draws 4000 · Chains 4) — для финальных моделей
  - «Эксперт-режим» (custom) — раскрывает оригинальные 3 number inputs
- Preset выбор **persisted в localStorage** key `econ-mcmc-preset` (читается на mount, пишется через `$effect`).
- `$effect` автоматически синхронизирует `mcmcTune`/`mcmcDraws`/`mcmcChains` с выбранным preset (кроме `custom` — там user controls raw values напрямую).

Manager-friendly path: не нужно знать что такое «Tune/Draws/Chains» — выбираешь категорию задачи и preset закрепляет проверенные defaults. Эконометрист: один дополнительный radio click → custom values available.

### Phase 3 closures (этим релизом)

- ✅ **Task 1A** DiagnosticsPanel layout reorg
- ✅ **Task 1B** ConvergenceDashboard banner двухуровневая structure
- ✅ **Task 2** MCMC preset radio в ConfigPanel

### Phase 3 remaining (Day 2)

- ⏸ **Task 3** Insights без жаргона — rewrite `insights-rules.js` (~25 user-facing strings с `R-hat`, `Markov Chain Monte Carlo`, `β-коэффициент`, `доверительные интервалы`, `posterior`, `omitted variable bias`, `priors`, `Adstock`, `Hill saturation` — Sonnet recon карта в Section 6)
- ⏸ **Task 4** Inline glossary popup pattern — новый component `GlossaryTerm.svelte` + sessionStorage-tracked first-appearance pattern в 5-10 ключевых местах

### Verification

- `npm run check` — **0 errors, 173 warnings** (identical to v2.1.0-rc4 baseline, no regression).
- Audit pass (Opus): обе Sonnet implementations spot-checked per `feedback_verify_external_repo_state_before_acting` Reference 4 — корректно. Минор known limitation: при перезагрузке custom MCMC values revert к defaults (pre-existing behaviour локальных `$state` vars, не ухудшено Phase 3).
- Recon отловил **3 stale claims** в audit doc до spawn'а Sonnet implementers: DiagnosticsPanel hint уже had business-language (gap был в layout приоритете, не в тексте); ConvergenceDashboard banner = 8 веток (не одна фраза); MCMC controls в ConfigPanel:528-554, не StepPlanInputs:539-555. Recon-first approach сэкономил ~30-60 min rework. **RF-3** flag (target_accept без UI input) предотвратил dead-end UX в banner copy.

---

## v2.1.0-rc4 — Improvements справочной системы под двойную аудиторию (2026-05-24)

Доработки after внутреннего help-system audit (Маша маленькая Opus 4.7 + 3× параллельных Sonnet recon). Цель: усилить позиционирование «топовый эконометрист руками менеджера» — справка должна одинаково работать для менеджера по рекламе/аналитика без эконометрического образования (90% аудитории) и для эконометриста (10%).

Полный отчёт: `Aurora_Dev/AURORA_MMM_HELP_SYSTEM_AUDIT_2026-05-24.md` (на EVO-X1).

### Позиционирование (visible пользователю)

- **`about.html` полный rewrite** — новое имя продукта «Aurora AI Econometrica — MMM Optimizer», новый tagline «Результат месячной работы топового эконометриста — силами менеджера за один день», обновлённая «Что это» секция с явной формулировкой «эконометрика уровня enterprise — доступна команде без эконометриста в штате». Удалены brand mentions Meta (Robyn) и Google (Meridian / LightweightMMM) — заменены на «иерархические приоры (по Hanssens), Hill-saturation, adstock decay, NUTS-сэмплер в NumPyro».
- **`README.md` reorganization** — заголовок теперь «Aurora AI — Monorepo (одна кодовая база, 5 product variants)» с таблицей 5 вариантов сборки (AI Agency / Legal Center / Creative Hub / Insights Hub / Econometrica MMM Optimizer). Это устраняет путаницу при первом знакомстве с репозиторием — раньше top-level README идентифицировал репо как «AI Agency Desktop», что не отражало flagship Econometrica variant.
- **`sidecar/econometrica/README.md`** — раньше 1 строка (только заголовок), теперь полное описание Python sidecar архитектуры, модулей, dev/production запуска, dependencies.

### Discovery educational content

- **`PipelineWhyThisStep` auto-open per first-visit** — самый ценный обучающий контент («Что мы делаем» + «Зачем нужно» + «На что обратить внимание» + «Что дальше», 4 блока на каждый из 6 шагов) теперь автоматически раскрыт при первом посещении каждого шага в данной инсталляции. После первого открытия — collapsed по умолчанию (опытный пользователь не раздражается повторами). Tracking через localStorage flag `aurora.whyThisStep.visited.<stepId>`. Master switch `hideEducationalHints` (Settings → Эксперт-режим) остаётся primary — если on, панель вообще не рендерится.
- **Sample data flow в Import шаге** — новая карточка «📥 Попробовать на примере» между drop-zone и .aurora archive загрузкой. 4 кнопки по верткалям (FMCG бренд / OTC фарма / Недвижимость / Ритейл-сеть) скачивают синтетические xlsx (~7-8 KB каждый). Структура файлов соответствует реальным проектам и проходит полный pipeline без правок. Снимает onboarding барьер «у меня нет данных под рукой».
  - Файлы: `static/sample-data/synth_fmcg_brand.xlsx`, `synth_otc_pharma.xlsx`, `synth_real_estate.xlsx`, `synth_retail_chain.xlsx` (исходники — `tools/synthetic_pilots/`).

### Tooltips на 3 пропущенных шагах (Import / Optimize / Report)

До этого релиза Tooltip-система покрывала только 2 из 6 шагов pipeline (Validate / Model). Sonnet sub-agent добавил **10 новых Tooltip wrap'ов** распределённых по Import/Optimize/Report (3 + 3 + 4) — strategic restraint, не везде, только где терминология может потребовать пояснения для менеджера.

- **Import:** «Тип моделирования», «Полное Bayesian MMM», «Упрощённое OLS-MMM» (3 wrap'а)
- **Optimize:** «От бюджета» (Forward), «От цели» (Goal-Seek), «What-if: изменённый бюджет» (3 wrap'а)
- **Report:** «MQS Score», «R²», «MAPE», «Прирост от оптимизации» (4 wrap'а, первые 3 переиспользуют existing tooltip ключи)

Новые tooltip ключи в `src/lib/data/tooltip-texts.js` (7): `import.modeling_type`, `import.bayesian`, `import.ols`, `optimize.forward`, `optimize.goal_seek`, `optimize.what_if`, `report.lift`.

### Hard bugs

- **Glossary shortcut documentation fix** — комментарии в `glossary.js:5` и `project-state.js:723` writting «Ctrl+K» — корректный shortcut «Ctrl+G» (Settings UI всегда показывал правильно, расхождение было только в внутренней документации).

### Не закрыто, отложено

- **5 P2 audit findings** (DiagnosticsPanel / ConvergenceDashboard Manager view rewrite, MCMC params → preset radio, insights без жаргона, inline glossary popup pattern, MCMC params explanation) — отложены отдельным sprint'ом (~1-2 дня). Требуют structural UI rewrite, не fit в текущий polish-релиз.
- **Видео-демо** — скрипт готов (`docs/VIDEO_DEMO_5MIN_SCRIPT.md`, 295 строк, расписан по тайм-кодам и voice-over), запись делается Антоном отдельно (не разработческая зона).

### Verification

- `npm run check` — **0 errors, 173 warnings** (все pre-existing, no new warnings introduced).
- Sonnet sub-agent tooltip work verified через spot-check (`feedback_verify_external_repo_state_before_acting` Reference 4 — sub-agent claims тоже требуют проверки).

### Полный audit doc

`Aurora_Dev/AURORA_MMM_HELP_SYSTEM_AUDIT_2026-05-24.md` (16 КБ): inventory справочной системы (10 strong points + ranked gaps), 4-фазный план улучшений (Phase 1-2 закрыты этим релизом, Phase 3 — следующий sprint, Phase 4 — strategic positioning), 5 risks с mitigation patterns.

---

## v1.3.0 — Next-gen MMM Optimizer: KPI semantics + Goal-Seek + safe corridor + educational system (2026-05-12)

Major UX upgrade — продукт следующего поколения, доступный не-эконометристам через
прогрессивную простоту и встроенную систему обучения.

### Новое

**KPI семантика (ADR-016)**: support для 10 KPI types в 2 семантических классах (плюс awareness — out_of_scope_v13, Phase B Aurora Brand Tracker).
Monetary (sales/revenue/profit) → ROI columns. Count (sales_packs/leads/
registrations/loyalty_cards/subscriptions/app_installs/custom) → CPU columns +
сравнение с user-провереnned value_per_count_unit (маржа/ценность лида/MRR).

**Mode = derived state (ADR-015)**: юзер выбирает KPI + per-channel input
(monetary vs physical), mode (ROI/Эффективность/Вручную) выводится автоматически.
Совпадает с industry standard (Robyn, PyMC-Marketing). Senior эконометристы —
Expert Mode override в Settings.

**Goal-Seek optimization (ADR-014)**: дуальная задача к forward. Дана цель
продаж → найти минимальный бюджет. Бисекция по бюджету, < 1s. Delta method
posterior CI.

**Safe corridor (ADR-014)**: math-валидные границы бюджета и цели per канал.
MVP: `[max(P5_obs, 0.5·µ), min(P95_obs, 1.5·µ)]`. Литература: Robyn, Hanssens 2003,
Jin 2017. UI зоны 🟢🟡🔴 на всех слайдерах.

**KPI-aware вердикты и метрики**: ROI / CPU / sales share — conditional rendering
per (mode, kpi_kind). Никаких ложных «Глубоко убыточный» на режиме Эффективность.

**Educational system**: Glossary 20 терминов (Ctrl+K), WhyThisStep панели на
каждом шаге pipeline, Intro Tutorial (8 slides «Что такое MMM»), inline tooltips
с linkом в глоссарий.

**Backend новые модули**: optimize/ package (bounds + inverse + auto_price),
engines/verdicts.py (KPI-aware dispatch), utils/{mode_inference,column_detection}.
4 new Tauri commands.

### Фиксы

- Window title: "Aurora AI Econometrica" → "Aurora AI Econometrica - MMM Optimizer".
- Onboarding step 1: split title на 2 строки (brand + product) + description rewrite.

### Backward compat

Bundle schema **не bumped** (ADR-017). v1.2 bundles читаются с defaults injected
in memory: KPI=`sales` (monetary), все каналы как monetary, derived mode = ROI.
Migration tool НЕ нужен.

### Tests

950 tests pass (929 v1.2 baseline + 21 new v1.3) + 5 known skips. 0 regression.
0 svelte-check errors.

### Известные ограничения

- Goal-Seek MVP — Delta method CI; full posterior re-bisection в Expert Mode → Phase B.
- Reports (HTML/PPTX/XLSX) не полностью KPI-aware — hotfix v1.3.1.
- Awareness KPI — out_of_scope_v13 (Aurora Brand Tracker Phase B).
- Educational system integration (WhyThisStep wire across шаги, Ctrl+K shortcut,
  mastery toggle) — hotfix v1.3.1.

---

## v1.0.10 — Stable: merge_rules e2e + UX wave + hardening (2026-04-23)

Промо rc1.4 в stable + Session B tooling hardening.

### Новое
- **Сравнение двух моделей (Comparison)**: side-by-side overlay с 6 секциями (KPI / каналы / waterfalls / ROI / optimize / insights) без переключения активного проекта.
- **Save/Load .aurora**: полный перенос проекта между машинами — atomic write + streaming + zip-slip защита + pre-validation.
- **HTML-экспорт отчёта**: самодостаточный 15-30 KB файл с интерактивными графиками через ECharts CDN.
- **Merge recommendation**: на Validate шаге — рекомендация «Объединить слабые каналы в Малые медиа». 4-layer materialization (modeler/decomposer/optimizer/awareness) без изменения исходных данных. Merged name наследует money-marker (до НДС / ₽ / руб).
- **UnitCostsPanel money-filter**: каналы с валютным маркером скрыты из dropdown «Добавить unit cost» (backward-compat с existing stored values).
- **Settings → Папка проектов**: кастомный путь хранения проектов.
- **Справочная система v1.0.10**: новые разделы Comparison / .aurora / HTML-экспорт / Слияние каналов в user-guide + index + pipeline + faq.
- **Session B hardening**: V40 AST linter (svelte/compiler `HtmlTag` ноды), lefthook pre-commit hook, release-notes.py generator, aurora-tag safety wrapper (fixed-string grep против regex injection).
- **JSON schema CI** для updater manifest: check-jsonschema на rosst-updates при push/PR в main.

### Фиксы
- **DecomposeStep onMount guard**: защита от spam `/compute/decompose` пока модель не обучена (регрессия ловилась 4 раза подряд — теперь + grep-guard в lefthook).
- **Pydantic TrainRequest/TrainStartRequest**: `merge_rules: dict[str, list[str]] = {}` поле явно задекларировано — fix silent-drop через `extra='ignore'`.
- **V40 linter bypass regex ужесточён**: требует формат HTML-комментария `<!-- aurora-fix:safe ... -->` (регрессия false-bypass через title-атрибут закрыта).
- **Schema URL pattern `^https://\S+$`**: защита от trailing whitespace в download_url.
- **rosst-updates CI fix**: drop `cache: 'pip'` (нет requirements.txt в deployment-repo, CI падал на всех коммитах Session B).
- **release-notes.py git PATH guard**: try/except FileNotFoundError + graceful warning.

### Tests (Track D)
- **Rust unit tests** для `project_load_comparison`: extract pure helper `load_snapshot_from_dir(dir)` + 3 теста (nonexistent / 0 scenarios / 100 → 50 newest по mtime).
- **DecomposeStep regression guard** в lefthook: grep на наличие `channelParams` guard'а — catches accidental removal at commit time.

### Rollback
Runbook: `memory/reference_econometrica_rollback.md`. Dry-run: `bash tools/rollback.sh 1.0.9`.

---

## v1.0.10-rc1.1 — Comparison polish + a11y (2026-04-22)

Follow-up к v1.0.10-rc1 (Comparison feature) — после self-audit всей сессии 17 findings; критическое fix'nуто сразу, остальное в этом rc.

### Comparison UX
- **Native `<dialog>`** для всех 3 модалок (ModelComparisonView, ProjectPickerModal, ConfirmDialog). Встроенный focus trap, Escape, `::backdrop` pseudo, a11y-правильные роли. Удалено 60+ строк custom overlay CSS + DOM listeners (keyboard Escape + body overflow hack).
- **DataTable reuse** в ComparisonView Section 2 (Channels) + Section 5 (Optimize budget). Auto-detect positive/negative по `+/-` prefix — убрана дубликация стилей.
- **optRows filter fix**: каналы с `current_spend` но без `optimal_spend` теперь показаны в таблице (раньше скрывались если проект не прошёл Optimize).

### Backend
- **`project_load_comparison`**: scenarios limit 50 newest (по mtime desc) вместо полного чтения директории. Предотвращает blocking FastAPI handler при 100+ сценариев.
- **`scenarios_total`** в payload — frontend показывает banner «показаны последние 50 из N» если overflow.

### Security (self-audit fix)
- **V40 XSS в `ModelComparisonView.renderMd()`** — исправлено в коммите `665f731` перед этим rc. Channel name из xlsx больше не попадает в `{@html}` без escape.

### DX / Infra (doc-only)
- **Rollback runbook**: `memory/reference_econometrica_rollback.md` — точные SQL/URL/SHA для v1.0.8 emergency rollback.
- **Dry-run rollback script**: `tools/rollback.sh` — показывает steps без execute.
- **Manual test checklist**: `tools/manual-test-comparison.md` — 8 flows (Comparison open, keyboard, picker, confirm, overflow, partial data, ECharts dispose, dropdown visibility) + regression checks.

### Artifact
- .exe **не пересобран** — изменения frontend-only + docs. Используется тот же installer что в v1.0.10-rc1 (SHA256 `102c20e74fba02059aa529659a2db2223c181af5bd28c3e7f13652ab0ae2b086`).

---

## v1.0.9-rc2 — Stability + multi-core MCMC (2026-04-22)

Follow-up к v1.0.9-rc1 (port isolation) — 7 технических фиксов по результатам live-теста IT Паши на CLOUDEAI RDP 2026-04-21.

### Stability
- **FastAPI**: глобальный exception handler возвращает JSON на 500 (фикс парсинг-ошибки GUI под RemoteApp). HTTPException pass-through сохранён — 400/404 работают как раньше.
- **Validator**: try/except вокруг записи `validation.json` + `default=str` для numpy-типов. Под roaming profile запись может упасть с PermissionError — result всё равно возвращается в GUI.
- **PyInstaller bundle**: arviz 0.23.4 split-пакеты (`arviz_base`, `arviz_stats`, `arviz_plots`) добавлены в `--collect-all` — фикс `FileNotFoundError` при импорте arviz.
- **Build script**: `PYTHONIOENCODING=utf-8` + `stdout.reconfigure` — фикс UnicodeEncodeError на cp1251 серверах. Post-build freshness check не пропускает stale exe в Tauri bundle.

### Performance
- **MCMC chain_method**: динамический выбор — `parallel` на multi-core CPU (`jax.devices() > 1`), `vectorized` fallback на одном устройстве.
- **JAX multi-core**: `XLA_FLAGS=--xla_force_host_platform_device_count=N` устанавливается в startup server.py до любого `import jax`. Дефолт `N = min(cpu_count, 8)`.
- **Ожидаемый speedup**: 3-8× на 4-8-ядерных серверах (rc1: 25% CPU = 1 ядро → rc2: все ядра под MCMC).

### Diagnostics
- `/health` возвращает версии `numpyro`, `jax`, `arviz`, `pytensor` (было: эти поля отсутствовали → FAIL в диагностическом чеклисте).
- `/health` packages handler расширен с `except ImportError` на `except Exception` — ловит partially-loaded modules.
- Startup log: `JAX devices: N × backend (expected=M)` + `AURORA_MCMC_CORES=N`.
- **Surgical asyncio filter**: убирает Windows-специфичный спам `_ProactorBasePipeTransport._call_connection_lost` из sidecar.log, реальные asyncio errors сохранены.

### Dependencies
- `requirements.txt`: добавлены pinned `numpyro==0.20.1`, `jax[cpu]==0.7.2`, `jaxlib==0.7.2`, `arviz==0.23.4` (+ 3 split-пакета), `pymc==5.28.4`, `pymc-marketing==0.19.2`, `pytensor>=2.24.0`. Pinned значения — production versions с CLOUDEAI.

### Env flags (новые)
- `AURORA_MCMC_CORES=N` — переопределить число виртуальных JAX host devices (дефолт `min(cpu, 8)`).
- `AURORA_MCMC_CHAIN_METHOD=parallel|vectorized|sequential` — форсировать chain distribution, минуя автодетект.
- (существующий) `AURORA_NUTS_BACKEND=auto|numpyro|pymc` — выбор backend.

### Files changed
- `sidecar/econometrica/server.py`
- `sidecar/econometrica/engines/validator.py`
- `sidecar/econometrica/engines/modeler.py`
- `sidecar/econometrica/build_sidecar.py`
- `sidecar/econometrica/requirements.txt`
- `CHANGELOG.md`

Rust-сторона (src-tauri/) не трогалась — v1.0.9-rc1 port isolation работает без изменений.

---

## v1.0.7 — S10: Help System + UX Polish (2026-04-20)

### Справочная система
- Новый справочный центр с 5 специализированными разделами: `data-preparation` (FMCG+Pharma примеры, Ratio 2/4/6 пороги, unit_costs таблица), `pipeline` (5 шагов с input/output/time-tag), `methodology` (Bayesian MMM, Adstock, Hill, NUTS, MQS, Trust Levels), `faq` (10+ вопросов с аккордеоном), `system-requirements` (Windows, RAM/CPU тиры, bundled Python 3.12 + JAX 0.7.2 + NumPyro 0.20.1)
- Единая кнопка «?» в header pipeline — динамически выбирает раздел по текущему шагу
- Аналогичная кнопка в header главного меню → index.html справки
- Navbar справки с логотипом Aurora + навигацией по группам (start / data / pipeline)
- Fix hover-dropdown bug: `padding-bottom + negative margin-bottom` на `.anav-group`, применено ко всем 12 nav.js в 10 продуктах Aurora
- Удалены упоминания инфраструктуры (vault/AES/Ed25519/APPDATA/Python sidecar/localhost/pickle/Tauri/SvelteKit) из пользовательской справки

### Сидекар и восстановление данных
- **Auto-respawn вычислительного модуля**: watchdog (tokio task, 15s tick), ensure_alive с async Mutex, zombie-kill через tasklist/taskkill с PID verify, banned cooldown (5 min после 5 неудач), `child.wait_timeout(3s)` через крейт `wait-timeout`
- `post_json` retry: при `is_connect`/`is_timeout` → `ensure_alive` → 1 retry
- `project_load_results` Rust команда — читает `results/*.json` при активации проекта, заполняет `modelData`/`decomposeData`/`optimizeData`/`validateData`
- `reconcileStepMetaFromDisk` — пересобирает stepMeta по фактам на диске, сбрасывает остаточные `error`-статусы без подкрепления данными (фикс «❌ Декомпозиция когда данных нет»)

### Кабинет эконометриста
- **6 новых команд-консультантов** (замена 7 старых mmm-*): `/interpret-model`, `/why-channel`, `/explain-ratio`, `/pilot-design`, `/next-quarter-plan`, `/data-gaps` + `/awareness-forecast`, `/awareness-to-sales`. Осмысление результатов pipeline без дублирования вычислений. Старые mmm-* команды остаются в `.claude/commands/` для ручного ввода (backward compat)
- Редизайн кабинета в стиле pipeline: логотип + «ECONOMETRICA» как в главном меню, project-chip рядом, footer-back-btn слева от command input
- Удалён нестабильный «Спросить AI» из InsightsPanel

### Pipeline UX
- `UnitCostsPanel` переработан: dropdown «+ Добавить канал» + кнопка ✕ на строке + hint «Обнаружено N TRP/GRP/OTS — добавить все». Autodetect сужен до TRP/GRP/OTS/РЕЙТИНГ/ОХВАТ. Панель видна только в режиме ROI. Preview «N юнит × цена = эквивалент ₽» на каждой строке
- `MQSBadge` + `ConvergenceDashboard`: значки «?» на каждом термине (R², MAPE, R-hat max, Divergences, Ratio) с tooltip'ами из ExpertModelPanel. R² и MAPE в правом верхнем углу графика «Факт vs Прогноз» (ECharts graphic overlay)
- Реалистичная оценка MCMC времени для JAX/NumPyro (~3 мин на 8 каналов вместо старых ~31)
- Scenario ROAS с `unit_costs`/money_mode: корректный подсчёт в рублях при смешанных единицах (TRP + рубли)
- Сценарии с человеко-читаемыми именами («Текущий 19.04 14:30»), кнопка «Сохранить оптимум»
- Убраны «8 слайдов» и «7 листов» из карточек экспорта и инсайта
- Кнопка «Назад» на шаге 0 pipeline → главное меню (вместо disabled)

### Критичные фиксы
- Onboarding tour запускается только при `channels.length > 0` (после train), не на пустом DOM
- Scroll race в OptimizeOnboarding: RAF polling с stable-rect detection (2 кадра или 500ms cap)
- `unit_costs` guard от отрицательных/NaN значений
- `kill_on_port` проверяет PID owner через `tasklist` (не убивает чужие процессы на :7430)
- `child.wait_timeout` вместо блокирующего `child.wait()` — защита от зависания shutdown
- Backward compat сценариев S8 через `_migrate_money_fields` на лету

### Content pack
- Обновлён: econometrist 11 → 8 команд, +6 новых описаний в command-meta-data.json, manifest version 3, Ed25519 re-signed

---

## v0.6.0 — Aurora Pipeline: Autonomous Agency Operations (2026-04-05)

### Pipeline Engine — контекстная цепочка между кабинетами
- **Context Chain** — каждый шаг workflow получает: бриф + бренд-контекст + summary предыдущих шагов + файлы предыдущего шага
- **`workflow_execute_with_brief`** — запуск workflow с контекстной цепочкой (brief inject в Claude message)
- **`ContextChain`** struct — накопление контекста, build_message_prefix(), summarize_step_exports()
- **Persistent exports** — результаты шагов сохраняются в `campaigns/.../steps/{id}/` ПЕРЕД close_session
- **Forward exports** — exports шага N автоматически копируются в inbox шага N+1
- **Startup interrupted scan** — пайплайны со статусом "running" при старте → "interrupted"

### Brief System
- **`campaign_set_brief`** — сохранение текста брифа + reference files в campaign dir
- **Brief panel** в workflow editor — collapsible текстовая область, auto-save при blur
- Бриф передаётся каждому шагу пайплайна как `[КОНТЕКСТ ПАЙПЛАЙНА]` prefix в message

### Export System
- **`campaign_export_zip`** — ZIP с организованными папками по шагам + автогенерированный summary.md
- **`campaign_open_exports`** — открыть папку persistent exports в Explorer
- **`campaign_get_status`** — статус пайплайна + timing + completed/total steps
- **Export panel** в workflow editor — "Экспорт ZIP" + "Открыть папку" после завершения

### Brand Management UX (v0.5.0 Polish)
- **Brand Update** (`brand_update`) — inline editing профиля бренда
- **Brand Delete** (`brand_delete`) — удаление с confirmation overlay
- **Document List** (`brand_list_docs`) — файлы с размером и датой, sorted by modified_at desc
- **Document Delete** (`brand_delete_doc`) — удаление отдельных документов
- **Drag-Drop Upload** — перетаскивание файлов в docs-section (hit-testing через isInsideElement)
- **BrandSelector** — dropdown для быстрого переключения бренда (Home topbar)
- **Welcome Screen** — inline создание первого бренда прямо на Home (1 клик)
- **Route Guards** — /brands и /brand/[id] redirect для non-Creative-Hub

### Security & Stability Fixes
- **brand_id path traversal protection** — `validate_brand_id()` на всех brand commands
- **Sidecar deadlock fix** — `Stdio::piped()` → `Stdio::null()` для RAG/Parser
- **open_cabinet brand context** — `write_brand_context()` при каждом открытии кабинета
- **Workflow prod-mode** — open_cabinet через vault/license в workflow execution (не только dev mode)
- **ensure_default_brand** — автоматическое создание для non-Creative-Hub
- **data_chat_deep concurrent safety** — уникальный workspace `data-chat-{uuid}`
- **UTF-8 safe excerpt** — char-based indexing в brand_history_search
- **sync_to_brand_history** — filesystem active brand (не blocking HTTP)

### Templates
- 5 workflow templates с `estimated_time_minutes`: Полная кампания (120м), Ребрендинг (150м), Креативная петля (90м), Юр. аудит (45м), Быстрый контент (40м)

### Тесты
- 48 тестов green (+8 новых: ContextChain, persist_step_exports, summarize, backward_compat, brand_update, brand_delete, doc_list, validate_brand_id)
- `npm run check` — 0 errors, 204 файла

### Затронутые файлы
- `src-tauri/src/commands/campaign.rs` — ContextChain, brief, persist_exports, export_zip, CampaignStatus, fix_interrupted
- `src-tauri/src/commands/brand.rs` — brand_update, brand_delete, brand_list_docs, brand_delete_doc, DocInfo, validate_brand_id
- `src-tauri/src/lib.rs` — workflow_execute_with_brief, context_chain in execute_workflow_steps, startup scan, sidecar stdio fix, brand context in open_cabinet
- `src-tauri/Cargo.toml` — +zip, +multipart
- `src/routes/workflow/[id]/+page.svelte` — Brief panel, export buttons, pipeline launch
- `src/routes/brand/[id]/+page.svelte` — Full rewrite: edit, docs list, delete, drag-drop
- `src/lib/components/BrandSelector.svelte` — NEW: brand dropdown
- `src/lib/creative-store.js` — updateBrand, deleteBrand, fetchRecentPipelines
- `src/lib/hints.js` — pipeline-brief, pipeline-export hints

---

## v0.5.0 — Creative Hub Integration (2026-04-05)

### Creative Hub — 6-й продукт-вариант
- **Filesystem-first Brand Layer** (`brand.rs`) — 11 Tauri-команд: brand_list, brand_create, brand_get, brand_activate, brand_get_active, brand_stats, brand_upload_doc, brand_search, brand_history_search, brand_health, data_chat_deep
- **Бренды = JSON на диске** — все CRUD работают без Python/RAG, RAG = опциональное усиление для vector search
- **Parser HTTP proxy** (`parser.rs`) — 5 команд: parser_run, parser_run_platform, parser_status, parser_history, parser_health
- **RAG/Parser Sidecar Lifecycle** — автостарт только для Creative Hub, graceful shutdown при закрытии
- **Product Identity** — `detect_product()` + `is_creative_hub()`, 6-й вариант в sync-variants.ps1

### Workflow Execution Engine
- **workflow_execute** + **workflow_control** — портированы из Brand Hub, зарегистрированы в invoke_handler
- **Рекурсивный обход** — Single, Parallel (tokio::spawn), Loop с max_iterations
- **Brand context injection** — `write_brand_context()` перед каждым Claude run
- **get_product_type** command — фронтенд определяет продукт при старте

### Frontend
- **creative-store.js** — productType, isCreativeHub, ragAvailable, parserAvailable, brands, activeBrand + initCreativeStore()
- **Brand Wizard** (`/brands`) — 2-шаговый визард создания бренда
- **Brand Detail** (`/brand/[id]`) — профиль, статистика, загрузка документов, RAG status
- **Data Chat Pro** — dual mode Lite/Pro, автоматический fallback при падении RAG
- **Canvas View** — WorkflowCanvas.svelte + CanvasToolbar.svelte, drag-and-drop, zoom, pan, minimap
- **CommandPalette** — навигация к Бренды

### Баг-фиксы
- **BUG-1:** `data_chat_deep` — 5-й аргумент `run_claude` исправлен: `false` → `None` (Option<String>)
- **BUG-2:** RAG sidecar теперь автоматически стартует при запуске Creative Hub
- **BUG-3:** sync-variants исключает brand-hub/ для всех вариантов кроме Creative Hub

### Тесты
- 39 тестов green (+7 новых для brand.rs: serialization, defaults, filesystem CRUD, roundtrip, count_files)
- `npm run check` — 0 errors

### Затронутые файлы
- `src-tauri/src/commands/brand.rs` — **НОВЫЙ** (11 команд, ~640 строк)
- `src-tauri/src/commands/parser.rs` — **НОВЫЙ** (5 команд, ~65 строк)
- `src-tauri/src/commands/mod.rs` — +brand, +parser
- `src-tauri/src/commands/online_auth.rs` — detect_product() + is_creative_hub()
- `src-tauri/src/lib.rs` — AppState.workflow_executions, workflow engine, sidecar lifecycle, command registration
- `src-tauri/Cargo.toml` — reqwest +multipart
- `src/lib/creative-store.js` — product awareness + brand state
- `src/routes/+layout.svelte` — initCreativeStore()
- `src/routes/brands/+page.svelte` — **НОВЫЙ**
- `src/routes/brand/[id]/+page.svelte` — **НОВЫЙ**
- `src/routes/data-chat/+page.svelte` — dual mode Lite/Pro
- `src/routes/workflow/[id]/+page.svelte` — Canvas View toggle
- `src/lib/components/workflow/WorkflowCanvas.svelte` — **НОВЫЙ**
- `src/lib/components/workflow/CanvasToolbar.svelte` — **НОВЫЙ**
- `src/lib/components/workflow/cabinetMeta.js` — **НОВЫЙ**
- `src/lib/components/CommandPalette.svelte` — +brands nav
- `Dev/sync-variants.ps1` — 6-й вариант Creative Hub

---

## v0.3.4 — Настраиваемые папки результатов + Изоляция файлов (2026-04-02)

### Настраиваемые папки результатов
- **Выбор папки для каждого кабинета** — в Настройках → «Папки результатов» можно выбрать, куда кабинет будет сохранять файлы (inbox и exports)
- **Модуль `user_config.rs`** — хранит пользовательские пути в `user_config.json` рядом с лицензией
- **Рефакторинг `lib.rs`** — 16 hardcoded путей `Desktop/AIAgency/` заменены на единую функцию `get_cabinet_workspace()`
- **3 новые Tauri-команды:** `get_cabinet_path`, `set_cabinet_path`, `reset_cabinet_path`
- Обратная совместимость: без настройки — всё работает как раньше (Desktop/AIAgency/)

### Изоляция файлов по продуктам
- **`list_recent_exports()`** — теперь фильтрует по лицензии: Legal видит только юридические файлы, Creative — только креативные
- **`copy_export_to_inbox()`** — использует настраиваемые пути
- **Runtime ограничения** — при запуске сессии в CLAUDE.md добавляется инструкция работать только с файлами рабочей директории
- **Все 11 CLAUDE.md** — добавлен блок «Ограничения доступа к файлам»

### Затронутые файлы
- `src-tauri/src/commands/user_config.rs` — **НОВЫЙ** модуль конфигурации путей
- `src-tauri/src/commands/mod.rs` — регистрация модуля
- `src-tauri/src/lib.rs` — рефакторинг путей, новые команды, фильтрация `list_recent_exports`, helper `get_allowed_cabinets()`
- `src-tauri/src/session/manager.rs` — runtime append ограничений в CLAUDE.md
- `src/routes/settings/+page.svelte` — секция «Папки результатов»
- `New_AI_Agency/*/CLAUDE.md` (11 файлов) — блок ограничения доступа

---

## v0.3.3 content update — Антизацикливание всех кабинетов (2026-04-02)

### Исправление промптов (content update, без пересборки .exe)
- **Все 11 кабинетов:** паттерн "ОСТАНОВИСЬ при неполных данных" заменён на "работай с имеющимися данными + помечай ограничения"
- **DocuMaster:** генерация документов без блокировки — пропуски помечаются `[НЕ УКАЗАНО: ...]`, нечёткие данные подставляются с `[ПРОВЕРИТЬ: причина]`
- **DocuMaster (doc-batch):** однопроходное выполнение — защита от зацикливания
- **DocuMaster (plan-to-doc):** при расхождении сумм документ сохраняется с пометками `[⚠ РАСХОЖДЕНИЕ]`
- **Эконометрист:** жёсткие блокировки → мягкие ограничения с пометками `[ОГРАНИЧЕНИЕ: ...]`
- **Юридические кабинеты:** черновик с `[ТРЕБУЕТ УТОЧНЕНИЯ: ...]` вместо остановки
- **Аналитические кабинеты:** анализ с оговорками об ограничениях данных
- **Vault'ы обновлены:** agency c5, docmaster c7, legal c3, creative c3, media c4

---

## v0.3.3 — Insights Hub + Эконометрист + Авто-обновление (2026-04-02)

### Новый кабинет: Эконометрист (econometrist)
- **8 команд:** `/mmm-prepare`, `/mmm-model`, `/mmm-decomposition`, `/mmm-optimize`, `/mmm-scenarios`, `/awareness-forecast`, `/awareness-to-sales`, `/mmm-report`
- Байесовское моделирование (PyMC-Marketing): Adstock, Hill function, MCMC
- Декомпозиция продаж, оптимизация бюджета, сценарное планирование
- Прогнозирование awareness + моделирование зависимости sales от awareness
- MQS (Model Quality Score) — 5-тировая шкала качества модели
- Подробная HTML-справка с примерами, словарём терминов и советами

### Ребрендинг
- **Aurora AI Media → Aurora AI Insights Hub** — все файлы, справки, настройки

### Справочный портал
- **nav.js** — единая навигация + поиск по 15 HTML-справкам
- **index.html** — хаб с карточками категорий
- **about.html** — манифест Aurora AI

### Авто-обновление приложений
- Supabase таблица `app_versions` + Edge Function `/app-update`
- `updater.rs` — Supabase основной, GitHub Pages fallback
- `UpdateBlockingOverlay` — исправлен баг с пустым URL
- CI — автоматический upsert `app_versions`

### Расширенный xlsx
- `rust_xlsxwriter`: автофильтры, заморозка строки, формулы SUM, условное форматирование

### Лицензирование
- `max_activations` → `max_sessions` + `session_id` — контроль одновременных запусков на одном ПК
- Backward compatibility в Edge Functions для старых клиентов

### Платформа
- **11 кабинетов**, **101 команда** (было 10 / 93)
- Insights Hub: 4 кабинета (было 3 + econometrist)
- 8 инсталляторов v0.3.3 (Aurora + ROSST)
- aurora-admin: кнопка «Выйти», мобильная адаптация, колонка «Макс.» для сессий

---

## v0.3.2 — Per-App Storage + WebView2 Fix + Svelte 5 Fix + Security Audit + Methodology Upgrade (2026-03-30)

**Версия:** v0.3.2 — изоляция данных, обработка ошибок запуска, исправление production build, аудит безопасности, методологический апгрейд кабинетов

### Критические исправления
- **Чёрный экран (WebView2)** — `.expect()` в `lib.rs:run()` заменён на `build_app() → Result`. При ошибке WebView2 автоматически чистится кэш `EBWebView` и делается повторная попытка. При неудаче показывается нативный Windows MessageBox с инструкцией (работает даже без WebView2).
- **Svelte 5 production crash** — `onDestroy()` на верхнем уровне вызывал `TypeError: Cannot read properties of null` в production build. Заменён на `return () => cleanup` из `onMount()` во всех компонентах: `+page.svelte`, `cabinet/+page.svelte`, `ChatPanel.svelte`, `DigitalClock.svelte`.
- **ChatPanel pendingCommand не срабатывал** — `onMount` был `async`, подписка на `pendingCommand` создавалась после `await` — кнопки команд не работали. Исправлено: `onMount` теперь синхронный, подписка создаётся сразу, async-часть (stream listeners) в IIFE.
- **vite.config.js — `resolve.conditions: []`** — в ROSST-вариантах `conditions` задавался пустым массивом в production mode, что ломало Svelte 5 module resolution. Исправлено: `resolve` применяется только в test mode (как в Agency).
- **Claude CLI path validation** — `find_claude_binary()` отклоняла `~/.local/bin/claude` (не в APPDATA/PROGRAMFILES). Добавлен USERPROFILE в trusted prefixes.

### Архитектурное изменение: Per-App Storage
- **Лицензии и волты теперь изолированы** по `identifier` из `tauri.conf.json`:
  - `%APPDATA%\com.aiagency.desktop\` — Full
  - `%APPDATA%\com.rosst.creative\` — Creative
  - `%APPDATA%\com.rosst.legal\` — Legal
  - `%APPDATA%\com.rosst.media\` — Media
- Используется `app_handle.path().app_config_dir()` / `app_data_dir()` (идиоматический Tauri v2)
- **Автомиграция:** при первом запуске v0.3.2 лицензия и волты копируются из legacy путей (`%APPDATA%\AIAgency\`, `%PROGRAMDATA%\AIAgency\`) в per-app директорию
- Исключены: конфликты лицензий между приложениями, ошибки расшифровки чужих волтов, повреждение данных при удалении одного из приложений

### Затронутые файлы (все 4 проекта)
- `src-tauri/src/lib.rs` — error handling, `app_handle` в командах
- `src-tauri/src/commands/license.rs` — per-app пути с миграцией
- `src-tauri/src/commands/vault.rs` — per-app пути с миграцией
- `src/routes/+page.svelte` — `onDestroy` → `onMount` return
- `src/routes/cabinet/+page.svelte` — `onDestroy` → `onMount` return
- `src/lib/components/ChatPanel.svelte` — `onDestroy` → `onMount` return
- `src/lib/components/DigitalClock.svelte` — `onDestroy` → `onMount` return

### Аудит безопасности (2026-03-30)
- **Изоляция вариантов** — Creative/Legal/Media показывают только свои 3 кабинета
- **Path traversal** — `sanitize_cabinet_id()` в vault.rs
- **PowerShell injection** — экранирование `'` в updater.rs
- **Session ACL** — icacls на sessions directory
- **TOCTOU** — tempfile::Builder для temp-директорий обновления
- **Mutex poison recovery** — `.unwrap_or_else(|e| e.into_inner())` (~17 мест)
- **DOMPurify** — ALLOWED_TAGS whitelist
- **Error boundary** — `+error.svelte`
- **Help файлы** — `help/index.html`
- **Migration logging** — warn!() для ошибок миграции vault/license

### v0.3.2 — Методологический апгрейд кабинетов (2026-03-30)

**Все 9 кабинетов:**
- Конфигурация моделей: Opus / Sonnet по задачам

**lawyer-contracts (2 новые команды + 3 улучшения):**
- `/contract-renewal-check` — анализ перед пролонгацией (WorldCC ContractConnect)
- `/contract-international` — международные контракты (CISG, UNIDROIT, Нью-Йоркская конвенция)
- Пленумы ВС/ВАС в каждом блоке анализа
- 4-осевой Risk Score (+ Business Impact, Reversibility)
- Переговорная тактика Fisher & Ury в /contract-counter

**lawyer-claims (1 новая команда + 3 улучшения):**
- `/nda-breach-response` — реагирование на утечку NDA
- Экономический анализ Landes-Posner в /settlement-plan
- ADR-модуль (медиация, арбитраж МКАС)
- Калькулятор неустоек (ст. 333 ГК + Пленум ВАС №81)

**lawyer-advertising (3 новые команды + 1 улучшение):**
- `/qa-ord` — ОРД-комплаенс (ФЗ №347, штрафы КоАП 14.3.1)
- `/qa-platform` — модерационные правила VK/Yandex/Telegram/Avito
- `/qa-visual-brief` — чек-лист визуальных материалов
- Саморегулирование: Российский кодекс рекламы 2023, ICC Code 2018

**creative-director (2 новые команды + 3 улучшения):**
- `/competitive-creative` — деконструкция кампании конкурента
- `/reference-library` — библиотека российских и международных кейсов
- Культурные коды России (Rapaille + Аузан)
- Поведенческий дизайн (Fogg, Kahneman, Shotton) + Behavioral Leverage 0-10
- Правополушарная оценка (Orlando Wood "Look Out" 2024)

**communication-strategist (2 новые команды + 3 улучшения):**
- `/cep-audit` — аудит Category Entry Points (Ehrenberg-Bass, Romaniuk 2018)
- `/crisis-strategy` — антикризисная стратегия (SCCT, Arthur W. Page)
- Sharp Compliance Score (7 правил Byron Sharp)
- Kantar MDS-оценка позиционирования
- Бенчмарки российского медиаландшафта

**focus-groups (5 новых команд + 1 улучшение):**
- `/concept-test` — A/B/C сравнительный тест (MaxDiff)
- `/packaging-test` — тест упаковки FMCG (SKIM Analytics)
- `/name-test` — тест названий (Catchword)
- `/ux-journey` — тест UX-сценариев (Norman, Krug)
- `/message-prioritization` — ранжирование сообщений (Kano Model)
- Roadmap реальной валидации с бюджетами

**media-analyst (2 новые команды + 3 улучшения):**
- `/data-analysis` — анализ сырых xlsx/csv
- `/benchmark` — медиа-бенчмарки РФ + SOV/SOM
- Data Storytelling (Knaflic 2015)
- ICE-приоритизация рекомендаций
- Каузальные цепочки (Field & Binet 2019)

**communication-analyst (3 новые команды + 1 улучшение):**
- `/narrative-tracking` — нарративный анализ (Entman Framing, Lakoff)
- `/influencer-impact` — анализ KOL (Katz & Lazarsfeld)
- `/pr-attribution` — атрибуция PR-активностей (AMEC 2020)
- SOV/ESOV расчёт (Binet & Field)

**social-listening (2 новые команды + 2 улучшения):**
- `/jtbd-extraction` — извлечение JTBD из отзывов (Christensen)
- `/trend-detection` — детекция трендов
- Детектор фейковых отзывов (Luca & Zervas) + Authenticity Score
- Granular Emotion Detection (Plutchik 8 эмоций + arousal)

---

## v0.3.1 — Light Theme + License Banner + User Guide (2026-03-27)

**Версия:** v0.3.1 — светлая тема, баннер лицензии, пользовательская инструкция

### Новое
- **Светлая тема** — toggle в topbar (луна/солнце) и в Настройках → Оформление. Сохраняется в localStorage, flash prevention через inline script
- **Баннер истечения лицензии** — жёлтый при < 14 дней, красный при < 3 дней, dismiss до перезапуска. Поле `days_remaining: i64` в LicenseStatus (Rust)
- **Пользовательская инструкция** — раздел в Настройках, открывает `help/user-guide.html` с подробным руководством по всем 9 кабинетам
- **Social Listening в User Guide** — секция 9 с 6 командами, обновлён Workflow 3 (Кризис)
- **Vault auto-fallback** — `resolve_vault_path()` пробует mapped имя, потом оригинальный cabinet_id

### Исправления
- **MSI-сборка убрана** — targets: ["nsis"] (WixTools падал, MSI не нужен)
- **Контрастность light theme** — hardcoded rgba заменены на CSS-переменные во всех компонентах (ChatPanel, FileList, CommandPanel, cabinet page)
- **Часы и ROSST** — графитовый цвет (#4A4A55) в светлой теме вместо ярко-зелёного

### Инфраструктура
- CSS-переменные: --panel-bg, --input-bg, --input-border, --hover-bg, --code-bg, --clock-color
- Theme store в `src/lib/store.js`, reactive binding в `+layout.svelte`
- `open_user_guide` Tauri-команда с dev-mode fallback (CARGO_MANIFEST_DIR)
- User Guide v0.3.1: 9 кабинетов, 3 workflow, 7 правил

---

## v0.3.0 — Social Listening + Feedback (2026-03-27)

**Версия:** v0.3.0 — новый кабинет Social Listening, форма обратной связи, UI-фиксы

### Новое
- **Кабинет Social Listening** — мониторинг отзывов, анализ тональности, отслеживание упоминаний бренда. 6 команд: /search-reviews, /analyze-sentiment, /report, /track-mentions, /competitors-buzz, /crisis-alert
- **Форма обратной связи** — в Настройках: выбор категории (проблема/пожелание/вопрос), описание, контакт. Бэкенд с rate-limiting (FB-001, FB-002)
- **SVG-иконка Social Listening** — «глаз» в CabinetCard, cyan-цвет (#06B6D4)
- **Горячие клавиши 1-9** — для 9 кабинетов (было 1-8)

### Исправления
- **NDA-плитка** — описание удлинено для выравнивания высоты карточек
- **Неразрывный пробел** — «анализ контрагентов» больше не разрывается между строками

### Инфраструктура
- `feedback.rs` — модуль отправки обратной связи (HTTP POST + rate limit)
- `errors.rs` — добавлены коды FB-001 (отправка не удалась), FB-002 (rate limit)
- `gen_license.py` — Media: 3 кабинета, Agency: 9 кабинетов
- `release.ps1` — исправлен DryRun (пропускает SHA256 шаг), добавлен UTF-8 BOM
- `social-listening.html` — встроенная HTML-справка
- Промпты: `New_AI_Agency/social-listening/` — CLAUDE.md + 6 slash-команд
- Синхронизировано во все 4 репо

### Статистика
- 9 кабинетов (было 8)
- 42 кода ошибок (было 40)
- 27 Rust-тестов — все проходят
- cargo clippy: 0 warnings
- svelte-check: 0 errors

---

## v0.2.1 — Error Codes + Renewal + Updates (2026-03-27)

**Версия:** v0.2.1 — коды ошибок, продление лицензий, система обновлений

### Новое
- **40 кодов ошибок `[XX-NNN]`** — каждая ошибка содержит код для быстрой диагностики (LI/VT/CL/FP/IN/SY/UP)
- **Встроенная справка по ошибкам** — `error-codes.html` с поиском по коду
- **Renewal лицензий** — продление без перепаковки vault'ов (режим 3 в gen_license.py сохраняет salt)
- **In-app обновления** — скачивание обновлений с прогресс-баром + автоустановка
- **Скрипт update.ps1** — обновление для IT: GitHub manifest / URL / локальный файл + SHA256 верификация
- **Расширенный manifest** — поля `checksum`, `min_version` в latest.json

### Инфраструктура
- `errors.rs` — модуль структурированных кодов ошибок (enum ErrorCode, 40 кодов, 2 теста)
- `futures-util` + `reqwest/stream` — потоковое скачивание с прогрессом
- Tauri-команды: `download_update`, `apply_update`
- CI: автообновление manifest при релизе (SHA256 чексумма)

### Документация
- `5_Документация/ERROR_CODES.md` — полная таблица кодов: код → причина → решение
- `2_Выдача_лицензий/CLAUDE.md` — секция Renewal
- `4_Выданные_лицензии/РЕЕСТР_ЛИЦЕНЗИЙ.md` — обновлённая процедура при истечении
- `3_Установка_клиентам/CLAUDE.md` — сценарий обновления

---

## v0.2.0 — Phase 4-7.5 (2026-03-26)

**Версия:** v0.2.0 — production polish, focus-groups cabinet, zero warnings

### Новое
- **Focus Groups кабинет** — 8-й кабинет в Agency-варианте для тестирования концепций на синтетических потребителях
- **Phase 4** — SvelteKit 5 миграция: runes, typed snippets, $app/state
- **Phase 5** — zero TS errors, unused imports cleanup, reactive state
- **Phase 6** — production polish: NSIS installer, HTML help, deploy scripts
- **Phase 7** — svelte-check CI gate, 5 Rust тестов, dist/ package
- **Phase 7.5** — 0 errors, 0 warnings svelte-check, ROSST-variant sync, NSIS rebuild

### Исправлено
- Все svelte-check warnings устранены (was 7 → 0)
- Синхронизация кода между Agency и 3 ROSST-вариантами
- Lock-файлы обновлены во всех вариантах

### Инфраструктура
- `__pycache__/` и `*.pyc` добавлены в `.gitignore` всех 4 репозиториев
- Трекаемые .pyc файлы удалены из git (55 файлов × 4 репо)

---

## v0.1.0 — Этап 2 (2026-03-22)

**Версия:** Этап 2 — глубокое усиление экспертизы + скил ИИ-фокус-групп

## Что изменилось

Обновлены **только** промпт-файлы (CLAUDE.md + .claude/commands/*.md) и HTML-справки.
Код приложений (Rust, Svelte, конфиги) **не затронут** — развёртывание идентично предыдущей версии.

---

## ROSST AI Legal (3 кабинета)

### Юрист — Договоры (lawyer-contracts)

**CLAUDE.md:**
- IACCM Top 10 Negotiated Terms — приоритизация рисков по международному стандарту
- Risk Quantification Framework: Severity (1-5) x Probability (1-5) x Financial Impact
- Negotiation Context Awareness — вопрос о переговорной позиции (заказчик/исполнитель, чей шаблон)
- Cognitive Debiasing — предупреждения о когнитивных искажениях при анализе
- Red Flags — 5 формулировок, которые никогда не должны быть в подписанном договоре

**Команды:**
- `/contract` — 9 блоков анализа (было 6), Risk Heatmap, ссылки на статьи ГК/АПК
- `/contract-checklist` — 25 пунктов сгруппированных по IACCM (было 12), веса Critical/Important/Desirable
- `/contract-counter` — BATNA/ZOPA анализ, 3 варианта защиты для каждого спорного пункта
- `/contract-template` — выбор уровня защиты, market-standard формулировки

### Юрист — Претензии (lawyer-claims)

**CLAUDE.md:**
- IRAC Framework (Issue → Rule → Application → Conclusion)
- 6 ключевых Постановлений Пленума ВС/ВАС с номерами
- Decision Tree для оценки перспектив спора (5 шагов)

**Команды:**
- `/pretension-write` — структура по IRAC, предупреждение о ст. 333 ГК, досудебный порядок
- `/pretension-analyze` — Decision Tree с 4 сценариями и финансовой оценкой каждого
- `/settlement-plan` — BATNA Analysis первым шагом, Timeline Risk
- `/nda-draft` — отраслевая специализация (IT/Pharma/Mfg), уровни жёсткости

### Юрист — Реклама (lawyer-advertising)

**CLAUDE.md:**
- Полная таблица штрафов по ст. 14.3 КоАП (физлица → юрлица → повторные → особые категории)
- Практика ФАС — 6 типичных оснований для привлечения
- ОРД/erid маркировка — практическое руководство (цепочка, формат, исключения)

**Команды:**
- `/qa` — 50+ пунктов (было 40), Environmental Claims, AI Content, Financial Risk Score
- `/qa-фарма` — 6 подкатегорий (ЛС рецептурные/безрецептурные, БАД, мед.изделия, лечебное питание, косметика)
- `/qa-финансы` — крипто/МФО/ИСЖ, калькулятор ПСК
- `/qa-template` — категория ОРД, ссылки на конкретные дела ФАС

---

## ROSST AI Creative (3 кабинета)

### Креативный директор (creative-director)

**CLAUDE.md:**
- Method Selection Matrix — decision tree: тип задачи → оптимальная комбинация методов
- Calibrated Scoring — якорные примеры для Score 3-10 и HumanKind 3-10
- Attention Economics — Hook (0-3s) → Tension (3-10s) → Payoff (10-30s), Sound-Off Design
- Cultural Context для РФ — юмор, табу, драйверы, платформенная специфика
- **ИИ-фокус-группы** — секция по использованию `/focus-group` для тестирования концепций

**Команды:**
- `/cycle` — Cultural Tension Mapping, Anti-Brief, калиброванные шкалы, Newspaper/Competitor тесты
- `/ad-variants` — платформо-специфичные hook-паттерны (Google/Meta/VK/Telegram/YouTube)
- `/format-creative` — Attention Economics timeline для каждого формата, Second Screen Behavior
- **`/focus-group` (НОВАЯ)** — тестирование креативных концепций на синтетических потребителях: AIDA-скоринг, ELM, concept testing (monadic/sequential monadic), brand linkage, Newspaper/Competitor тесты. Маркировка [HIGH/MEDIUM/LOW]

**Справка (HTML):**
- Добавлена команда «Фокус-группа» в таблицу команд
- Добавлена пошаговая инструкция по фокус-группам
- Добавлен пример запроса
- Обновлены ограничения

### Коммуникационный стратег (communication-strategist)

**CLAUDE.md:**
- Ehrenberg-Bass Institute Framework (CEPs, Mental Availability, Distinctive Brand Assets)
- Competitive Response Modeling
- Binet & Field 60/40 (brand building / performance activation)
- **ИИ-фокус-группы** — 4 режима (ИССЛЕДОВАНИЕ, ВАЛИДАЦИЯ, ЦЕНООБРАЗОВАНИЕ, ИНСАЙТЫ), диаграмма взаимодействия

**Команды:**
- `/positioning` — CEP Analysis, Distinctive Assets Audit, Positioning Durability Test
- `/brief` — Brief Stress Test (5 проверок SMP), Edge of Briefing
- `/messages` — Customer Journey Mapping, Message Hierarchy (4 уровня)
- `/strategy` — 7 этапов (было 5), Competitive Response, Measurement Framework
- **`/focus-group` (НОВАЯ)** — 4 режима тестирования стратегии: ИССЛЕДОВАНИЕ (глубинная группа 8-20 персон, Krueger & Casey), ВАЛИДАЦИЯ (стресс-тест позиционирования/messaging), ЦЕНООБРАЗОВАНИЕ (Van Westendorp + Gabor-Granger), ИНСАЙТЫ (laddering, проективные техники, Means-End Chain). Персоны по JTBD + TPB + Hofstede

**Справка (HTML):**
- Добавлена команда «Фокус-группа» в таблицу команд
- Добавлена пошаговая инструкция с описанием 4 режимов
- Добавлен пример запроса

---

## ROSST AI Insights Hub (2 кабинета)

### Медиа-аналитик (media-analyst)

**CLAUDE.md:**
- Data Storytelling Framework (Cole Nussbaumer Knaflic)
- Narrative Arc (Setup → Tension → Resolution)
- Audience-Adaptive Depth ([CEO]/[CMO]/[BM])
- Усиленная формула: Факт + Benchmark + Причина + Влияние + Рекомендация
- **Точность источников данных** — таблица надёжности (продажи=точные, ТВ=точные, Wordstat=высокая, медиабюджеты=средняя, digital=НИЗКАЯ с обязательными оговорками)
- **Верификация данных** — обязательная сверка каждой цифры с графиком/таблицей, особенно при редактировании существующих комментариев

**Команды:**
- `/analytics` — усиленная формула, Anomaly Detection, точность источников, верификация
- `/action-title` — 3 уровня SO WHAT (Operational/Tactical/Strategic), точность → жёсткость формулировок
- `/executive-summary` — 2 формата (Pyramid + SCR), Traffic Light Summary, верификация
- `/bridges` — Narrative Arc вместо механических связок, Causal Chain, точность мостов
- `/check` — **полная перезапись**: верификация цифр как приоритет №1, точность формулировок, 5 блоков проверки
- `/batch-analytics` — точность источников + верификация для каждого файла

### Коммуникационный аналитик (communication-analyst)

**CLAUDE.md:**
- AMEC Barcelona Principles 3.0 (7 принципов, цепочка Output→Outtake→Outcome→Impact)
- PESO Model (Paid/Earned/Shared/Owned)
- Sentiment Sophistication (Intensity 1-5, Aspect-Based, Emotion Detection)
- **Верификация данных** — обязательная сверка цифр с выгрузками

**Команды:**
- `/media-monitor` — **полная перезапись**: PESO Breakdown, Share of Voice, Narrative Analysis, Sentiment Sophistication, верификация
- `/sentiment` — **полная перезапись**: 3 измерения (Intensity/Aspect-Based/Emotion Detection), таблица с 7 колонками
- `/crisis-analysis` — **полная перезапись**: Fink Crisis Model (4 стадии), SCCT (тип→стратегия), Stakeholder Mapping
- `/effectiveness` — **полная перезапись**: AMEC Chain, запрет AVE, PESO Effectiveness

---

## Сквозные улучшения

1. **ИИ-фокус-группы** — новый скил для тестирования стратегий и концепций на синтетических потребителях. Интегрирован в оба кабинета ROSST AI Creative (Креативный директор + Коммуникационный стратег). Методологическая база: JTBD, TPB, ELM, AIDA, Means-End Chain, Van Westendorp, Gabor-Granger, Krueger & Casey moderation, Hofstede Cultural Dimensions.

2. **Верификация данных** — добавлена во все аналитические команды обоих медиа-кабинетов. Каждая цифра и процент сверяются с источником. При редактировании старых комментариев — старым цифрам не доверять.

3. **Точность источников данных** — все медиа-аналитические команды знают, что digital-мониторинг всегда показывает меньше реальных активностей, и адаптируют формулировки.

4. **Cross-cabinet синергия** — в каждый CLAUDE.md добавлены рекомендации по связке с другими кабинетами (Creative → Advertising проверка, Strategy → Creative бриф, Communication-Analyst → Strategy вход, Focus-Group → итеративная связка со стратегией и креативом).

5. **HTML-справки** — обновлены для обоих кабинетов ROSST AI Creative: добавлены команда, инструкция и пример для фокус-групп.

---

## Развёртывание

Развёртывание идентично предыдущей версии — см. `DEPLOY_CLAUDE.md`.
Никаких изменений в коде, зависимостях или конфигурации не требуется.
