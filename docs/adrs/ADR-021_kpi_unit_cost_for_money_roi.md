# ADR-021: kpi_unit_cost для ROI count→money conversion

**Status:** Accepted
**Date:** 2026-05-17
**Context:** v2.1.0-rc2 mixed mode completeness — closing money ROI display gap for count-type KPIs.

## Context

После ADR-020 (unit_costs at training), Aurora MMM Optimizer корректно обучает Bayesian MMM в mixed mode (count KPI + monetary/физика media с unit_costs). β-коэффициенты выходят в «KPI per ₽-equivalent media». Но **decomposer и optimizer выдают ROI / contribution в native KPI units** (упаковки на рубль, лиды на рубль).

Для **бренд-менеджеров фарма/FMCG** money ROI («сколько ₽ продаж принёс каждый ₽ медиа») — primary метрика принятия решений. Без неё:
- Decomposer показывает «вклад канала = 1500 упаковок» — юзер не знает money equivalent
- Optimizer считает «прирост = 8500 упаковок» — нужен conversion в money lift
- ROI / mROAS labels показывают `2.5 ед./₽` вместо `2.5×` для monetary KPI

В pilot 2026-05-17 это был один из выявленных pain points (~40% probable complaint). ADR-021 закрывает gap inline в v2.1.0 (не откладывая в v2.2.0).

## Decision

**Принимаем глобальный `kpi_unit_cost: float | None` (средняя цена единицы count KPI в ₽) который применяется в decomposer и optimizer для money ROI conversion. UI input — inline в под-шаге «Метрики каналов» Валидации.**

### Backend math

В decomposer:
```python
# Текущая (ADR-020 baseline):
contribution_count = β × hill(adstock(x_media) / media_means) × y_std  # native KPI units
spend_money = raw_spend × unit_cost  # media monetary

# После ADR-021:
if kpi_unit_cost is not None and kpi_kind == 'count':
    contribution_money = contribution_count * kpi_unit_cost
    roi_money = contribution_money / spend_money
    mroas_money = (marginal_contribution_count * kpi_unit_cost) / marginal_spend_money
else:
    # Legacy: roi в native units / ₽ (count-on-money) для count KPI
    roi_native = contribution_count / spend_money
```

В optimizer:
```python
# planned_kpi всегда в native count units (модель β learns в native)
planned_kpi_count = base_kpi_count + Σ(planned_β × ...)
if kpi_unit_cost is not None and kpi_kind == 'count':
    planned_kpi_money = planned_kpi_count * kpi_unit_cost
    lift_money = planned_kpi_money - current_kpi_money
else:
    lift_native = planned_kpi_count - current_kpi_count  # legacy
```

### Pickle contract

`model_data['kpi_unit_cost_snapshot']: float | None` — snapshot значения которое было задано на момент тренировки. Pair'd с ADR-020 `unit_costs_snapshot` (для media). Backward compat: None → legacy native-units path в decomposer/optimizer (no breaking change для existing pickles).

### Frontend behaviour

1. **Input placement:** inline в «Метрики каналов» под-шаге Валидации (subStep === 2 ValidateStepV13). Над UnitCostsPanel (per-channel CPP/CPM media). Видим **только при kpi_kind === 'count'**. Context-aware label: «Средняя цена упаковки» / «Средняя цена лида» / «Цена регистрации» — based on kpi_type.

2. **Default behaviour без kpi_unit_cost:**
   - ROI / mROAS / contribution показываются в native count units
   - Inline hint в Decompose «Укажите цену единицы [упаковки/лида] для money ROI» с кнопкой «Перейти к Валидации → Метрики каналов»

3. **Display switching (когда kpi_unit_cost задан):**
   - **Primary:** money value (`1.5 млн ₽`)
   - **Secondary в скобках:** count value (`(10 050 упаковок)`)
   - Применимо к: ChannelTimeline tooltip, WaterfallChart labels, ROI/mROAS metric badges, OptimizeStep lift summary, ReportStep cover

4. **Inline validation:** soft-warning если `kpi_kind=='count'` + `unit_costs` для media задан + `kpi_unit_cost` пуст → «Указали цену единиц для каналов, но не для целевой метрики. Money ROI недоступен. Заполните цену 1 единицы [KPI] чтобы видеть результаты в ₽.»

### Inflation

**Static value без inflation correction** в v2.1.0. Симметрично с media `unit_cost_inflation_pct` — backlog v2.2.0. Юзер задаёт one number, не year-by-year curve.

## Consequences

### Positive
- Mixed mode полностью закрыт: count KPI + media в любых units → money ROI display
- Decomposer / optimizer / report показывают money values рядом с count — usable для бренд-менеджеров
- Backward compat сохранён через None default
- Symmetric с ADR-020 unit_costs pattern (INV-36 training+load симметрия)

### Negative
- Юзер должен **активно** ввести kpi_unit_cost — если забыл, money ROI скрыт (с inline-хинтом). Это explicit choice пользователя, не silent surprise.
- Доп. complexity в decomposer / optimizer (3-5 code paths где contribution × kpi_unit_cost). Mitigation: comprehensive grep перед commit + 3-5 functional tests.

### Neutral
- Backward compat: existing pickles без `kpi_unit_cost_snapshot` → продолжают давать count ROI без conversion. Никаких exceptions.

## Alternatives considered

### (a) Auto-derive из KPI total / unit count
**Rejected:** требует знать sales_money колонку которая может не быть в данных. Risk = wrong derivation (среднее ≠ marginal).

### (b) Kanal-level kpi_unit_cost (different price per channel)
**Rejected:** complexity overflow + не имеет смысла (цена единицы — global business fact, не per-channel).

### (c) Per-period kpi_unit_cost (inflation curve)
**Rejected:** v2.2.0 backlog. Symmetric с media uc inflation отложен.

### (d) Принимать `kpi_unit_cost` как required field на под-шаге Валидации (block confirm если count KPI + media uc заданы + kpi_unit_cost пуст)
**Considered, partially adopted:** soft-warning в inline вместо hard block. Юзер может хотеть native count display (некоторые аналитические задачи).

## Implementation

См. tracker: `C:\Users\ackol\.claude\plans\kpi-unit-cost-execution-tracker.md`.

## Verification

3-5 backend pytest:
1. `test_decomposer_money_roi_with_kpi_unit_cost` — count KPI + kpi_unit_cost=120 → roi_money = expected_count × 120 / spend
2. `test_decomposer_native_units_without_kpi_unit_cost` — kpi_unit_cost=None → legacy roi_count_on_money path
3. `test_optimizer_money_lift_with_kpi_unit_cost` — planned lift в money
4. `test_pickle_kpi_unit_cost_snapshot_persisted` — snapshot в pickle при train
5. `test_decomposer_backward_compat_without_snapshot` — old pickles без snapshot работают legacy path

2 frontend vitest:
1. `kpiUnitCost` store persistence (localStorage + project.json)
2. ConfigPanel передаёт правильный kpi_unit_cost в train config

Manual smoke: train + decompose + optimize + report с kpi_unit_cost=120, all views показывают money primary + count в скобках.

## Related

- **ADR-020** unit_costs at training — pair'd для full mixed mode coverage
- **INV-36** training+load симметрия — kpi_unit_cost_snapshot follows same pattern
- **ADR-015** mode as derived state — kpi_kind=count детектируется и activates UI
- **Backlog v2.2.0:** kpi_unit_cost_inflation_pct year-by-year curve (если pilot потребует)
