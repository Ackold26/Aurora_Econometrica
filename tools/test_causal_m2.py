"""
Sprint 3 Pharma Causal — M2 SCM endpoint MIN-LIVE checkpoint.

Per ADR §6 + §11/Q1 refinement: per-M sanity gate (~30min).

Synthesizes a controlled SCM scenario с known ground-truth ATT:
- 6 regions × 24 months (region_0 = treated, остальные = donors)
- Common pre-treatment trajectory (region-specific intercept + linear trend + noise)
- Treatment from month 13 → known ATT shift for region_0

Verifies:
- _solve_scm_weights returns valid simplex weights (sum=1, nonneg)
- estimate_scm recovers true ATT в loose tolerance
- Pre-treatment RMSE diagnostics
- Placebo test produces p-value
- HonestDisclosure populated
- Artifact persisted
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))

import numpy as np
import pandas as pd

PASSED = 0
FAILED = 0


def check(label: str, ok: bool, hint: str = '') -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f'[OK]   {label}')
    else:
        FAILED += 1
        msg = f'[FAIL] {label}'
        if hint:
            msg += f' — {hint}'
        print(msg)


# ──────────────────────────────────────────────────────────────────
# Build synthetic SCM scenario с known ground truth
# ──────────────────────────────────────────────────────────────────
print('── Synthesize SCM ground-truth scenario ──')
np.random.seed(42)

n_regions = 6
n_periods = 24
treatment_period = 13
TRUE_ATT = 80.0
treated_unit = 'region_0'

# Common factor model (each region = base + factor_loading × time_factor + noise)
time_factor = np.cumsum(np.random.normal(0, 1, n_periods))  # random walk shared

units = [f'region_{i}' for i in range(n_regions)]
loadings = {u: 0.5 + i * 0.2 for i, u in enumerate(units)}  # heterogeneous loadings
intercepts = {u: 200 + i * 30 for i, u in enumerate(units)}

rows = []
for u in units:
    for t in range(1, n_periods + 1):
        kpi = (intercepts[u] + loadings[u] * time_factor[t - 1] +
               np.random.normal(0, 5))
        # Treatment effect: kicks in at treatment_period for treated_unit only
        if u == treated_unit and t >= treatment_period:
            kpi += TRUE_ATT
        rows.append({'unit': u, 'period': t, 'kpi': kpi})

scm_df = pd.DataFrame(rows)
scm_path = REPO / 'test_payloads' / 'synth_scm_panel.xlsx'
scm_path.parent.mkdir(parents=True, exist_ok=True)
scm_df.to_excel(scm_path, index=False)
print(f'Synthetic panel: {len(scm_df)} obs, {n_regions} regions × {n_periods} months')
print(f'TRUE ATT = {TRUE_ATT}, treated = {treated_unit}, t_start = {treatment_period}')

# ──────────────────────────────────────────────────────────────────
# M2.1 — _solve_scm_weights returns valid simplex weights
# ──────────────────────────────────────────────────────────────────
print('\n── M2.1: _solve_scm_weights interface ──')
from engines.causal.scm import _solve_scm_weights

# Synthesize tractable case: 5 donors, 12 pre-periods
n_pre = 12
y_treat_pre = np.random.normal(100, 10, n_pre)
Y_donors_pre = np.random.normal(100, 10, (n_pre, 5))
weights, status = _solve_scm_weights(y_treat_pre, Y_donors_pre)

check('_solve_scm_weights returns weights array', weights is not None)
if weights is not None:
    check(f'weights status = optimal (got {status})', status == 'optimal')
    check(f'weights shape (5,) (got {weights.shape})', weights.shape == (5,))
    check(f'weights sum to 1 (got {weights.sum():.6f})', abs(weights.sum() - 1.0) < 1e-4)
    check(f'weights all nonneg (min={weights.min():.6f})', weights.min() >= -1e-9)

# Edge case: no donors
w_empty, s_empty = _solve_scm_weights(np.array([1, 2, 3]), np.zeros((3, 0)))
check('_solve_scm_weights no donors → returns None', w_empty is None)
check('_solve_scm_weights no donors → status = no_donors', s_empty == 'no_donors')

# ──────────────────────────────────────────────────────────────────
# M2.2 — estimate_scm engine recovers ATT
# ──────────────────────────────────────────────────────────────────
print('\n── M2.2: estimate_scm engine ──')
from engines.causal.scm import estimate_scm

project_dir = REPO / 'test_payloads' / 'projects' / 'synth_scm'
project_dir.mkdir(parents=True, exist_ok=True)

result = estimate_scm(
    str(scm_path),
    project_dir=str(project_dir),
    unit_column='unit',
    time_column='period',
    kpi_column='kpi',
    treated_unit=treated_unit,
    treatment_period=treatment_period,
    confidence=0.9,
    run_placebo=True,
)

check('estimate_scm: status=ok', result.get('status') == 'ok',
      f'got status={result.get("status")} message={result.get("message")}')

if result.get('status') == 'ok':
    att = result['att']
    err_pct = abs(att['point'] - TRUE_ATT) / TRUE_ATT
    check(f'ATT point estimate within 50% of true {TRUE_ATT} (got {att["point"]:.2f}, err {err_pct*100:.1f}%)',
          err_pct < 0.50,
          f'recovered {att["point"]} expected {TRUE_ATT}')
    check(f'ATT CI contains true value {TRUE_ATT} ([{att["ci_low"]:.2f}, {att["ci_high"]:.2f}])',
          att['ci_low'] <= TRUE_ATT <= att['ci_high'])
    check('ATT ci_method = placebo_permutation (run_placebo=True)',
          att['ci_method'] == 'placebo_permutation')

# ──────────────────────────────────────────────────────────────────
# M2.3 — Diagnostics shape + content
# ──────────────────────────────────────────────────────────────────
print('\n── M2.3: diagnostics ──')
diag = result.get('diagnostics', {})
expected_keys = {
    'panel_metadata', 'treated_unit', 'treatment_period', 'donor_units',
    'donor_weights', 'weight_optimization_status', 'pre_treatment_rmse',
    'pre_treatment_rmse_ratio', 'effective_n_donors', 'weight_hhi',
    'placebo_test', 'n_pre_periods', 'n_post_periods', 'att_per_period',
}
got_keys = set(diag.keys())
check(f'diagnostics has all {len(expected_keys)} expected keys',
      expected_keys.issubset(got_keys),
      f'missing: {expected_keys - got_keys}')

donor_weights = diag.get('donor_weights', {})
check(f'donor_weights has 5 entries (n_regions - 1)',
      len(donor_weights) == n_regions - 1)
check('donor_weights sum ~ 1',
      abs(sum(donor_weights.values()) - 1.0) < 0.01)

check(f'pre_treatment_rmse populated (got {diag.get("pre_treatment_rmse")})',
      diag.get('pre_treatment_rmse') is not None)

placebo = diag.get('placebo_test', {})
check('placebo_test has p_value', placebo.get('p_value') is not None)
check(f'placebo_test n_placebos > 0 (got {placebo.get("n_placebos")})',
      placebo.get('n_placebos', 0) > 0)

check(f'att_per_period length = n_post_periods ({n_periods - treatment_period + 1})',
      len(diag.get('att_per_period', [])) == n_periods - treatment_period + 1)

# ──────────────────────────────────────────────────────────────────
# M2.4 — HonestDisclosure
# ──────────────────────────────────────────────────────────────────
print('\n── M2.4: HonestDisclosure ──')
hd = result.get('honest_disclosure', {})
check('honest_disclosure.method = scm_abadie_classic',
      hd.get('method') == 'scm_abadie_classic')
check('honest_disclosure.assumptions has ≥3 items',
      len(hd.get('assumptions', [])) >= 3)
check('honest_disclosure.references has ≥1 academic ref',
      len(hd.get('references', [])) >= 1)
# Either passed or failed weight_concentration_hhi diagnostic should appear
all_diag = (hd.get('diagnostics_passed', []) + hd.get('diagnostics_failed', []))
check('honest_disclosure includes pre_rmse diagnostic',
      any('pre_treatment_rmse' in d for d in all_diag))
check('honest_disclosure includes weight_concentration_hhi diagnostic',
      any('weight_concentration_hhi' in d for d in all_diag))

# ──────────────────────────────────────────────────────────────────
# M2.5 — Artifact persisted
# ──────────────────────────────────────────────────────────────────
print('\n── M2.5: Artifact persistence ──')
artifact_path = result.get('artifact_path')
check('artifact_path returned', artifact_path is not None)
check('artifact file exists', Path(artifact_path).exists() if artifact_path else False)

if artifact_path and Path(artifact_path).exists():
    with open(artifact_path, 'r', encoding='utf-8') as f:
        artifact = json.load(f)
    check('artifact has same status', artifact.get('status') == 'ok')
    check('artifact has same ATT point',
          abs(artifact['att']['point'] - result['att']['point']) < 1e-6)
    check('artifact filename starts with scm_',
          Path(artifact_path).name.startswith('scm_'))

# ──────────────────────────────────────────────────────────────────
# M2.6 — Error paths
# ──────────────────────────────────────────────────────────────────
print('\n── M2.6: Error path validation ──')

err_result = estimate_scm(
    str(scm_path),
    project_dir=str(project_dir),
    unit_column='unit',
    time_column='period',
    kpi_column='kpi',
    treated_unit='nonexistent_region',
    treatment_period=treatment_period,
)
check('unknown treated_unit → status=error', err_result.get('status') == 'error')
check('unknown treated_unit → TREATED_UNIT_MISSING',
      err_result.get('error_code') == 'TREATED_UNIT_MISSING')

# Insufficient pre-periods
err_result2 = estimate_scm(
    str(scm_path),
    project_dir=str(project_dir),
    unit_column='unit',
    time_column='period',
    kpi_column='kpi',
    treated_unit=treated_unit,
    treatment_period=3,  # only 2 pre-periods
)
check('<6 pre-periods → INSUFFICIENT_PRE_PERIODS',
      err_result2.get('error_code') == 'INSUFFICIENT_PRE_PERIODS')

# ──────────────────────────────────────────────────────────────────
# M2.7 — run_placebo=False uses pre_rmse_proxy CI
# ──────────────────────────────────────────────────────────────────
print('\n── M2.7: run_placebo=False fallback CI method ──')
result_no_placebo = estimate_scm(
    str(scm_path),
    project_dir=str(project_dir),
    unit_column='unit',
    time_column='period',
    kpi_column='kpi',
    treated_unit=treated_unit,
    treatment_period=treatment_period,
    run_placebo=False,
)
check('run_placebo=False: status=ok', result_no_placebo.get('status') == 'ok')
check('run_placebo=False: ci_method = pre_rmse_proxy',
      result_no_placebo['att']['ci_method'] == 'pre_rmse_proxy')
check('run_placebo=False: placebo_test n_placebos = 0',
      result_no_placebo['diagnostics']['placebo_test']['n_placebos'] == 0)

# ──────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────
try:
    scm_path.unlink()
except Exception:
    pass
import shutil
try:
    if (project_dir / 'causal').exists():
        shutil.rmtree(project_dir / 'causal')
except Exception:
    pass

# ──────────────────────────────────────────────────────────────────
print(f'\n{PASSED}/{PASSED + FAILED} assertions passed.')
sys.exit(0 if FAILED == 0 else 1)
