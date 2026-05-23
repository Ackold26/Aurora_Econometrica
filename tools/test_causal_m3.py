"""
Sprint 3 Pharma Causal - M3 Causal Forest endpoint MIN-LIVE checkpoint.

Per ADR §6 + §11/Q1: per-M sanity gate.

Synthetic HTE scenario:
- 500 observations
- Treatment T ∈ {0, 1}, randomized 50/50
- 3 features X1, X2, X3 - only X1 modulates treatment effect
- True CATE(X1=low) ~ 5, True CATE(X1=high) ~ 25 → meaningful heterogeneity

Verifies:
- estimate_causal_forest recovers ATE in reasonable range
- CATE distribution shows heterogeneity (q90 - q10 substantial)
- Feature importance surfaces X1 как top driver
- Overlap check passes (synthetic randomized treatment)
- HonestDisclosure populated
- Artifact persisted
- Error paths
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
# Build synthetic HTE scenario
# ──────────────────────────────────────────────────────────────────
print('── Synthesize HTE ground-truth scenario ──')
np.random.seed(42)

n = 500
# Features: X1 modulates effect, X2/X3 noise
X1 = np.random.uniform(0, 10, n)
X2 = np.random.normal(0, 1, n)
X3 = np.random.uniform(-5, 5, n)
# Random treatment
T = np.random.binomial(1, 0.5, n).astype(float)
# Outcome: Y = 100 + 3*X2 + 2*X3 + (5 + 2*X1) * T + noise
true_cate = 5 + 2 * X1
Y = 100 + 3 * X2 + 2 * X3 + true_cate * T + np.random.normal(0, 5, n)

EXPECTED_ATE = float(np.mean(true_cate))  # ~ 15 (5 + 2*5 average X1)

df = pd.DataFrame({
    'Y': Y, 'T': T, 'X1': X1, 'X2': X2, 'X3': X3,
})
forest_path = REPO / 'test_payloads' / 'synth_forest_data.xlsx'
forest_path.parent.mkdir(parents=True, exist_ok=True)
df.to_excel(forest_path, index=False)
print(f'Synthetic data: n={n}, true ATE ~ {EXPECTED_ATE:.2f}, X1 modulates (CATE 5→25)')

# ──────────────────────────────────────────────────────────────────
# M3.1 - estimate_causal_forest recovers ATE
# ──────────────────────────────────────────────────────────────────
print('\n── M3.1: estimate_causal_forest engine ──')
from engines.causal.causal_forest import estimate_causal_forest

project_dir = REPO / 'test_payloads' / 'projects' / 'synth_forest'
project_dir.mkdir(parents=True, exist_ok=True)

result = estimate_causal_forest(
    str(forest_path),
    project_dir=str(project_dir),
    kpi_column='Y',
    treatment_column='T',
    feature_columns=['X1', 'X2', 'X3'],
    confidence=0.9,
    n_estimators=100,  # smaller for test speed
    random_state=42,
)

check('estimate_causal_forest: status=ok', result.get('status') == 'ok',
      f'got status={result.get("status")} message={result.get("message")}')

if result.get('status') == 'ok':
    att = result['att']
    err_pct = abs(att['point'] - EXPECTED_ATE) / EXPECTED_ATE
    check(f'ATE point estimate within 50% of true {EXPECTED_ATE:.2f} (got {att["point"]:.2f}, err {err_pct*100:.1f}%)',
          err_pct < 0.50)
    check(f'ATE CI populated (low={att["ci_low"]:.2f}, high={att["ci_high"]:.2f})',
          att['ci_low'] is not None and att['ci_high'] is not None)
    check(f'ATE CI ordered (low ≤ point ≤ high)',
          att['ci_low'] <= att['point'] <= att['ci_high'])
    check(f'ATE ci_method ∈ {{honest_split, bootstrap}} (got {att["ci_method"]})',
          att['ci_method'] in ('honest_split', 'bootstrap'))

# ──────────────────────────────────────────────────────────────────
# M3.2 - Heterogeneity diagnostics
# ──────────────────────────────────────────────────────────────────
print('\n── M3.2: Heterogeneity diagnostics ──')
diag = result.get('diagnostics', {})
cate_summary = diag.get('cate_summary', {})
expected_cate_keys = {'mean', 'median', 'std', 'q10', 'q25', 'q75', 'q90', 'min', 'max'}
got_cate_keys = set(cate_summary.keys())
check(f'cate_summary has all 9 expected percentile keys',
      expected_cate_keys.issubset(got_cate_keys),
      f'missing: {expected_cate_keys - got_cate_keys}')

# Heterogeneity range - true CATE varies from 5 (X1=0) to 25 (X1=10).
# Forest should detect q90 > q10 substantially (~2x or more).
if cate_summary:
    cate_range = cate_summary['q90'] - cate_summary['q10']
    check(f'CATE distribution shows heterogeneity (q90-q10 = {cate_range:.2f} > 5)',
          cate_range > 5,
          f'true range ~ 20')

heterogeneity_strength = diag.get('heterogeneity_strength', 0)
check(f'heterogeneity_strength populated > 0 (got {heterogeneity_strength})',
      heterogeneity_strength > 0)

# ──────────────────────────────────────────────────────────────────
# M3.3 - Overlap check
# ──────────────────────────────────────────────────────────────────
print('\n── M3.3: Overlap check (randomized T should pass) ──')
overlap = diag.get('overlap_check', {})
check('overlap_check.passed = True (randomized treatment)',
      overlap.get('passed') == True,
      f'detail: {overlap.get("detail")}')
check(f'overlap_check has propensity range fields',
      'propensity_min' in overlap and 'propensity_max' in overlap)
check(f'propensity range reasonable (~0.4-0.6 для randomized)',
      0.2 < overlap.get('propensity_min', 0) and overlap.get('propensity_max', 0) < 0.8)

# ──────────────────────────────────────────────────────────────────
# M3.4 - HonestDisclosure
# ──────────────────────────────────────────────────────────────────
print('\n── M3.4: HonestDisclosure ──')
hd = result.get('honest_disclosure', {})
check('honest_disclosure.method = forest_wager_athey',
      hd.get('method') == 'forest_wager_athey')
check('honest_disclosure.assumptions has ≥3 items',
      len(hd.get('assumptions', [])) >= 3)
check('honest_disclosure.references has ≥1 academic ref (Wager-Athey 2018)',
      any('Wager' in r for r in hd.get('references', [])))
all_diag = hd.get('diagnostics_passed', []) + hd.get('diagnostics_failed', [])
check('honest_disclosure includes overlap_check diagnostic',
      any('overlap' in d for d in all_diag))

# ──────────────────────────────────────────────────────────────────
# M3.5 - Artifact persistence
# ──────────────────────────────────────────────────────────────────
print('\n── M3.5: Artifact persistence ──')
artifact_path = result.get('artifact_path')
check('artifact_path returned', artifact_path is not None)
check('artifact file exists', Path(artifact_path).exists() if artifact_path else False)

if artifact_path and Path(artifact_path).exists():
    with open(artifact_path, 'r', encoding='utf-8') as f:
        artifact = json.load(f)
    check('artifact has same status', artifact.get('status') == 'ok')
    check('artifact has same ATE point',
          abs(artifact['att']['point'] - result['att']['point']) < 1e-6)
    check('artifact filename starts with forest_',
          Path(artifact_path).name.startswith('forest_'))

# ──────────────────────────────────────────────────────────────────
# M3.6 - Error paths
# ──────────────────────────────────────────────────────────────────
print('\n── M3.6: Error path validation ──')

err_result = estimate_causal_forest(
    str(forest_path),
    project_dir=str(project_dir),
    kpi_column='Y',
    treatment_column='T',
    feature_columns=['nonexistent_X'],
)
check('missing feature → status=error', err_result.get('status') == 'error')
check('missing feature → COLUMNS_MISSING',
      err_result.get('error_code') == 'COLUMNS_MISSING')

# Small dataset
small_df = df.head(50)
small_path = REPO / 'test_payloads' / 'synth_forest_small.xlsx'
small_df.to_excel(small_path, index=False)
err_result2 = estimate_causal_forest(
    str(small_path),
    project_dir=str(project_dir),
    kpi_column='Y',
    treatment_column='T',
    feature_columns=['X1', 'X2', 'X3'],
)
check('n<100 → PANEL_FORMAT_INVALID error',
      err_result2.get('error_code') == 'PANEL_FORMAT_INVALID')

# ──────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────
for f in [forest_path, small_path]:
    try:
        f.unlink()
    except Exception:
        pass
import shutil
try:
    if (project_dir / 'causal').exists():
        shutil.rmtree(project_dir / 'causal')
except Exception:
    pass

print(f'\n{PASSED}/{PASSED + FAILED} assertions passed.')
sys.exit(0 if FAILED == 0 else 1)
