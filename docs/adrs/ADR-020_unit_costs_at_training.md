# ADR-020: unit_costs применяются при тренировке (mixed mode mathematical correctness)

**Status:** Accepted
**Date:** 2026-05-17
**Context:** Aurora MMM Optimizer v2.1.0-rc2 pilot 2026-05-17 audit C-1

## Context

`TrainRequest.unit_costs: dict[str, float]` приходит из ConfigPanel через `econ_train` endpoint в backend `engines.modeler.train_model`. До этой ADR `unit_costs` пропагировался через `config` объект в pickle, но **никогда не читался** в modeler.py при построении X_media. unit_costs использовались только в `engines.decomposer` для конверсии spend в ₽ при расчёте ROI.

Pilot 2026-05-17 с KPI «Продажи в уп. бренд» (count) + media в смешанных units (₽ бюджеты + TRPs физика без CPP/CPM) выявил критический баг:
- Bayesian MMM обучала Hill saturation функцию на **смешанных шкалах** (TRPs 22 100 vs ₽ 107 млн).
- Hill kernel `x^α / (γ^α + x^α)` калибровался относительно `mean(adstock(x))`, но если в одной модели каналы в TRPs И в рублях, normalization теряет смысл.
- Bayesian priors на α/γ заточены под нормированный 0..1 range, при mixed scales эта инвариантность нарушалась.

Аудит-агент virtual-pilot подтвердил: `grep "unit_costs" sidecar/econometrica/engines/modeler.py` возвращал **0 matches** вне config dict propagation.

## Decision

**Media columns с `unit_costs[col] > 0 и != 1.0` будут pre-multiply'иться ПЕРЕД adstock как в training, так и при load обученного pickle в decomposer.**

```python
# В modeler.py train_model (~line 337-345):
unit_costs = config.get('unit_costs', {}) or {}
unit_costs_snapshot = {}
for col in media_cols:
    raw_arr = df[col].fillna(0).values.astype(float)
    uc = float(unit_costs.get(col, 1.0) or 1.0)
    if uc > 0 and uc != 1.0:
        raw_arr = raw_arr * uc
        unit_costs_snapshot[col] = uc
    X_media[col] = apply_adstock(raw_arr, adstock_type)

# В pickle:
model_data['unit_costs_applied_at_training'] = bool(unit_costs_snapshot)
model_data['unit_costs_snapshot'] = unit_costs_snapshot

# В decomposer.py при load (~line 322-400):
if model_data.get('unit_costs_applied_at_training'):
    snapshot = model_data.get('unit_costs_snapshot', {})
    for col in media_cols:
        raw = df[col].fillna(0).values.astype(float)
        uc = float(snapshot.get(col, 1.0))
        if uc > 0 and uc != 1.0:
            raw = raw * uc
        # ... build X_media as before
```

**Дополнительно:** существующий `KPI_TYPE_NOT_IMPLEMENTED` guard в modeler.py:192 разделяется на:
- **awareness-only types** (`aided_awareness`, `top_of_mind`) — продолжают возвращать `KPI_TYPE_NOT_IMPLEMENTED` (требуют Phase A1a logit-Normal likelihood).
- **count/monetary types** (`sales`, `sales_packs`, `leads`, `profit`, `revenue`, `registrations`, `count_custom`) — allowed, проходят через monetary Normal likelihood. count units просто сохраняются в β scale (без kpi_unit_cost conversion в decomposer).

## Consequences

### Positive
- Mixed mode (count KPI + monetary/physical media) математически корректен: все media приведены к одной шкале (₽-equivalent) ДО Hill nonlinear transformation. β-коэффициенты в едином смысле (KPI per ₽-equivalent adstocked media).
- Bayesian Hill priors на α/γ остаются валидными — все каналы normalized в 0..1 после division by `media_means`.
- Decomposer load симметричен training — pickle reproducibility сохраняется (INV-23a invariant).
- `unit_costs_snapshot` в pickle гарантирует **byte-identical** reproduction даже если config.unit_costs пере-перерасчитан позже (INV-23a).
- Backward compat: pickles без `unit_costs_applied_at_training` flag → default `False` → legacy path (no pre-multiply при load).

### Negative
- Count KPI в pickle обучается на raw count values, decomposer возвращает contribution в count units (упаковки/лиды). **ROI в monetary terms** (₽/₽) **не доступен** без `kpi_unit_cost` (средняя revenue per unit). Это **отложено в backlog** v2.2.0.
- JAX float32 numerical stability: умножение raw TRPs × 120000 могут приблизиться к float32 max ≈3.4e38. На типичных датах safe (TRPs <100k, CPP <500k → 5e10), но для крупных охватов нужен monitoring через assert на max(X_media) < 1e18.

### Neutral
- Существующие production pickles (если есть) продолжают работать через legacy path. Re-train с новой backend version даст pickles с flag=True (если unit_costs заданы).
- Decomposer ROI computation **не меняется**: всё ещё считает spend × unit_cost для money ROI display. Math остаётся valid в обе стороны.

## Alternatives considered

### (a) Не трогать training, применять unit_costs только в decomposer
**Rejected:** Hill saturation kernel калибруется на mixed scale → α/γ priors invalidated → broken posterior. Лечит симптомы, не корень.

### (b) Pre-divide KPI на average price вместо pre-multiply media
**Rejected:** требует ввести `kpi_unit_cost` UI input + новое поле в TrainRequest + изменение decomposer ROI math. Большая работа, отложена в v2.2.0. Pre-multiply media — minimal disruption.

### (c) Hybrid: pre-multiply ТОЛЬКО когда есть physical media (`detection: classify_column == 'physical'`)
**Rejected as default:** smart-detection добавляет complexity. Простое правило «применить если uc!=1.0» достаточно — юзер сам решает указывать ли CPP/CPM.

### (d) Backend reject mixed mode (count KPI + physical media без CPP)
**Partially adopted:** мы НЕ блокируем при unit_costs={} (юзер может явно хотеть raw scale для experimental MMM). Но `KPI_TYPE_NOT_IMPLEMENTED` guard relax — пускаем count/profit/revenue в monetary code path (β в count units, decomposer без ROI conversion).

## Implementation

См. план: `C:\Users\ackol\.claude\plans\immutable-mixing-tide.md` Этап 1.
Tracker: `C:\Users\ackol\.claude\plans\v2.1.0-rc2-execution-tracker.md`.

## Verification

- 3 functional pytest в `sidecar/econometrica/tests/test_modeler_unit_costs.py`:
  1. `test_unit_costs_default_no_op`: train с unit_costs={} → β coefficients идентичны pre-fix baseline (no regression для existing models).
  2. `test_unit_costs_inverse_scale_beta`: train с unit_costs={TRPs: 120000} → β для TRPs канала в **inverse ratio** к baseline (β shrink × ~120000).
  3. `test_decomposer_symmetric_apply`: train → save pickle → decompose → contribution_sum + baseline ≈ y_actual_sum (energy conservation; ±1% tolerance).

- Manual pilot: re-run последнего pilot run (Кагоцел 4 каналов, KPI=sales, no unit_costs) → MQS/R²/MAPE в пределах ±5% baseline.

## Related

- INV-NN (TBD): «modeler унит_costs symmetric apply» — формализация этой ADR как invariant.
- ADR-015: mode_as_derived_state — режим (ROI/effectiveness/mixed) derived из kpi_kind + perChannelInput.
- ADR-016: kpi_kinds_binary_semantics — count vs monetary classification.
- Backlog v2.2.0: kpi_unit_cost flow для money ROI conversion при count KPI.
