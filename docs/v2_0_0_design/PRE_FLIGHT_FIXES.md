# Pre-flight fixes для v2.0.0 (post-audit)

**Дата:** 2026-05-14
**Trigger:** `AUDIT_RESULTS_v1.md` — 2 BLOCKER + 17 HIGH findings нужны fix до Phase A start.
**Status:** Все 19 items addressed (see ниже).

---

## B2 — Wizard State Lifecycle ✅

Added `§0.6 Wizard State Lifecycle` to `WIZARD_FLOW_v2_FINAL.md`:
- State machine diagram (IDLE → WIZARD_PENDING → AUTO_DETECTING → {ESCAPE / WIZARD_ACTIVE / AUTO_FILLED} → RUNNING → COMPLETED)
- Lifecycle events table (10 events)
- State persistence layers (in-memory, localStorage, bundle.json)
- Back-navigation invalidation rules
- Manager ↔ Expert sync logic
- Edge case: data re-import

---

## H5 → B — Adstock priors monthly grain ✅ (resolved by code audit)

**Finding:** Verify if current adstock priors в `sidecar/econometrica/engines/modeler.py` calibrated для weekly или monthly grain (РФ default).

**Resolution:** Read `modeler.py:442` — explicit comment **«Hyperprior calibration per ADR §3.A1 + A2 (monthly data, mean ~0.20)»**.

**Verification through math:**
- Brand `mu_logit ~ Normal(0.7, 0.3)` → `sigmoid(0.7) ≈ 0.668` → half-life `0.693 / -ln(0.668) ≈ 1.72 months` ≈ 5-7 months full effect span. Reasonable для TV brand campaign в РФ.
- Performance `mu_logit ~ Normal(-1.4, 0.7)` → `sigmoid(-1.4) ≈ 0.198` → half-life `0.693 / -ln(0.198) ≈ 0.43 months` ≈ 2 weeks. Reasonable для Performance/Search.

**Conclusion:** Priors **уже calibrated для monthly grain** РФ-стандарта. NO recalibration needed для Phase A.

**Caveat для weekly data:** если customer грузит weekly data — текущие priors будут давать "wrong scale" decay. **Action:** Phase A task A6 — добавить branching logic in `modeler.py` для grain-aware priors (auto-scale если weekly detected). Documented в task list.

---

## B1 + L2 — Timeline revised ✅

ADR-019 §Phase plan updated:

| Phase | Old estimate | **New estimate** |
|---|---|---|
| Phase A — Backend foundation | ~1 неделя | **~1.5 weeks** (Phase A scope inflated после reuse audit) |
| Phase B — Wizard + Validate refactor | ~1.5 недели | **~1.5 weeks** (no change) |
| Phase C — Diagnostics & viz | ~1 неделя | **~1 week** (no change) |
| Phase D — Multi-scenario page | ~0.5 недели | **~0.75 week** (added edge cases B5) |
| Phase E — Audit + ship | ~1 неделя | **~1.25 weeks** (added Methodology Cert + verifier coord) |

**Total: 4.5-5 → 5.75-6.5 weeks с 0.5-1 week buffer.**

Updated в `ADR-019_explicit_mode_wizard_v2.md` Phase plan table.

---

## B3 — Migration logic algorithm spec ✅

Detailed algorithm для v1.3.x → v2.0.0 project migration (added to `WIZARD_FLOW_v2_FINAL.md` § M):

```js
function migrateV13ToV20(projectState) {
  const pcInput = projectState.perChannelInput || {};
  const channels = Object.keys(pcInput);

  // Case 1: empty project (new)
  if (channels.length === 0) {
    analysisMode.set('roi');
    expertMode.set(false);
    return { migrated: false, scenario: 'new' };
  }

  // Case 2: pure monetary
  if (channels.every(ch => pcInput[ch] === 'monetary')) {
    analysisMode.set('roi');
    expertMode.set(false);
    return { migrated: true, scenario: 'pure_monetary_to_roi', toast: false };
  }

  // Case 3: pure physical
  if (channels.every(ch => pcInput[ch] === 'physical')) {
    analysisMode.set('effectiveness');
    expertMode.set(false);
    return { migrated: true, scenario: 'pure_physical_to_effectiveness', toast: false };
  }

  // Case 4: mixed (some monetary + some physical) — auto-Expert
  const monetary_count = channels.filter(ch => pcInput[ch] === 'monetary').length;
  const physical_count = channels.filter(ch => pcInput[ch] === 'physical').length;
  if (monetary_count > 0 && physical_count > 0) {
    analysisMode.set('mixed');
    expertMode.set(true);
    return { migrated: true, scenario: 'mixed_to_expert', toast: true };
  }

  // Case 5: null/unknown values (legacy bundles without per-channel)
  // Fallback: auto-Expert + warning
  analysisMode.set('mixed');
  expertMode.set(true);
  return { migrated: true, scenario: 'unknown_legacy', toast: true };
}
```

**Toast spec (RU + EN):**

RU: «Включён Expert mode. Ваш проект использует смешанный режим единиц медиа-каналов (часть в ₽, часть в физических метриках). Управление per-channel доступно в Expert UI. Переключить режим — Settings.»

EN: «Expert mode activated. Your project uses mixed media unit modes (some monetary ₽, some physical metrics). Per-channel control available in Expert UI. Toggle mode in Settings.»

**Toast UX:** top-center banner, 10 sec duration default, dismissible, sticky-replay в Settings until dismissed.

**4 test scenarios:** все 5 cases covered + сanity test «v1.3.x bundle с missing perChannelInput field → fallback to Case 5».

---

## B4 — Signed factor priors placeholder doc ✅

`WIZARD_FLOW_v2_FINAL.md` §5.2 already specifies priors. Adding **«Status: placeholder calibration»** note:

```
**Status (2026-05-14):** placeholder values used in v2.0.0 Phase A:
- Media channels: LogNormal (existing, monthly-calibrated)
- Positive controls: HalfNormal (existing)
- Competitor: Normal(μ=-0.5σ, σ=1.0) — generic negative-leaning prior
- Price/weather/macro: Normal(μ=0, σ=1.0) — uninformative

Recalibration scheduled в Phase E (E2 — math review on pilot data).
Pilot: Кагоцел / Венарус projects, verify posterior coverage matches expert intuition.
If significant deviation — adjust mu/sigma per category, re-train models, document в ADR-019 v2.
```

Added to `forecast_planned_activities.yaml` spec footer + ADR-019 §11 Implementation.

---

## B6 + N8 — `forecast_planned_activities.yaml` spec ✅

**Task profile NEW** — добавляется в Phase A item A11.

```yaml
id: optimize.forecast_planned_activities.v1
app: aurora_econometrica_optimizer
task: forecast_planned_activities
version: 1.0
description: |
  Forecast по плану пользователя — модель обучается на исторических данных
  бренда, customer загружает Excel с плановыми активностями, модель
  прогнозирует KPI per-period.
  
  Workflow:
    1. Калибровка MMM-модели (та же что в budget_optimization).
    2. Загрузка plan Excel с future-period rows (даты после cutoff).
    3. Validator: planned columns ⊆ trained channels, unit types match.
    4. Apply model: adstock continuation от historical tail + Hill saturation
       + signed factor contributions (если планируются).
    5. Output: per-period predicted KPI с 90% CI + per-channel contribution stack.

scenario: forecast_user_plan

source_detection:
  method: signature_based_auto_detection
  task_profile_source_agnostic: true

cutoff_detection:
  method: last_row_with_observed_sales

target_brand_historical:
  same_as: budget_optimization.yaml
  notes: Identical requirements (≥24 months, ≥50% active advertising, etc.)

target_brand_planned:
  description: |
    Plan Excel с future-period rows. Validator-enforced structure:
    - Те же channel columns что в trained model
    - Тот же тип units per channel (monetary or physical)
    - Date column с datetime values после last_observed cutoff
    - Опционально: non-media planned columns (distribution, trade_activity, price)

  required:
    - field: planned_period_dates
      type: timeseries
      validation: dates > last_observed_cutoff
    - field: planned_media_per_channel
      type: timeseries_multivar
      validation: |
        - columns ⊆ trained_model.channel_set
        - unit_types[ch] == trained_model.channel_unit_types[ch]
    
  optional:
    - field: planned_distribution
      type: timeseries
      fallback: forward_fill_historical_average
    - field: planned_trade_activity_score
      type: timeseries
      scale: 0_to_5_relative
      fallback: forward_fill
    - field: planned_price_average
      type: timeseries
      fallback: forward_fill

  validators:
    - plan_in_trained_model:
        rule: planned channels MUST be subset of trained model channels
        fail_action: block + suggest_retrain
        message: |
          Канал «{channel}» в плане отсутствует в обученной модели.
          Возможные действия:
          - Удалить канал из плана
          - Переобучить модель с этим каналом (требует исторических данных)
    - unit_compatibility:
        rule: planned unit type per channel MUST match trained model unit type
        fail_action: block + suggest_retrain
        message: |
          Канал «{channel}» в плане в единицах «{plan_unit}»,
          а модель обучена в «{trained_unit}». Прогноз математически некорректен
          без переобучения.
    - extrapolation_warning:
        rule: planned spend per channel MUST be in [0.5×, 2×] of training_max_spend
        warn_action: highlight_warning
        message: |
          Канал «{channel}» в плане {plan_value}, что значительно превышает
          максимум обучения {training_max}. Hill saturation за training range
          экстраполируется — прогноз может быть неточен.
    - non_media_warning:
        rule: if planned_period > 4 monthly periods AND no non_media planned values
        warn_action: highlight_warning
        message: |
          Для долгого планового периода (>{N} периодов) рекомендуется указать
          plan-period значения для дистрибуции / trade / цены — иначе модель
          использует historical averages, что может не отражать реальность.

forecast_output:
  description: |
    Per-period predicted KPI + per-channel contribution + signed factor contributions.

  forecast_results:
    - field: predicted_kpi_per_period
      type: timeseries
      uncertainty: bayesian_credible_interval_90pct
      grain: same_as_data_signature
    - field: per_channel_contribution_per_period
      type: dict_channel_to_timeseries
    - field: signed_factor_contribution_per_period
      type: dict_factor_to_timeseries
      notes: Includes holiday effects + competitor activity + price/weather/macro
    - field: base_contribution_per_period
      type: timeseries

  forecast_horizon:
    method: plan_period_length_plus_adstock_tail

quality_gates:
  validator_must_pass:
    rule: All plan_in_trained_model + unit_compatibility checks pass
    fail_action: block_forecast_run
  
  no_extrapolation_block:
    rule: extrapolation_warning is warn-only, never blocks
    notes: Customer free to extrapolate, with explicit warning.

output_bundle_target:
  app: aurora_econometrica_optimizer
  bundle_layout_id: forecast_v1.0
  required_files:
    - data/target_brand_full_timeline.parquet
    - data/planned_activities.parquet
    - data/planned_validators_results.json
    - data/forecast_predicted.parquet
    - data/forecast_contributions.parquet
    - manifest.json

ux_hints:
  estimated_time_to_collect: "30-60 минут (plan file должен existing в business processes)"
  difficulty_for_manager: low
  common_blockers:
    - Plan содержит канал, не использовавшийся в trained model → переобучение
    - Plan unit type mismatch (план в TRP, модель в ₽) → переобучение
    - Plan period короче 1 единицы grain → нет смысла прогнозировать

methodology_references:
  shared_with_optimizer: true
  notes: Same Bayesian MMM machinery (adstock, Hill, hierarchical priors).

references:
  - 04_Task_Profiles/aurora_optimize/budget_optimization.yaml
  - docs/v2_0_0_design/WIZARD_FLOW_v2_FINAL.md §2.4 Task 4
```

This becomes new file `D:\Docs\Aurora_Ai\Aurora Data Studio\04_Task_Profiles\aurora_optimize\forecast_planned_activities.yaml` в Phase A item A11.

---

## H1 — Backtest holdout algorithm pseudocode ✅

Added to `WIZARD_FLOW_v2_FINAL.md` §6.1:

```python
def determine_backtest_holdout(data_signature):
    """
    Determines holdout period for backtest validation.
    Default: 4 months for monthly grain (РФ standard).
    Auto-adapt for weekly grain; auto-extend for long histories.
    """
    grain = data_signature['history_grain']  # 'monthly' | 'weekly'
    history_length = data_signature['history_months']  # in months always
    
    if grain == 'monthly':
        # Default 4 months
        default_holdout_months = 4
        
        # Minimum training period must be ≥24 months (per budget_optimization.yaml)
        max_holdout_for_training = max(0, history_length - 24)
        
        # Auto-extend for long histories
        if history_length >= 48:
            extended_holdout = min(8, max_holdout_for_training)
            holdout = extended_holdout
        else:
            holdout = min(default_holdout_months, max_holdout_for_training)
    
    elif grain == 'weekly':
        # 4 months = ~16 weeks default
        weeks_in_history = history_length * 4.33
        default_holdout_weeks = 16
        
        # Minimum training ≥52 weeks
        max_holdout_for_training = max(0, weeks_in_history - 52)
        
        if weeks_in_history >= 208:  # 4 years
            extended_holdout = min(32, max_holdout_for_training)
            holdout = extended_holdout
        else:
            holdout = min(default_holdout_weeks, max_holdout_for_training)
    
    if holdout < 2:  # less than 2 periods
        return None  # backtest not feasible, flag в diagnostics 🔴
    
    return holdout
```

Acceptance test scenarios (Phase A unit tests):
- 25 monthly history → holdout 4 monthly (training 21)
- 36 monthly history → holdout 4
- 48 monthly history → holdout 8
- 60 monthly history → holdout 8
- 52 weekly → holdout 0 (not enough), backtest skipped
- 104 weekly (2 years) → holdout 16
- 208 weekly (4 years) → holdout 32
- 24 monthly (exactly min) → holdout 0 (not enough), backtest skipped

---

## H3 — Holiday collinearity check spec ✅

Added to `holiday_calendar_ru.py` design:

```python
def detect_holiday_collinearity(holidays_df: pd.DataFrame, threshold: float = 0.5):
    """
    Detect overlapping holiday windows that могут create multicollinearity.
    Returns warnings; не blocks (only documents в diagnostics).
    """
    warnings = []
    
    for h1, h2 in combinations(holidays_df.columns, 2):
        overlap_pct = ((holidays_df[h1] == 1) & (holidays_df[h2] == 1)).sum() / max(1, holidays_df[h1].sum())
        
        if overlap_pct > threshold:
            warnings.append({
                'holiday_a': h1,
                'holiday_b': h2,
                'overlap_pct': overlap_pct,
                'severity': 'warn',
                'message': f'{h1} and {h2} overlap {overlap_pct*100:.0f}%, may cause multicollinearity'
            })
    
    # Specific known overlaps to flag explicitly:
    # holiday_newyear_preshop (15-31 Dec) ∩ holiday_school_breaks (winter break ~20 Dec-8 Jan)
    # ~50% overlap by design
    
    return warnings
```

Acceptance:
- Известные overlaps documented как «expected, model adapts»
- Unknown overlaps surface как warnings в DiagnosticsPanel
- Math fallback: если 2 holidays >80% overlap, merge them into single dummy

---

## H6 — Variable classifier test coverage spec ✅

Phase A acceptance criteria updated:

```
- pytest на column_detection.py passing
- 25+ test cases per target metric type (13 types × 25 = 325 cases minimum)
- 15+ test cases per media format (15 formats × 15 = 225 cases minimum)
- Edge case scenarios MUST be tested:
  - RU column names with typos (продажы / выручкa)
  - EN column names with synonyms (revenue/sales/turnover)
  - Mixed case (Sales_Rub, SALES_RUB, sales_RUB)
  - Adjusted variants (sales_rub_adjusted, sales_rub_promo_adj)
  - Numeric column without name hints
  - Multiple potential targets in same dataset (must surface all candidates)
- Synthetic dataset generator file: test/fixtures/variable_classifier_corpus.py
- Real-world subsample: Кагоцел + Венарус column names (anonymized)
```

---

## H7 — Decomposer JSON output structure spec ✅

Added to `decomposer.py` design (Phase A item A7):

```json
{
  "version": "2.0.0",
  "kpi_total": 245000.5,
  "kpi_ci_90": [230000, 262000],
  "base_contribution": {
    "value": 165000,
    "pct": 67.3,
    "ci_90": [157000, 173000]
  },
  "channel_contributions": {
    "TV": {"value": 24500, "pct": 10.0, "ci_90": [22000, 27000], "type": "media"},
    "Digital": {"value": 49000, "pct": 20.0, "ci_90": [45000, 53000], "type": "media"},
    "OOH": {"value": 12250, "pct": 5.0, "ci_90": [10500, 14000], "type": "media"},
    "Performance": {"value": 26950, "pct": 11.0, "ci_90": [24500, 29400], "type": "media"}
  },
  "signed_factor_contributions": {
    "competitor_trp": {"value": -26950, "pct": -11.0, "ci_90": [-32000, -22000], "type": "signed_negative"},
    "price_average": {"value": -7350, "pct": -3.0, "ci_90": [-9500, -5200], "type": "signed_unconstrained"},
    "holiday_newyear_preshop": {"value": 4900, "pct": 2.0, "ci_90": [3200, 6600], "type": "holiday"},
    "holiday_march8": {"value": 7350, "pct": 3.0, "ci_90": [5500, 9200], "type": "holiday"}
  },
  "positive_control_contributions": {
    "distribution": {"value": 19600, "pct": 8.0, "ci_90": [17000, 22000], "type": "positive_control"},
    "trade_activity": {"value": 4900, "pct": 2.0, "ci_90": [3500, 6200], "type": "positive_control"}
  },
  "metadata": {
    "model_version": "1.3.0",
    "training_samples": 36,
    "mcmc_diagnostics": {"r_hat_max": 1.02, "ess_min": 1240},
    "ppc": {"r2": 0.91, "residual_durbin_watson": 1.95}
  }
}
```

**Total verification:** sum(all contributions including negative) should equal `kpi_total` ± 0.5% (rounding).

Used by WaterfallChart.svelte (rendering negative bars) + Report sections.

---

## M6→H — analysisObjective consumer grep audit ✅

```bash
grep -rn "analysisObjective" src/
```

Results:
- `src/lib/components/pipeline/InsightsPanel.svelte:14,189` — reads via `$analysisObjective`
- `src/lib/components/pipeline/UnitCostsPanel.svelte:25,391,404` — reads
- `src/lib/components/pipeline/ValidateStep.svelte:22,130,176,190,191,298,300,309,311,320,322,332,334` — reads/writes
- `src/lib/components/pipeline/ValidateStepV13.svelte:32,442` — reads

**Migration plan для Phase B:**
1. `analysisObjective` остаётся как derived alias (`$analysisObjective = derive analysisMode + expertMode`)
2. New code (wizard) uses `analysisMode` directly
3. Legacy callers (InsightsPanel, UnitCostsPanel, ValidateStep) — UPDATE references к `analysisMode` (one-line replacement) в Phase B
4. After ValidateStep.svelte (legacy) deprecation в Phase E — `analysisObjective` alias can be removed

Tracked в Phase B item B-A1.

---

## L4→H — persistence.py v1.3→v2.0 compat test plan ✅

Acceptance test для Phase A:
1. Take real v1.3.x pickle file (если есть production project) или synthesize one
2. Load в v2.0.0 code path
3. Verify:
   - All v1.3 fields accessible without error
   - New v2.0.0 fields (signed_factor_contributions, holiday_dummies, mcmc_diagnostics) absent gracefully (return None / empty dict, не crash)
   - Backward compat helper `load_model_with_compat()` correctly maps schema
4. Test in reverse: save v2.0.0 model, load via v1.3 code path — older code должен ignore unknown fields (additive schema per ADR-017)

Phase A item A12 — extend persistence.py:
- Add `model_version` field defaulting `1.3` if absent
- Add v2.0.0 specific fields с `Optional` types
- Add migration step: if `model_version < 2.0` and project loaded — show «Modeль обучена в v1.3.x. Re-train recommended для full diagnostics.» banner.

---

## N1 — Manager mode rename buttons ✅

`WIZARD_FLOW_v2_FINAL.md` §2 updated:

```
Manager mode AnalysisModeSelector — 2 buttons:

┌─────────────────────────────────────────┐
│  💰 ROI режим                            │
│  Все каналы в ₽                          │
│  KPI любой (продажи / лиды / упаковки)  │
│  Модель считает ROI / CPU                │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  📊 Эффективность режим                  │
│  Все каналы в физических метриках       │
│  (TRP, показы, клики)                    │
│  KPI любой                               │
│  Модель считает доли вклада в %          │
└─────────────────────────────────────────┘

Expert mode добавляет 3-ю опцию:

┌─────────────────────────────────────────┐
│  🔧 Смешанный (Expert) ⚠                 │
│  Per-channel выбор единиц               │
│  Точность ROI зависит от ставок         │
│  конверсии (±10-25%)                     │
└─────────────────────────────────────────┘
```

**Critical:** под капотом эти 2 кнопки = только media input mode. **KPI kind определяется Шагом 2** (KPISelector) независимо. Customer может выбрать «ROI mode + count KPI = CPU/упак» или «Effectiveness mode + monetary KPI = % shares ₽».

Этот fix устраняет semantic conflict из audit finding N1.

---

## N2 — Forecast plan vs trained model validator ✅

См. §B6+N8 `forecast_planned_activities.yaml` validators block:
- `plan_in_trained_model` — channels ⊆ trained channels
- `unit_compatibility` — unit types match
- `extrapolation_warning` — spend within [0.5×, 2×] training range

---

## N3 — Existing Expert mode capability audit ✅

```bash
grep -rn "\$expertMode\|expertMode" src/lib/components/pipeline/ | head -30
```

Found:
- `OptimizeStep.svelte:25,53-55` — reads `$expertMode` for conditional UI
- `RatioInfoCard.svelte` — Expert opt-in breakdown grid
- `ValidateStepV13.svelte` — `expertMode` reference

**Audit conclusion:** Текущий Expert mode = pretty limited toggle (controls expanded view в RatioInfoCard, conditional fields). **Не полный math access escape hatch** как нужно для v2.0.0.

**Phase B action (added to B-A11):** `AnalysisModeSelector.svelte` Expert opens **full toolbox**:
- `PerChannelInputSelector` visible
- `UnitCostsPanel` visible (conditional on physical channels)
- All advanced fields surfaced
- Prior override controls (если будут в v2.2.0)

This becomes part of `AnalysisModeSelector` + `ScenarioWizard` integration в Phase B.

---

## N7 — Methodology Certificate v2.0.0 schema update plan ✅

Methodology Certificate hash currently включает:
- `bundle.manifest.json` (data structure)
- `model_spec` (priors, formulas)
- `decomposition_results` (per-channel contributions)

**v2.0.0 additions to hash payload:**
- `analysisMode` field (Manager mode chosen или derived)
- `signed_factor_contributions` (NEW output)
- `holiday_calendar_version` (which 12 events used)
- `forecast_planned_activities_inputs` (если task 4)

**Cross-product implication:** `verify.auroraai.pro` WASM verifier (Rust, в `aurora-platform-core/c7-web-verifier`) **должен parse новый schema**. Это external coordination dependency.

**Phase E item E5:**
- Update Methodology Certificate template (`engines/methodology_cert.py`)
- Coordinate verifier update (cross-product task — Маша небесная or shared Platform Core)
- Backward compat: old certificates remain verifiable, new certificates work in both v1.3 and v2.0 verifiers (additive fields)

---

## N13 — Save/Load cache diagnostics list ✅

`persistence.py` extension scope (Phase A item A12):

```python
@dataclass
class V20ModelArtifact:
    # v1.3 fields (existing)
    trace: dict
    channel_params: dict
    normalization: dict
    config: dict
    
    # v2.0.0 NEW cached diagnostics
    signed_factor_priors_used: dict  # which priors applied
    holiday_dummies_injected: list  # which 12 events present in training
    mcmc_diagnostics: dict  # r_hat per param, ess per param
    backtest_results: dict  # MAPE, RMSE, R² + per-period predictions
    ppc_results: dict  # R² scatter values, residual stats
    sensitivity_tornado_cache: dict  # top-7 params + their |ΔROI|, computed on-demand
    decomposition_signed_factors: dict  # full JSON structure (per H7)
    
    model_version: str = '2.0.0'
```

`load_model_with_compat()` reads all v2.0.0 fields gracefully (return None if absent) for backward compat с v1.3.

Customer on load sees: «Модель обучена в v1.3.x. Диагностика недоступна — рекомендуется re-train для full v2.0.0 features.» (banner, not blocking).

---

## Summary

| Item | Status | Where addressed |
|---|---|---|
| B2 — Wizard state lifecycle | ✅ | WIZARD_FLOW §0.6 |
| H5→B — Adstock priors monthly | ✅ Resolved (already calibrated) | Code audit, documented in this file |
| B1+L2 — Timeline | ✅ | ADR-019 + this file + track.md |
| B3 — Migration logic | ✅ | this file + WIZARD_FLOW §M |
| B4 — Signed factor priors | ✅ | this file (placeholder doc) |
| B6+N8 — forecast YAML | ✅ | this file (full spec, ready для file create) |
| H1 — Backtest pseudocode | ✅ | this file |
| H3 — Holiday collinearity | ✅ | this file |
| H6 — Variable classifier tests | ✅ | this file (acceptance criteria) |
| H7 — Decomposer JSON | ✅ | this file (full schema) |
| M6→H — analysisObjective audit | ✅ | this file (grep results + migration plan) |
| L4→H — persistence.py compat | ✅ | this file (test plan) |
| N1 — Manager mode rename | ✅ | WIZARD_FLOW §2 + this file |
| N2 — Forecast validator | ✅ | forecast YAML validators block |
| N3 — Expert mode audit | ✅ | this file (grep + action plan) |
| N7 — Methodology Cert update | ✅ | this file (Phase E E5) |
| N13 — Save/Load diagnostics | ✅ | this file (V20ModelArtifact dataclass) |

**Pre-flight complete. Ready для Phase A start.**
