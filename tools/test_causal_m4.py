"""
Sprint 3 Pharma Causal - M4 integration MIN-LIVE checkpoint.

Verifies:
- causal_preflight: applicable methods detection on synthetic panel
- list_causal_artifacts: directory listing с metadata extraction
- cross_method_consistency: pairwise CI overlap + divergence verdict
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
            msg += f' - {hint}'
        print(msg)


# ──────────────────────────────────────────────────────────────────
# Build synthetic panel with all method requirements
# ──────────────────────────────────────────────────────────────────
print('── Build synthetic full-feature panel ──')
np.random.seed(42)

n_regions = 6
n_periods = 24
treatment_period = 13
treated_unit = 'region_0'

rows = []
for r_i, u in enumerate([f'region_{i}' for i in range(n_regions)]):
    for t in range(1, n_periods + 1):
        is_treated = (u == treated_unit) and (t >= treatment_period)
        rows.append({
            'unit': u,
            'period': t,
            'kpi': 200 + r_i * 30 + t * 2 + np.random.normal(0, 5) + (50 if is_treated else 0),
            'treated': 1 if is_treated else 0,
            'feature_x1': np.random.uniform(0, 10),
            'feature_x2': np.random.normal(0, 1),
        })
panel_df = pd.DataFrame(rows)
panel_path = REPO / 'test_payloads' / 'synth_m4_panel.xlsx'
panel_path.parent.mkdir(parents=True, exist_ok=True)
panel_df.to_excel(panel_path, index=False)
print(f'Panel: {len(panel_df)} obs, {n_regions} regions × {n_periods} months')

project_dir = REPO / 'test_payloads' / 'projects' / 'm4_test'
project_dir.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────────
# M4.1 - causal_preflight on full-feature panel
# ──────────────────────────────────────────────────────────────────
print('\n── M4.1: causal_preflight ──')
from engines.causal.preflight import causal_preflight, list_causal_artifacts, cross_method_consistency

result = causal_preflight(
    str(panel_path),
    unit_column='unit',
    time_column='period',
    kpi_column='kpi',
    treatment_column='treated',
    treated_unit=treated_unit,
    treatment_period=treatment_period,
    feature_columns=['feature_x1', 'feature_x2'],
)
check('preflight: status=ok', result.get('status') == 'ok')
check('preflight: overall_tier=reliable (≥2 methods applicable)',
      result.get('overall_tier') == 'reliable')

methods_app = result.get('methods_applicable', {})
check('preflight: did applicable=True', methods_app.get('did') == True)
check('preflight: scm applicable=True', methods_app.get('scm') == True)
# Forest needs n>=100, panel has 144 - applicable
check('preflight: forest applicable=True (n=144>=100)',
      methods_app.get('forest') == True)

check('preflight: recommended_methods has all 3', len(result.get('recommended_methods', [])) == 3)
check('preflight: common_caveats has SUTVA reference',
      any('SUTVA' in c for c in result.get('common_caveats', [])))

# ──────────────────────────────────────────────────────────────────
# M4.2 - preflight degraded scenarios
# ──────────────────────────────────────────────────────────────────
print('\n── M4.2: preflight degraded inputs ──')

# No treatment_column → DiD/Forest both N/A, only SCM if treated_unit/period provided
result_no_treat = causal_preflight(
    str(panel_path),
    unit_column='unit',
    time_column='period',
    kpi_column='kpi',
    treatment_column=None,
    treated_unit=treated_unit,
    treatment_period=treatment_period,
    feature_columns=None,
)
check('preflight no treat: did NOT applicable',
      result_no_treat.get('methods_applicable', {}).get('did') == False)
check('preflight no treat: scm applicable (treated_unit + period)',
      result_no_treat.get('methods_applicable', {}).get('scm') == True)
check('preflight no treat: tier=directional (1 method)',
      result_no_treat.get('overall_tier') == 'directional')

# Insufficient - no treatment, no SCM params
result_none = causal_preflight(
    str(panel_path),
    unit_column='unit',
    time_column='period',
    kpi_column='kpi',
    treatment_column=None,
)
check('preflight no causal info: tier=insufficient',
      result_none.get('overall_tier') == 'insufficient')

# ──────────────────────────────────────────────────────────────────
# M4.3 - list_causal_artifacts
# ──────────────────────────────────────────────────────────────────
print('\n── M4.3: list_causal_artifacts ──')

# First - empty project
empty_listing = list_causal_artifacts(str(project_dir))
check('list empty project: count=0', empty_listing['count'] == 0)
check('list empty project: artifacts is empty list', empty_listing['artifacts'] == [])

# Run DiD + SCM to populate
from engines.causal.did import estimate_did
from engines.causal.scm import estimate_scm

did_result = estimate_did(
    str(panel_path),
    project_dir=str(project_dir),
    unit_column='unit',
    time_column='period',
    kpi_column='kpi',
    treatment_column='treated',
)
check('DiD ran successfully для list test', did_result.get('status') == 'ok')

scm_result = estimate_scm(
    str(panel_path),
    project_dir=str(project_dir),
    unit_column='unit',
    time_column='period',
    kpi_column='kpi',
    treated_unit=treated_unit,
    treatment_period=treatment_period,
    run_placebo=True,
)
check('SCM ran successfully для list test', scm_result.get('status') == 'ok')

# List again
listing = list_causal_artifacts(str(project_dir))
check(f'list after DiD+SCM: count=2 (got {listing["count"]})',
      listing['count'] == 2)
check('list artifacts have method field',
      all('method' in a for a in listing['artifacts']))
check('list artifacts include did_twfe',
      any(a['method'] == 'did_twfe' for a in listing['artifacts']))
check('list artifacts include scm_abadie_classic',
      any(a['method'] == 'scm_abadie_classic' for a in listing['artifacts']))
check('list artifacts have att_point populated',
      all(a.get('att_point') is not None for a in listing['artifacts']))

# ──────────────────────────────────────────────────────────────────
# M4.4 - cross_method_consistency
# ──────────────────────────────────────────────────────────────────
print('\n── M4.4: cross_method_consistency ──')

consistency = cross_method_consistency(str(project_dir))
check('consistency: status=ok', consistency.get('status') == 'ok')
check('consistency: methods_compared has 2',
      len(consistency.get('methods_compared', [])) == 2)
check('consistency: att_values populated for both methods',
      len(consistency.get('att_values', {})) == 2)
check('consistency: ci_overlap has did_vs_scm or analogous',
      len(consistency.get('ci_overlap', {})) >= 1)
check('consistency: max_relative_divergence is float',
      isinstance(consistency.get('max_relative_divergence'), (int, float)))
check(f'consistency: verdict in {{agree, disagree, partial, unknown}}',
      consistency.get('consistency_verdict') in ('agree', 'disagree', 'partial', 'unknown'))
check('consistency: recommendation is non-empty string',
      isinstance(consistency.get('recommendation'), str) and len(consistency['recommendation']) > 0)

# ──────────────────────────────────────────────────────────────────
# M4.5 - empty project consistency
# ──────────────────────────────────────────────────────────────────
print('\n── M4.5: consistency on empty project ──')

# Use a fresh empty project
empty_project = REPO / 'test_payloads' / 'projects' / 'm4_empty'
empty_project.mkdir(parents=True, exist_ok=True)
empty_consistency = cross_method_consistency(str(empty_project))
check('empty project: verdict=insufficient_data',
      empty_consistency.get('consistency_verdict') == 'insufficient_data')

# ──────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────
try:
    panel_path.unlink()
except Exception:
    pass
import shutil
for d in [project_dir, empty_project]:
    try:
        if d.exists():
            shutil.rmtree(d)
    except Exception:
        pass

print(f'\n{PASSED}/{PASSED + FAILED} assertions passed.')
sys.exit(0 if FAILED == 0 else 1)
