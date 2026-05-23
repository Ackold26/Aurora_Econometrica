# Educational Texts Audit (v1.3.0)

**Date:** 2026-05-12
**Owner:** Маша маленькая
**Scope:** onboarding overlay, pipeline tours, help-econometrica HTML pages, inline tooltips, command-meta.

## Цель

Аудит существующих образовательных текстов:
1. Что меняется в связи с v1.3.0 (derived mode, KPI kinds, goal-seek, CPU, value_per_count_unit).
2. Что добавляется новое (Stage 4 educational system).
3. Какой content уже подходит и сохраняется без правок.

## Existing educational surfaces

### 1. `OnboardingOverlay.svelte` (4 шага intro)

Step 1: **Aurora AI Econometrica** intro (✅ updated 2026-05-12: split title + 2 предложения).

Step 2: **Модели и методы** - «NumPyro + JAX для байесовского вывода, Hill function, adstock...».
- **v1.3.0 changes:** добавить mention goal-seek и safe corridor.

Step 3: **Как начать** - «Создайте проект, загрузите Excel, пройдите 6 шагов: Import → Validate → Model → Decompose → Optimize → Report».
- **v1.3.0 changes:** обновить Validate подсказку с «выберите режим» на «выберите KPI и метрики каналов».

Step 4: **Клиент-ready отчёты** - описание форматов отчётов.
- **v1.3.0 changes:** добавить mention KPI-aware reports + goal-seek reports.

### 2. `pipeline-tours.js` (`TOURS` объект)

5 per-step tours (validate, model, decompose, optimize, report).

**v1.3.0 changes per step:**

- **validate**: REWRITE tour entirely. Old tour описывал ObjectiveSelector карточки; новый - KPI selector + per-channel input.
- **model**: minor update - добавить mention KPI-aware priors из registry.
- **decompose**: REWRITE для KPI/mode-aware verdicts и CPU column.
- **optimize**: ADD second portion про Goal-Seek toggle + safe corridor.
- **report**: minor update - KPI-aware sections + goal-seek reports.

### 3. `help-econometrica/` (11 HTML pages)

| Page | Content | v1.3.0 update |
|---|---|---|
| `index.html` | Landing | Add v1.3 highlights box (KPI kinds, goal-seek, safe corridor) |
| `data-preparation.html` | Import + Validate guide | REWRITE Validate section per ADR-015 |
| `methodology.html` | Bayesian + Hill + adstock | ADD: KPI kinds explained, value_per_count_unit, goal-seek bisection |
| `pipeline.html` | 6-step overview | REWRITE Optimize section (forward + goal-seek), update Decompose (CPU column) |
| `econometrica.html` | High-level product description | Update - emphasize «work with any KPI», not «for revenue» |
| `user-guide.html` | Step-by-step workflow | Full update per new Validate/Optimize UX |
| `system-requirements.html` | System reqs | No change |
| `about.html` | About page | Add v1.3.0 changelog highlight |
| `error-codes.html` | Error codes | Add new codes for v1.3.0 errors (invalid_kpi_kind, missing_value_per_count, etc.) |
| `faq.html` | FAQ | ADD: «Что такое CPU?», «Чем Goal-Seek отличается от Forward?», «Что такое derived mode?» |
| `econ-nav.js` | Navigation menu | Add 2 new pages: `glossary.html`, `goal_seek_guide.html` |

**2 NEW pages** в Stage 4:
- `glossary.html` - mirror SPA glossary.
- `goal_seek_guide.html` - dedicated guide для goal-seek workflow.

### 4. `command-meta.js` (inline tooltips)

Уже содержит short descriptions per команда / поле. v1.3.0:
- ADD: descriptions для новых полей (kpi_kind, value_per_count_unit, derived_mode, safe corridor, goal-seek target).
- UPDATE: descriptions, которые упоминают «ROI» - параметризовать по KPI.

### 5. `insights-rules.js` (insights templates)

Уже описано в `KPI_TEXT_AUDIT.md`. Здесь не дублирую.

## New educational surfaces (Stage 4 deliverables)

### A. `glossary.js` + `GlossaryPanel.svelte`

20 critical терминов MVP (см. `GLOSSARY_TERMS.md`). Каждый термин:
- `term`: название.
- `short`: 1 предложение.
- `long`: 3-5 предложений.
- `example`: пример.
- `related`: cross-links.

Access:
- Icon in header (доступ с любого шага).
- Inline link in tooltips.
- `Ctrl+K` shortcut.

### B. `WhyThisStep.svelte` × 6 главных шагов

Раскрывающаяся секция с 4 блоками:
1. «Что мы делаем»
2. «Зачем это нужно»
3. «На что обратить внимание»
4. «Что будет дальше»

Content в `contextual-help.json`.

### C. `InlineHelpIcon.svelte` (final implementation)

80+ полей в UI имеют (i)-иконку. Click → small popover с:
- Tooltip text.
- Glossary link.
- Optional «See methodology» link to help-econometrica page.

Content в `field-tooltips.json`.

### D. `AdaptiveInsightsPanel.svelte`

Правая панель, 3 контекстных подсказки per текущий step и project state. Trigger rules в `adaptive-insights-rules.js` (50+ rules).

### E. `IntroTutorial.svelte` (5-min walkthrough)

8 slides перед первым проектом:
1. Что такое MMM (1 sentence + image).
2. Как работает adstock.
3. Что такое Hill saturation.
4. Что такое priors и MCMC (very simply).
5. Декомпозиция продаж.
6. Forward оптимизация.
7. Goal-Seek.
8. KPI и метрики каналов.

Каждый slide: image + 2-3 предложения текста + кнопка «Дальше».

### F. Mastery toggle (Settings → Скрыть подсказки)

Default off. Когда on:
- WhyThisStep скрыт.
- Inline tooltips скрыты (доступны через right-click → «Показать описание»).
- Adaptive insights collapsed.

## Структура content writing (Stage 4)

Stage 4 = 6 дней, разбито:

| Подзадача | Дни |
|---|---|
| Glossary 20 terms content writing | 1.5 |
| Contextual help × 6 steps content | 1 |
| Field tooltips × 80 fields content | 1 |
| Adaptive insights rules × 50+ | 1 |
| Intro tutorial 8 slides content + images | 0.5 |
| Help-econometrica 11 pages updates + 2 new | 1 |
| **Total** | **6** |

## Открытые вопросы

1. **Glossary 20 vs 40 терминов.** Решено: MVP 20, rest → Phase B.

2. **Mastery levels: trinary vs binary.** Решено: binary toggle (Скрыть подсказки on/off).

3. **Help pages updates: full rewrite или delta?** Решено: delta (sections updates per page), не full rewrite.

4. **Intro tutorial - skippable?** Да, на каждом slide кнопка «Пропустить остальное».

5. **Mastery progression dialog после N проектов - нужен?** Нет (per binary toggle simplification).
