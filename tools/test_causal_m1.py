"""
Sprint 3 Pharma Causal — M1 DiD endpoint MIN-LIVE checkpoint.

Per ADR §6 + §11/Q1 refinement: per-M sanity gate (~30min).

Synthesizes a controlled DiD scenario с known ground-truth ATT:
- 5 regions × 12 months
- 2 treated regions, treatment starts month 7
- True ATT = 50 units (kpi shift on treated × post)

Verifies:
- estimate_did recovers true ATT ± 30% (loose tolerance for synthetic noise)
- CI contains true ATT
- HonestDisclosure populated (assumptions, references, parallel-trends test)
- Artifact file saved to project_dir/causal/did_*.json
- Non-staggered design correctly detected
- Endpoint shape matches ADR §4.3 spec
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
# Build synthetic DiD scenario с known ground truth
# ──────────────────────────────────────────────────────────────────
print('── Synthesize DiD ground-truth scenario ──')
np.random.seed(42)

units = [f'region_{i}' for i in range(5)]
periods = list(range(1, 13))  # 12 months
treated_units_set = {'region_0', 'region_1'}
treatment_start = 7
TRUE_ATT = 50.0

# Base KPI: regional mean ~ 200 + region_id × 10 (heterogeneity), each month +- noise
rows = []
for u in units:
    region_mean = 200 + units.index(u) * 10
    for t in periods:
        base = region_mean + t * 2 + np.random.normal(0, 5)  # secular trend + noise
        is_treated = (u in treated_units_set) and (t >= treatment_start)
        kpi = base + (TRUE_ATT if is_treated else 0)
        rows.append({
            'unit': u,
            'period': t,
            'kpi': kpi,
            'treated': 1 if is_treated else 0,
        })

synth_df = pd.DataFrame(rows)
synth_path = REPO / 'test_payloads' / 'synth_did_panel.xlsx'
synth_path.parent.mkdir(parents=True, exist_ok=True)
synth_df.to_excel(synth_path, index=False)
print(f'Synthetic panel: {len(synth_df)} obs, {len(units)} regions × {len(periods)} months')
print(f'TRUE ATT = {TRUE_ATT}, treated = {sorted(treated_units_set)}, t_start = {treatment_start}')

# ──────────────────────────────────────────────────────────────────
# M1.1 — estimate_did recovers ATT close к ground truth
# ──────────────────────────────────────────────────────────────────
print('\n── M1.1: estimate_did engine recovers ATT ──')
from engines.causal.did import estimate_did

project_dir = REPO / 'test_payloads' / 'projects' / 'synth_did'
project_dir.mkdir(parents=True, exist_ok=True)

result = estimate_did(
    str(synth_path),
    project_dir=str(project_dir),
    unit_column='unit',
    time_column='period',
    kpi_column='kpi',
    treatment_column='treated',
    control_columns=[],
    confidence=0.9,
)

check('estimate_did: status=ok', result.get('status') == 'ok',
      f'got status={result.get("status")} message={result.get("message")}')

if result.get('status') == 'ok':
    att = result['att']
    err_pct = abs(att['point'] - TRUE_ATT) / TRUE_ATT
    check(f'ATT point estimate within 30% of true {TRUE_ATT} (got {att["point"]:.2f}, err {err_pct*100:.1f}%)',
          err_pct < 0.30)
    check(f'ATT CI contains true value {TRUE_ATT} ([{att["ci_low"]:.2f}, {att["ci_high"]:.2f}])',
          att['ci_low'] <= TRUE_ATT <= att['ci_high'])
    check('ATT ci_method = frequentist_se_clustered', att['ci_method'] == 'frequentist_se_clustered')
    check('ATT confidence = 0.9', att['confidence'] == 0.9)

# ──────────────────────────────────────────────────────────────────
# M1.2 — Diagnostics shape
# ──────────────────────────────────────────────────────────────────
print('\n── M1.2: diagnostics dict shape ──')
diag = result.get('diagnostics', {})
expected_keys = {'panel_metadata', 'parallel_trends_test', 'is_staggered',
                  'p_value', 'r_squared', 'n_observations', 'n_entities', 'n_periods', 'cluster_se_by'}
got_keys = set(diag.keys())
check(f'diagnostics has {len(expected_keys)} expected keys',
      expected_keys.issubset(got_keys),
      f'missing: {expected_keys - got_keys}')

check('non-staggered design correctly detected (is_staggered=False)',
      diag.get('is_staggered') == False)

check('parallel_trends_test populated (p_value present)',
      diag.get('parallel_trends_test', {}).get('p_value') is not None)

check(f'n_observations correct ({len(synth_df)})',
      diag.get('n_observations') == len(synth_df))

check(f'n_entities correct ({len(units)})',
      diag.get('n_entities') == len(units))

# ──────────────────────────────────────────────────────────────────
# M1.3 — HonestDisclosure populated
# ──────────────────────────────────────────────────────────────────
print('\n── M1.3: HonestDisclosure shape ──')
hd = result.get('honest_disclosure', {})
check('honest_disclosure.method = did_twfe', hd.get('method') == 'did_twfe')
check('honest_disclosure.assumptions has ≥3 items',
      len(hd.get('assumptions', [])) >= 3,
      f'got {len(hd.get("assumptions", []))}')
check('honest_disclosure.references has ≥1 academic ref',
      len(hd.get('references', [])) >= 1)
check('honest_disclosure non-staggered passes',
      'non_staggered_2x2_design' in hd.get('diagnostics_passed', []))

# ──────────────────────────────────────────────────────────────────
# M1.4 — Artifact file saved
# ──────────────────────────────────────────────────────────────────
print('\n── M1.4: Artifact persistence ──')
artifact_path = result.get('artifact_path')
check('artifact_path returned in response', artifact_path is not None)
check('artifact file exists', Path(artifact_path).exists() if artifact_path else False)

if artifact_path and Path(artifact_path).exists():
    with open(artifact_path, 'r', encoding='utf-8') as f:
        artifact = json.load(f)
    check('artifact has same status', artifact.get('status') == 'ok')
    check('artifact has same ATT point', abs(artifact['att']['point'] - result['att']['point']) < 1e-6)

# ──────────────────────────────────────────────────────────────────
# M1.5 — Error paths
# ──────────────────────────────────────────────────────────────────
print('\n── M1.5: Error path validation ──')

# Missing column
err_result = estimate_did(
    str(synth_path),
    project_dir=str(project_dir),
    unit_column='nonexistent',
    time_column='period',
    kpi_column='kpi',
    treatment_column='treated',
)
check('missing column → status=error', err_result.get('status') == 'error')
check('missing column → error_code=COLUMNS_MISSING',
      err_result.get('error_code') == 'COLUMNS_MISSING')

# All-untreated panel — wrong treatment encoding
all_zero_df = synth_df.copy()
all_zero_df['treated'] = 0
all_zero_path = REPO / 'test_payloads' / 'synth_did_no_treat.xlsx'
all_zero_df.to_excel(all_zero_path, index=False)

err_result2 = estimate_did(
    str(all_zero_path),
    project_dir=str(project_dir),
    unit_column='unit',
    time_column='period',
    kpi_column='kpi',
    treatment_column='treated',
)
check('all-zero treatment → returns error', err_result2.get('status') == 'error')
check('all-zero treatment → TREATED_UNIT_MISSING',
      err_result2.get('error_code') == 'TREATED_UNIT_MISSING')

# ──────────────────────────────────────────────────────────────────
# M1.6 — Staggered detection
# ──────────────────────────────────────────────────────────────────
print('\n── M1.6: Staggered adoption detection ──')

# Build staggered scenario: region_0 treated from t=5, region_1 from t=8
staggered_rows = []
for u in units:
    for t in periods:
        treat_t = {'region_0': 5, 'region_1': 8}.get(u, 999)
        is_treated = t >= treat_t
        staggered_rows.append({
            'unit': u, 'period': t,
            'kpi': 200 + t * 2 + np.random.normal(0, 5) + (TRUE_ATT if is_treated else 0),
            'treated': 1 if is_treated else 0,
        })
staggered_df = pd.DataFrame(staggered_rows)
staggered_path = REPO / 'test_payloads' / 'synth_did_staggered.xlsx'
staggered_df.to_excel(staggered_path, index=False)

stag_result = estimate_did(
    str(staggered_path),
    project_dir=str(project_dir),
    unit_column='unit',
    time_column='period',
    kpi_column='kpi',
    treatment_column='treated',
)
check('staggered design: status=ok (still computes)', stag_result.get('status') == 'ok')
check('staggered design: is_staggered=True detected',
      stag_result.get('diagnostics', {}).get('is_staggered') == True)
check('staggered design: diagnostics_failed contains staggered_adoption_twfe_biased',
      'staggered_adoption_twfe_biased' in stag_result.get('honest_disclosure', {}).get('diagnostics_failed', []))

# ──────────────────────────────────────────────────────────────────
# Cleanup synthetic files
# ──────────────────────────────────────────────────────────────────
for f in [synth_path, all_zero_path, staggered_path]:
    try:
        f.unlink()
    except Exception:
        pass
# Cleanup artifacts
import shutil
try:
    if (project_dir / 'causal').exists():
        shutil.rmtree(project_dir / 'causal')
except Exception:
    pass

# ──────────────────────────────────────────────────────────────────
print(f'\n{PASSED}/{PASSED + FAILED} assertions passed.')
sys.exit(0 if FAILED == 0 else 1)
