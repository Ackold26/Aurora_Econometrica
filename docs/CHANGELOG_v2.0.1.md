# Aurora MMM Optimizer v2.0.1 — Pilot Hotfix

**Release date:** 2026-05-1X (TBD by Антон)
**Branch:** `feat/v2.0.0-explicit-mode-wizard`
**Base tag:** `v2.0.0`
**Status:** ⏳ Draft — pending pilot verification + Антон approval

---

## Motivation

Hotfix patch обнаружен через **pilot UI testing на real dataset pilot pharma dataset**
2026-05-14 (32 columns: 6 digital media каналов + TV TRPs + OOH/Radio/Press +
controls + KPI). 4 issues найдены в Manager ROI mode flow:

1. 🔴 **CRITICAL BUG #2**: TV TRPs / физические метрики маскировались как
   «спенд в ₽» — модель тренировалась с unit error
2. 🟠 **HIGH BUG #3**: SOM / SOV / market_share классифицировались как
   `control` — endogeneity risk (derived из KPI)
3. 🟡 **MEDIUM UX gap**: Auto-excluded каналы (ratioRecommendation rule)
   не объяснены — юзер видел 6 каналов без понимания что было 10
4. 🟢 **FB Антона**: Конвертация physical→monetary должна быть в Manager
   mode inline, а не требовать Expert mode

---

## Changes

### Frontend — `src/lib/components/pipeline/AppliedModeSummary.svelte`

**Channel label logic:**
- Physical channel в ROI mode без unit_cost → `⚠ нужна конвертация в ₽`
  (incompatible state, желтая полоска + warning marker)
- Physical channel в ROI mode с unit_cost > 0 → `N ₽/ед — конвертация в ₽`
  (converted state, зелёная полоска + check mark)
- Monetary channel в ROI mode → `спенд в ₽ ✓` (как раньше)

**Inline two-mode `unit_cost` inputs:**
Под warning banner для each physical-в-ROI канала появляется input row.
- **Mode A** (Общий бюджет ₽): one input для total ₽ за period →
  модель derives `unit_cost = budget / Σ(units)`. Show preview:
  «1234.56 ₽ за 1 TRP (бюджет ÷ 31 ед.)»
- **Mode B** (Цена 1 ед. + инфляция CPP/CPM): two inputs (₽/ед +
  %/год inflation) — соответствует UnitCostsPanel pattern прошлых
  версий. Show preview: «итоговая сумма за период: 38 254 ₽».
- **Default mode** = «Цена 1 ед.» (как в прошлых версиях).
- Stores в существующие `unitCosts` + `unitCostInflation` Svelte stores
  (downstream consumers DecomposeStep/OptimizeStep/BudgetOptimizer already
  handle inflation-adjusted weighted-avg).

**Counts pills + excluded list:**
- `✓ N активных` + `⊘ M исключено` (clickable expand button)
- Expanded list показывает имена + hint «можно вернуть через "Роли колонок"»

### Frontend — `src/lib/components/pipeline/ValidateStepV13.svelte`

- New helper `detectChannelType(name)` — regex-based MONETARY_RE/PHYSICAL_RE
  (mirrors backend `column_detection.py` MONETARY_PATTERNS + PHYSICAL_PATTERNS).
  Используется когда `$perChannelInput` empty (Manager mode) → AppliedModeSummary
  получает реальный detectedType вместо hardcoded `'monetary'` default.
- New derived `channelSums` — extracts `c.stats.sum` per media column → passes
  к AppliedModeSummary для Mode A (budget) calculation.
- New derived `excludedMediaNames` — filters role='unused'/'excluded' cols
  через MONETARY/PHYSICAL regex → passes к AppliedModeSummary для pill display.

### Backend — `sidecar/econometrica/engines/validator.py`

**BUG #3 fix:** new `DERIVED_KEYS` priority check после competitor override:
```python
DERIVED_KEYS = [
    'som в', 'som (', 'som_',
    'sov ', 'sov (', 'sov_',
    'share_of_market', 'share of market', 'market_share', 'market share',
    'share_of_voice', 'share of voice',
    'доля_рынка', 'доля рынка', 'доля_голоса', 'доля голоса',
]
if (any(k in lower for k in DERIVED_KEYS)
        or lower in ('som', 'sov')
        or lower.endswith(' som') or lower.endswith(' sov')):
    return 'unused', 0.85
```

Returns `('unused', 0.85)` → auto-exclude from model. Юзер может explicitly
включить через Roles UI override если знает что делает.

Trailing-space / suffix guards защищают от false positives ('mosgorsovet',
'sovetnik', 'somatic' остаются 'control' как pre-fix — accepted tech debt
для будущей migration к utils/column_detection.py separator-aware regex).

### Tests

- `src/tests/applied-mode-summary.test.js`: 21 → 41 tests (+20 для inline UI
  + excluded pills + new behaviours)
- `tools/test_validator_derived_metrics.py`: NEW file, 32 tests, 4 classes
  (derived excluded / no regression / competitor priority preserved / kpi unaffected)
- Full vitest: 375/375 pass (+4 net new)
- Full pytest: 1504+ pass (2 pre-existing failures in test_priors_calibration
  unrelated to v2.0.1 changes, verified through git stash)
- svelte-check: 0 errors, 163 baseline warnings preserved

---

## Migration impact

### Existing projects (saved .aurora archives)

`unit_costs` и `unit_cost_inflation_pct` в `project.json` — **не меняется
формат**, новый UI просто читает/пишет в existing stores. Старые проекты
загрузятся без breaking.

### Existing classification

`SOM в руб` / `SOM в уп.` / `SOV` columns — раньше попадали в
`control_columns`, теперь в `excluded_columns` (auto). Для **сохранённых
.aurora projects** где SOM был в control_columns — при reopen роли
remain как сохранены (не re-classify). Для **новых импортов** SOM
автоматически excluded.

### Pre-flight на v2.0.0 customer projects

- Если customer dataset содержит physical media каналы (TRP, GRP) в ROI
  mode → банер появится с inline inputs
- Если customer dataset содержит SOM/SOV → они попадут в excluded
  (раньше — control). User получит больше клин model. Если эти cols
  были critical predictors — user может re-enable через Roles step.

---

## Known limitations (deferred к v2.0.2 / v2.1.0)

1. **Backend defense-in-depth**: `econ_save_kpi_settings` сейчас принимает
   physical channels без unit_cost (UI warns но не блокирует). Backend
   filter add для guaranteed correctness — separate PR.
2. **CONTROL_PATTERNS false positives**: `'sov'` substring matches
   `'mosgorsovet'` (rare edge case). Migration к
   `utils/column_detection.py` separator-aware regex — separate PR.
3. **Reorder substeps Валидации** (FB Антона): «Целевая метрика» до
   «Роли колонок» — architectural change, design doc создан, scope ~3-5h.
   Target v2.1.0 minor release.

---

## Reviewer notes

- ADR-019 не меняется (still supersedes ADR-015)
- Methodology Certificate schema не затронуто
- Verifier compatibility preserved
- WIZARD_FLOW_v2_FINAL.md spec — добавить раздел «§7 Unit-cost конвертация»
  если merge подтверждён

---

**Discovered through:** Pilot UI testing 2026-05-14 (Маша маленькая autonomous)
**Authored:** Маша маленькая (Claude Code, Opus 4.7 max)
**Verified:** 375 vitest + 1504 pytest + svelte-check 0 errors
**Status:** Awaiting Antón approval for merge → math-fix-v1.0.13 → NSIS ship
