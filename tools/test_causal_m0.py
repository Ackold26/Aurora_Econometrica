"""
Sprint 3 Pharma Causal — M0 stack scaffolding tests.

Run: python tools/test_causal_m0.py

Per ADR §6 + §11/Q1 refinement: per-M MIN-LIVE checkpoint as internal sanity
gate (~30min per M). M0 verifies imports + dataclass invariants + panel data
loader/validator basics — dataset-agnostic.
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
# M0.1 — Sprint 3 dependencies installed and importable
# ──────────────────────────────────────────────────────────────────
print('── M0.1: Dep imports ──')
try:
    import linearmodels
    check(f'linearmodels imports (v{linearmodels.__version__})', True)
except ImportError as e:
    check('linearmodels imports', False, str(e))

try:
    import econml
    check(f'econml imports (v{econml.__version__})', True)
except ImportError as e:
    check('econml imports', False, str(e))

try:
    import statsmodels
    check(f'statsmodels imports (v{statsmodels.__version__})', True)
except ImportError as e:
    check('statsmodels imports', False, str(e))

# ──────────────────────────────────────────────────────────────────
# M0.2 — Causal namespace structure
# ──────────────────────────────────────────────────────────────────
print('\n── M0.2: Causal namespace ──')
from engines.causal import __version__ as cversion
check(f'engines.causal namespace exists (v{cversion})', cversion.startswith('0.1.0'))

from engines.causal.common import ATT, HonestDisclosure, error_response, ERROR_CODES, confidence_to_alpha
check('engines.causal.common: ATT, HonestDisclosure, error_response, ERROR_CODES, confidence_to_alpha imported', True)

from engines.causal._panel_data import (
    load_panel, validate_for_did, validate_for_scm, validate_for_forest,
    synthesize_geo_split, PanelMetadata,
)
check('engines.causal._panel_data: load_panel, validators, synthesize_geo_split, PanelMetadata imported', True)

# ──────────────────────────────────────────────────────────────────
# M0.3 — ATT dataclass invariants
# ──────────────────────────────────────────────────────────────────
print('\n── M0.3: ATT dataclass ──')
att = ATT(point=100.0, ci_low=80.0, ci_high=120.0, ci_method='frequentist_se')
check('ATT positive-only CI: significant=True', att.is_significant)
check('ATT to_dict returns 5 fields', set(att.to_dict().keys()) == {'point', 'ci_low', 'ci_high', 'ci_method', 'confidence'})

att_zero = ATT(point=10.0, ci_low=-5.0, ci_high=25.0, ci_method='bootstrap')
check('ATT zero-crossing CI: significant=False', not att_zero.is_significant)

att_neg = ATT(point=-50.0, ci_low=-80.0, ci_high=-20.0, ci_method='honest_split')
check('ATT negative-only CI: significant=True', att_neg.is_significant)

# ──────────────────────────────────────────────────────────────────
# M0.4 — HonestDisclosure dataclass + blocking semantics
# ──────────────────────────────────────────────────────────────────
print('\n── M0.4: HonestDisclosure ──')
hd_clean = HonestDisclosure(method='did_callaway_santanna', assumptions=['parallel-trends'])
check('HonestDisclosure no failures: not blocked', not hd_clean.is_blocked)

hd_blocked = HonestDisclosure(
    method='scm_abadie_classic',
    diagnostics_failed=['pre_treatment_rmse_high', 'overlap_violation'],
)
check('HonestDisclosure with failed diagnostics: blocked', hd_blocked.is_blocked)
check('HonestDisclosure to_dict has all 6 fields',
      set(hd_blocked.to_dict().keys()) == {'method', 'assumptions', 'caveats', 'diagnostics_passed', 'diagnostics_failed', 'references'})

# ──────────────────────────────────────────────────────────────────
# M0.5 — Error response uniform shape
# ──────────────────────────────────────────────────────────────────
print('\n── M0.5: Error responses ──')
err = error_response('PANEL_FORMAT_INVALID', 'detail тут')
check('error_response has status=error', err['status'] == 'error')
check('error_response has error_code', err['error_code'] == 'PANEL_FORMAT_INVALID')
check('error_response message includes base + detail', 'detail тут' in err['message'])

# Unknown code falls through к code itself
err_unknown = error_response('NEW_CODE_XYZ', '')
check('error_response unknown code: graceful (uses code as msg)', err_unknown['error_code'] == 'NEW_CODE_XYZ')

# ──────────────────────────────────────────────────────────────────
# M0.6 — confidence_to_alpha helper
# ──────────────────────────────────────────────────────────────────
print('\n── M0.6: confidence_to_alpha ──')
check('confidence_to_alpha(0.9) == 0.1', abs(confidence_to_alpha(0.9) - 0.1) < 1e-10)
check('confidence_to_alpha(0.95) == 0.05', abs(confidence_to_alpha(0.95) - 0.05) < 1e-10)
try:
    confidence_to_alpha(1.5)
    check('confidence_to_alpha rejects >1', False, 'should have raised ValueError')
except ValueError:
    check('confidence_to_alpha rejects >1', True)
try:
    confidence_to_alpha(0.0)
    check('confidence_to_alpha rejects 0', False, 'should have raised ValueError')
except ValueError:
    check('confidence_to_alpha rejects 0', True)

# ──────────────────────────────────────────────────────────────────
# M0.7 — Panel data loader on synthetic data
# ──────────────────────────────────────────────────────────────────
print('\n── M0.7: Panel data loader (synthetic) ──')

# Build synthetic balanced panel: 5 regions × 10 periods
np.random.seed(42)
units = [f'region_{i}' for i in range(5)]
periods = list(range(2024, 2034))  # 10 years
rows = []
for u in units:
    for t in periods:
        rows.append({'unit': u, 'period': t, 'kpi': np.random.normal(100, 20), 'treated': 0})
synth_df = pd.DataFrame(rows)
# Mark first 2 units as treated from year 2030
synth_df.loc[(synth_df['unit'].isin(['region_0', 'region_1'])) & (synth_df['period'] >= 2030), 'treated'] = 1

# Save to xlsx
synth_path = REPO / 'test_payloads' / 'synth_panel.xlsx'
synth_path.parent.mkdir(parents=True, exist_ok=True)
synth_df.to_excel(synth_path, index=False)

df, meta, err = load_panel(
    str(synth_path),
    unit_column='unit',
    time_column='period',
    kpi_column='kpi',
    treatment_column='treated',
)
check('load_panel synthetic: no error', err is None, str(err) if err else '')
check('load_panel: df is DataFrame', isinstance(df, pd.DataFrame))
check('load_panel: 50 rows (5 units × 10 periods)', meta.n_obs == 50)
check('load_panel: 5 units detected', meta.n_units == 5)
check('load_panel: 10 periods detected', meta.n_periods == 10)
check('load_panel: balanced=True', meta.is_balanced)
check('load_panel: has_treatment=True', meta.has_treatment)
check('load_panel: 2 treated units detected', len(meta.treated_units) == 2)

# Missing column → COLUMNS_MISSING
df2, meta2, err2 = load_panel(
    str(synth_path),
    unit_column='nonexistent_column',
    time_column='period',
    kpi_column='kpi',
)
check('load_panel missing column: returns COLUMNS_MISSING error', err2 and err2['error_code'] == 'COLUMNS_MISSING')

# ──────────────────────────────────────────────────────────────────
# M0.8 — Panel validators
# ──────────────────────────────────────────────────────────────────
print('\n── M0.8: Panel validators ──')

# DiD validator: passes на нормальной panel
err_did = validate_for_did(meta)
check('validate_for_did: synthetic panel passes', err_did is None, str(err_did) if err_did else '')

# DiD validator: rejects panel without treatment
meta_no_treat = PanelMetadata(
    n_units=5, n_periods=10, n_obs=50, is_balanced=True,
    unit_column='u', time_column='t', kpi_column='k',
    units_list=units, periods_list=periods, has_treatment=False,
)
err_did2 = validate_for_did(meta_no_treat)
check('validate_for_did: rejects no-treatment panel', err_did2 and err_did2['error_code'] == 'PANEL_FORMAT_INVALID')

# SCM validator: passes для valid setup
err_scm = validate_for_scm(meta, treated_unit='region_0', treatment_period=2030)
check('validate_for_scm: synthetic valid passes', err_scm is None, str(err_scm) if err_scm else '')

# SCM validator: rejects unknown unit
err_scm2 = validate_for_scm(meta, treated_unit='nonexistent_region', treatment_period=2030)
check('validate_for_scm: rejects unknown treated_unit', err_scm2 and err_scm2['error_code'] == 'TREATED_UNIT_MISSING')

# SCM validator: rejects insufficient pre-periods
err_scm3 = validate_for_scm(meta, treated_unit='region_0', treatment_period=2025)  # only 1 pre period
check('validate_for_scm: rejects <6 pre-periods', err_scm3 and err_scm3['error_code'] == 'INSUFFICIENT_PRE_PERIODS')

# ──────────────────────────────────────────────────────────────────
# M0.9 — synthesize_geo_split fallback (для M1+ pre-launch блокер mitigation)
# ──────────────────────────────────────────────────────────────────
print('\n── M0.9: synthesize_geo_split (aggregated → panel fallback) ──')

# Aggregate brand-level df (no geo)
agg_df = pd.DataFrame({
    'date': pd.date_range('2024-01-01', periods=12, freq='ME'),
    'kpi_sales': np.random.uniform(100, 200, 12),
    'channel_olv_spend': np.random.uniform(10, 50, 12),
})
n_geo = 4
panel_synth = synthesize_geo_split(agg_df, n_geo=n_geo, seed=42, geo_column_name='region')
check('synthesize: panel rows = original × n_geo',
      len(panel_synth) == len(agg_df) * n_geo,
      f'got {len(panel_synth)} expected {len(agg_df) * n_geo}')
check('synthesize: region column present', 'region' in panel_synth.columns)
check('synthesize: n_geo unique regions', panel_synth['region'].nunique() == n_geo)
check('synthesize: each region has same period count',
      panel_synth.groupby('region').size().nunique() == 1)

# Cleanup synthetic file
try:
    synth_path.unlink()
except Exception:
    pass

# ──────────────────────────────────────────────────────────────────
print(f'\n{PASSED}/{PASSED + FAILED} assertions passed.')
sys.exit(0 if FAILED == 0 else 1)
