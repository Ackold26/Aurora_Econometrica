# ADR-015: Mode (ROI / Эффективность / Вручную) как Derived State

**Status:** Accepted
**Date:** 2026-05-12
**Owner:** Маша маленькая (review Антон)
**Related:** ADR-014, ADR-016, REFACTOR_PLAN_v1.3.0.md

## Context

В v1.2.0 шаг Валидация требует от юзера явного выбора `analysisObjective` ∈ `{ROI, Эффективность, Вручную}` через `ObjectiveSelector` (3 карточки). Mode применяется через `objective-engine.js::applyObjectiveToColumns()`:
- ROI: keep budget colums, exclude volume.
- Эффективность: keep volume colums, exclude budgets.
- Вручную: no filtering (user decides per канал).

**Проблемы такой архитектуры:**

1. **Нестандартно** в industry. Flexible Bayesian MMM tools (PyMC-Marketing, Meta Robyn, Lightweight MMM, Jin et al. 2017) не имеют «выбора режима» как первичного вопроса. Юзер просто подаёт data frame с media variables в любых единицах; mode неявно следует из данных.

2. **Юзер должен иметь экспертизу** чтобы сразу решить «какой режим выбрать», прежде чем увидит данные. Это противоположно principle Progressive Simplicity (Aurora design principle).

3. **Mode-aware UI отсутствует** на шагах после Validate — Decompose / Optimize / Report не различают режимы, что приводит к артефактам (например, режим Эффективность показывает ROI=4172× из дефолтного `unit_cost=1`).

4. **Mismatch с реальными данными.** Клиент часто имеет: TV в ₽ (точный прайс), OLV в показах (Mediascope), Performance в ₽+кликах. «Выбрать ROI» приводит к подаче `olv_spend` (бартер, noisy → biased) вместо `olv_impressions` (точно).

## Decision

Mode становится **derived state** — выводится автоматически из per-channel input metric selection. Юзер не выбирает mode напрямую.

**Новая структура UX Валидации:**

1. **Step 1: KPISelector** — выбор target metric:
   - 💰 Выручка / прибыль (`kpi_kind=monetary`).
   - 📦 Продажи в штуках, лиды, регистрации, карты, подписки, custom (`kpi_kind=count`).

2. **Step 2 (только для count): ValuePerCountUnitInput** — поле с per-KPI label («Маржа на упаковку», «Ценность лида», «MRR на подписку» и т.д.) + auto-suggest по данным.

3. **Step 3: PerChannelInputSelector** — таблица каналов:
   - Auto-detected доступные метрики per канал (ры расходы, показы, клики, GRP).
   - Radio selector «Использовать: бюджет / физ. метрика».
   - Smart hints типа «у TV есть и ₽, и GRP — выбирайте более надёжную колонку».
   - **Скрывается полностью** если все каналы имеют только одну единицу (auto-mode без UI).

4. **Step 4: ModeDerivedExplanation** — plain-text:
   ```
   Derived mode:
     all monetary → ROI
     all physical → Эффективность
     mixed → Вручную
   ```

**Expert Mode override** (скрыт в Settings):
- Тогл «Я знаю, что делаю — выбрать режим явно» возвращает старый `ObjectiveSelector`.
- Для senior эконометристов, привыкших к v1.2 UX.

## Rationale

**Industry standard alignment:**

- **PyMC-Marketing** (Google's flexible Bayesian MMM): mode-free, юзер передаёт `media_data` frame с любыми units; модель работает с ними как-есть.
- **Meta Robyn**: разделяет `paid_media_spends` (₽-bound) и `paid_media_vars` (any units), не требует выбора режима.
- **Lightweight MMM (Google)**: `media_data` принимает любые единицы; нет explicit mode.
- **Jin et al. (2017) Google paper**: §3.1 явно говорит «media variables могут быть в любых units, что подаёт юзер — то и считается».

**UX argument:**

Principle of Least Knowledge Required — юзер должен думать в терминах **данных, которые у него есть** («какие колонки в моём Excel?»), не в терминах **архитектурного режима** («ROI vs Эффективность что это»). Mode — implementation detail, должен быть hidden.

**Methodological argument:**

Per-channel input metric selection — это **honest** mapping реальных данных клиента на модель. ROI/Эффективность/Вручную — это **post-hoc classification** того, что получилось. Семантика та же; UX чище.

## Alternatives Considered

| Альтернатива | Отвергнуто потому что |
|---|---|
| **A. Сохранить explicit toggle** (v1.2 текущий) | Нестандартно, требует экспертизы upfront, противоречит Progressive Simplicity |
| **B. Убрать Вручную, оставить 2 explicit toggle** | Теряем гибкость mixed-units; не решает базовую UX-проблему |
| **C. Derived state из per-channel inputs (выбран)** | Industry standard, методологически точнее, UX проще |
| **D. Полностью убрать concept of mode** | Mode-aware UI на Decompose / Optimize / Report по матрице полезен (ROI vs share-based семантика); концепт нужен внутренне |

## Consequences

**Positive:**
- UX align с industry standard.
- Юзер не блокируется на «какой режим выбрать».
- Backward compat: v1.2 bundles читаются (старый `mode` field мапится в per-channel inputs).
- Smart-default: 80% юзеров не видят per-channel selector (все каналы в одной единице).
- Mode-aware UI на остальных шагах активируется автоматически.

**Negative:**
- Требует rewrite ValidateStep.svelte (~600 LOC → новый 4-substep).
- Auto-detection колонок — новый source of bugs (несовпадение наименований).
- Senior эконометристы могут предпочесть старый UX → решено через Expert Mode override.

**Neutral:**
- Бизнес-логика unchanged. ROI / Effectiveness / Manual mode семантика та же — меняется только entry-point.

## Implementation

**Backend:**
- `sidecar/econometrica/utils/mode_inference.py` (NEW) — `derive_mode(per_channel_inputs: dict) → 'roi'|'effectiveness'|'manual'`.
- `sidecar/econometrica/utils/column_detection.py` (NEW) — auto-detect monetary/physical metrics по именам колонок (RU/EN regex).

**Frontend:**
- `src/lib/components/pipeline/ValidateStep.svelte` — REWRITE (4 sub-steps).
- `src/lib/components/pipeline/KPISelector.svelte`, `ValuePerCountUnitInput.svelte`, `PerChannelInputSelector.svelte`, `ModeDerivedExplanation.svelte` — NEW.
- `src/lib/project-state.js:396` — заменить `analysisObjective` store на `kpiKind` + `perChannelInput` + `derivedMode` stores.
- `src/lib/objective-engine.js` — DEPRECATE; новый `src/lib/mode-derivation.js`.

**Backward compat:**
- При загрузке v1.2 bundle с явным `analysisObjective='roi'` → все каналы prefilled как `monetary`, `derivedMode='roi'`.
- `effectiveness` → все каналы как `physical`.
- `manual` → читать per-channel из bundle (старая Вручную сохраняла per-channel).

**Edge cases:**
- Один канал → mode выводится по этому каналу.
- Колонка не классифицируется auto-detection → юзер выбирает manually + warning «не смогли определить тип».
- Все каналы только monetary → PerChannelInputSelector скрыт, mode=`roi` без UI.

## References

- PyMC-Marketing: <https://www.pymc-marketing.io>
- Meta Robyn: <https://facebookexperimental.github.io/Robyn/>
- Lightweight MMM: <https://github.com/google/lightweight_mmm>
- Jin et al. (2017): <https://research.google/pubs/pub46001/>
- Aurora ADR-014, ADR-016.
- REFACTOR_PLAN_v1.3.0.md — Open Question #6 (closed 2026-05-12).
