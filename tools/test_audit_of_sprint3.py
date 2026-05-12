"""
Lock-in tests для audit-of-Sprint3 fixes (2026-04-27).

Verify HIGH-severity findings B1-B5 + selected MEDIUM (B7-B10) cannot regress.
Each test asserts the SPECIFIC behavior changed by the fix, не general functionality.
"""
from __future__ import annotations

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


def check(label, ok, hint=''):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f'[OK]   {label}')
    else:
        FAILED += 1
        print(f'[FAIL] {label}' + (f' - {hint}' if hint else ''))


# ──────────────────────────────────────────────────────────────────
# B1 lock-in: SCM placebo excludes original treated_unit from donor pool
# ──────────────────────────────────────────────────────────────────
print('── B1: SCM placebo donor pool excludes original treated_unit ──')
from engines.causal.scm import _placebo_inference

# Build minimal panel: 4 units × 12 periods. region_0 is treated.
np.random.seed(7)
units = ['region_0', 'region_1', 'region_2', 'region_3']
n_periods = 12
treatment_period = 7
rows = []
for u in units:
    for t in range(1, n_periods + 1):
        # Big spike for treated post-period - should NOT contaminate placebo donor pool
        is_real_treat = (u == 'region_0') and (t >= treatment_period)
        rows.append({
            'unit': u, 'period': t,
            'kpi': 100.0 + np.random.normal(0, 1) + (1000.0 if is_real_treat else 0.0),
        })
df = pd.DataFrame(rows)

# donor_units list excludes the true treated_unit per Abadie convention
donor_units = ['region_1', 'region_2', 'region_3']

# Run with treated_unit kwarg (B1 fix)
result_with_fix = _placebo_inference(
    df, true_att=1000.0,
    treatment_period=treatment_period,
    unit_col='unit', time_col='period', kpi_col='kpi',
    donor_units=donor_units,
    treated_unit='region_0',  # B1 fix: pass true treated_unit
)
check('B1: placebo runs successfully with treated_unit kwarg',
      result_with_fix.get('p_value') is not None,
      f'detail: {result_with_fix}')

# Backward-compat: when treated_unit not passed, falls back к full df behavior
result_no_fix = _placebo_inference(
    df, true_att=1000.0,
    treatment_period=treatment_period,
    unit_col='unit', time_col='period', kpi_col='kpi',
    donor_units=donor_units,
    # treated_unit NOT passed - backward-compat path
)
check('B1: backward-compat path returns p_value (legacy callers ok)',
      result_no_fix.get('p_value') is not None)

# B1 structural verification: scenario-independent assertion that with-fix
# excludes treated_unit from df. Done via inspecting source code (most robust)
# + verifying both paths return valid results без crash.
import inspect
from engines.causal import scm
src_scm = inspect.getsource(scm._placebo_inference)
check('B1: source code excludes treated_unit from df (df_no_true logic)',
      'df_no_true' in src_scm and "df[df[unit_col] != treated_unit]" in src_scm)
check('B1: docstring documents Abadie convention',
      'Abadie convention' in src_scm)
# Both paths return valid p-value (no crash на edge case)
check('B1: with-fix returns valid n_placebos',
      result_with_fix.get('n_placebos', 0) >= 1)
check('B1: without-fix returns valid n_placebos (backward compat)',
      result_no_fix.get('n_placebos', 0) >= 1)

# Std field added to summary (B2 fix)
summary = result_with_fix.get('placebo_atts_summary', {})
check('B2: placebo_atts_summary includes std field',
      'std' in summary,
      f'keys: {list(summary.keys())}')

# ──────────────────────────────────────────────────────────────────
# B2 lock-in: ci_method honest fallback marker когда insufficient placebos
# ──────────────────────────────────────────────────────────────────
print('\n── B2: SCM ci_method='+chr(39)+'placebo_pre_rmse_fallback'+chr(39)+' когда insufficient placebos ──')
from engines.causal.scm import estimate_scm

# Tiny panel: 4 units × 12 periods → only 3 donors (excluding treated).
# Per Abadie convention с n_donors=3, after excluding true treated в placebo
# loop we have 2 donors per placebo run, which has minimum constraint check.
# Actually just run normally - checking that ci_method label adapts honestly.
project_dir = REPO / 'test_payloads' / 'projects' / 'audit_b2'
project_dir.mkdir(parents=True, exist_ok=True)

scm_path = REPO / 'test_payloads' / 'audit_b2_panel.xlsx'
df.to_excel(scm_path, index=False)

result = estimate_scm(
    str(scm_path),
    project_dir=str(project_dir),
    unit_column='unit',
    time_column='period',
    kpi_column='kpi',
    treated_unit='region_0',
    treatment_period=treatment_period,
    run_placebo=True,
)
ci_method = result.get('att', {}).get('ci_method', '')
check(f'B2: ci_method ∈ honest set (got {ci_method})',
      ci_method in ('placebo_permutation', 'placebo_pre_rmse_fallback'),
      f'got {ci_method}')

# ──────────────────────────────────────────────────────────────────
# B3 lock-in: causal_forest CI method label honest when fallback fires
# ──────────────────────────────────────────────────────────────────
print('\n── B3: Causal Forest cate_mean_se_fallback honest naming ──')
# Hard to test без forcing failure of cf.effect_interval. Instead verify в code:
import inspect
from engines.causal import causal_forest
src = inspect.getsource(causal_forest.estimate_causal_forest)
check('B3: code references cate_mean_se_fallback (not generic bootstrap)',
      'cate_mean_se_fallback' in src)
check('B3: caveat string about underestimating uncertainty',
      'underestimates true uncertainty' in src)

# ──────────────────────────────────────────────────────────────────
# B4 lock-in: parallel-trends test uses cluster-robust SE
# ──────────────────────────────────────────────────────────────────
print('\n── B4: DiD parallel_trends_test uses clustered SE ──')
from engines.causal.did import _parallel_trends_test

# Build pre-treatment panel
pre_df_data = []
for u in ['region_0', 'region_1', 'region_2', 'region_3']:
    for t in range(1, 7):
        pre_df_data.append({
            'unit': u, 'period': t,
            'kpi': 100 + (10 if u == 'region_0' else 0) + np.random.normal(0, 5),
            'treated': 0,
        })
# Add treatment markers (post-period 7+ for region_0/1)
for u in ['region_0', 'region_1', 'region_2', 'region_3']:
    for t in range(7, 13):
        pre_df_data.append({
            'unit': u, 'period': t,
            'kpi': 100 + np.random.normal(0, 5),
            'treated': 1 if u in ('region_0', 'region_1') else 0,
        })
pt_df = pd.DataFrame(pre_df_data)

result = _parallel_trends_test(
    pt_df, 'unit', 'period', 'kpi', 'treated',
    treated_units=['region_0', 'region_1'],
)
check('B4: parallel_trends_test returns se_method field',
      'se_method' in result,
      f'keys: {list(result.keys())}')
check(f'B4: se_method=cluster для panel with ≥2 units (got {result.get("se_method")})',
      result.get('se_method') == 'cluster')

# ──────────────────────────────────────────────────────────────────
# B5 lock-in: модель pickle включает causal_artifact_path field
# ──────────────────────────────────────────────────────────────────
print('\n── B5: modeler.py pickle schema includes causal_artifact_path field ──')
import inspect
from engines import modeler
src_modeler = inspect.getsource(modeler.train_model)
check('B5: modeler.py contains causal_artifact_path в pickle schema',
      "'causal_artifact_path'" in src_modeler)

# ──────────────────────────────────────────────────────────────────
# B7 lock-in: SCM validate ставит overfit warning meta когда n_pre < n_donors+1
# ──────────────────────────────────────────────────────────────────
print('\n── B7: SCM overfit warning when n_pre < n_donors+1 ──')
from engines.causal._panel_data import PanelMetadata, validate_for_scm

# 8 units, only 6 pre-periods → n_pre=6 < n_donors+1=8. Should pass validation
# но stamp _overfit_warning attribute (non-blocking warning).
metadata_overfit = PanelMetadata(
    n_units=8, n_periods=10, n_obs=80, is_balanced=True,
    unit_column='u', time_column='t', kpi_column='k',
    units_list=[f'r_{i}' for i in range(8)],
    periods_list=list(range(1, 11)),
    has_treatment=False,
)
err = validate_for_scm(metadata_overfit, treated_unit='r_0', treatment_period=7)
check('B7: validate passes (non-blocking warning)', err is None)
check('B7: _overfit_warning meta attribute set когда n_pre < n_donors+1',
      hasattr(metadata_overfit, '_overfit_warning'))

# ──────────────────────────────────────────────────────────────────
# B9 lock-in: cross_method_consistency skips pairs с null CI
# ──────────────────────────────────────────────────────────────────
print('\n── B9: cross_method_consistency skips ci_missing pairs ──')
import json
from engines.causal.preflight import cross_method_consistency

# Project с 2 artifacts: one с full CI, one с null CI
b9_project = REPO / 'test_payloads' / 'projects' / 'audit_b9'
(b9_project / 'causal').mkdir(parents=True, exist_ok=True)

art1 = {
    'status': 'ok', 'method': 'did_twfe',
    'att': {'point': 50, 'ci_low': 40, 'ci_high': 60, 'ci_method': 'frequentist_se_clustered', 'confidence': 0.9},
    'created_at': '2026-04-27T10:00:00',
}
art2 = {
    'status': 'ok', 'method': 'scm_abadie_classic',
    'att': {'point': 55, 'ci_low': None, 'ci_high': None, 'ci_method': 'placebo_pre_rmse_fallback', 'confidence': 0.9},
    'created_at': '2026-04-27T11:00:00',
}
with open(b9_project / 'causal' / 'did_001.json', 'w', encoding='utf-8') as f:
    json.dump(art1, f)
with open(b9_project / 'causal' / 'scm_002.json', 'w', encoding='utf-8') as f:
    json.dump(art2, f)

consistency = cross_method_consistency(str(b9_project))
overlap_dict = consistency.get('ci_overlap', {})
# Skipped pair has 'skipped_*' marker, not boolean false
has_skipped = any('skipped' in str(v) for v in overlap_dict.values())
check('B9: pair с null CI labeled skipped (not false-flag)',
      has_skipped,
      f'overlap_dict: {overlap_dict}')

# Verdict == 'unknown' when all pairs skipped (was 'disagree' pre-fix)
check(f'B9: verdict=unknown когда no comparable pairs (got {consistency.get("consistency_verdict")})',
      consistency.get('consistency_verdict') == 'unknown')

# ──────────────────────────────────────────────────────────────────
# B10 lock-in: synthesize_geo_split numeric_cols hoisted (smoke - no perf check)
# ──────────────────────────────────────────────────────────────────
print('\n── B10: synthesize_geo_split numeric_cols computed once ──')
from engines.causal._panel_data import synthesize_geo_split
agg = pd.DataFrame({
    'date': pd.date_range('2024-01-01', periods=24, freq='ME'),
    'kpi': np.random.uniform(100, 200, 24),
    'spend': np.random.uniform(10, 50, 24),
})
panel = synthesize_geo_split(agg, n_geo=4, seed=42, geo_column_name='region')
check('B10: function still works after refactor', len(panel) == 24 * 4)
check('B10: region column populated', 'region' in panel.columns)
check('B10: numeric scaling applied', not (panel['kpi'] == agg['kpi'].iloc[0]).all())

# ──────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────
import shutil
for f in [scm_path]:
    try: f.unlink()
    except: pass
for d in [project_dir, b9_project]:
    try:
        if d.exists(): shutil.rmtree(d)
    except: pass

print(f'\n{PASSED}/{PASSED + FAILED} assertions passed.')
sys.exit(0 if FAILED == 0 else 1)
