"""
Headless validation harness for Aurora Econometrica MMM.

Runs a sample .xlsx through the program's OWN engines (no reimplementation) and
reports five facts:

  1. Per-column detected role via column_detection.classify_column +
     detect_media_format. Flags any column classified as 'unknown'.
  2. Fitted MMM decomposition: contribution share per channel/control and base.
  3. MQS (model quality score) band / score + effective-parameters figure.
  4. Whether an overfitting / low-effective-params warning fires.
  5. Whether credible / bootstrap CI are present in the result.

Model path: OLS engine (train_ols).
  - Runs in <5s on typical files (no MCMC sampling).
  - CI = frequentist bootstrap ROI intervals (per channel, stored in pickle).
  - Posterior Bayesian CI NOT available on OLS path; flagged in output.

Usage:
    python tools/validate_sample_data.py path/to/data.xlsx

    # From repo root:
    python sidecar/econometrica/tools/validate_sample_data.py \
        static/sample-data/synth_fmcg_brand.xlsx

API:
    from tools.validate_sample_data import validate
    report = validate("path/to/data.xlsx")   # returns dict with 5 fact keys
"""

from __future__ import annotations

import sys
import time
import tempfile
import logging
from pathlib import Path
from typing import Any

# ── make sure sidecar package root is on sys.path ──────────────────────────
# Works when script is run from sidecar/econometrica/ OR from repo root.
_SIDECAR_DIR = Path(__file__).resolve().parent.parent / 'sidecar' / 'econometrica'   # repo_root/sidecar/econometrica/
if str(_SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(_SIDECAR_DIR))

import pandas as pd

logger = logging.getLogger(__name__)

# ── ColumnKind groups used for role assignment ─────────────────────────────
_MEDIA_KINDS = frozenset({'monetary', 'physical'})
_TARGET_KINDS = frozenset({'target_monetary', 'target_count'})
_CONTROL_KINDS = frozenset({
    'control', 'signed_competitor', 'signed_price',
    'signed_weather', 'signed_macro', 'holiday',
})


def _auto_split_columns(classified: dict[str, str]) -> dict[str, list[str]]:
    """Split classified columns into kpi / media / control / date / unknown."""
    kpi, media, control, date_cols, unknown = [], [], [], [], []
    for col, kind in classified.items():
        if kind == 'date':
            date_cols.append(col)
        elif kind in _TARGET_KINDS:
            kpi.append(col)
        elif kind in _MEDIA_KINDS:
            media.append(col)
        elif kind in _CONTROL_KINDS:
            control.append(col)
        else:
            unknown.append(col)
    return {
        'kpi': kpi,
        'media': media,
        'control': control,
        'date': date_cols,
        'unknown': unknown,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def validate(xlsx_path: str | Path) -> dict[str, Any]:
    """Run detect → OLS model → decompose → MQS → CI check.

    Args:
        xlsx_path: absolute or relative path to an .xlsx (or .csv) data file.

    Returns:
        dict with keys:
          column_roles      – per-column {name: {kind, media_format, flagged_unknown}}
          unknown_columns   – list of column names classified as 'unknown'
          decomposition     – {baseline_pct, channels: [{name, contribution_pct, roi,
                                roi_ci_low, roi_ci_high, ci_method, verdict}],
                               signed_factors: {name: {pct, type}}}
          mqs               – {score, tier, tier_label, thinness_cap, ratio,
                                effective_params, nominal_params, n_obs, verdict_text,
                                components}
          warnings          – {overfitting: bool, low_effective_params: bool,
                                model_warning: str | None, messages: [str]}
          ci_present        – {present: bool, method: str, channels_with_ci: [str]}
          model_path        – {engine, version, project_tmp_dir}
          runtime_seconds   – wall-clock seconds for train+decompose
    """
    t0 = time.perf_counter()
    xlsx_path = Path(xlsx_path).resolve()

    # ── 1. Column detection ─────────────────────────────────────────────────
    from utils.column_detection import classify_columns, classify_column, detect_media_format

    df_probe = pd.read_excel(xlsx_path) if xlsx_path.suffix.lower() in ('.xlsx', '.xls') \
               else pd.read_csv(xlsx_path)
    all_columns = df_probe.columns.tolist()

    classified = classify_columns(all_columns)

    column_roles: dict[str, dict] = {}
    for col, kind in classified.items():
        fmt = detect_media_format(col) if kind in _MEDIA_KINDS else 'n/a'
        column_roles[col] = {
            'kind': kind,
            'media_format': fmt,
            'flagged_unknown': (kind == 'unknown'),
        }

    unknown_columns = [c for c, info in column_roles.items() if info['flagged_unknown']]
    split = _auto_split_columns(classified)

    # Guard: need at least one KPI and one media column to train
    if not split['kpi']:
        return _error_result('No KPI column detected (target_monetary / target_count)')
    if not split['media']:
        return _error_result('No media columns detected (monetary / physical)')
    if not split['date']:
        return _error_result('No date column detected')

    kpi_col = split['kpi'][0]          # first detected target
    media_cols = split['media']
    control_cols = split['control']
    date_col = split['date'][0]

    # ── 2. OLS training (fastest path: closed-form, no MCMC) ───────────────
    from engines.ols_modeler import train_ols

    project_tmp = tempfile.mkdtemp(prefix='econometrica_val_')

    config: dict[str, Any] = {
        'data_file': str(xlsx_path),
        'kpi_column': kpi_col,
        'media_columns': media_cols,
        'control_columns': control_cols,
        'date_column': date_col,
        'adstock_config': {},   # library defaults (geometric, decay=0.5)
        'unit_costs': {},       # no cost scaling — harness uses raw channel units
    }

    train_result = train_ols(config, project_tmp)
    if train_result.get('status') != 'ok':
        return _error_result(
            f"OLS training failed: {train_result.get('message', train_result.get('error_code'))}"
        )

    ols_diag = train_result['diagnostics']

    # ── 3. Decomposition ────────────────────────────────────────────────────
    from engines.decomposer import decompose

    dec = decompose(project_tmp)
    if dec.get('status') != 'ok':
        return _error_result(
            f"Decompose failed: {dec.get('message', dec.get('error_code'))}"
        )

    # ── 4. MQS ─────────────────────────────────────────────────────────────
    from utils.diagnostics import generate_diagnostics_summary

    m = ols_diag['metrics']
    # OLS diagnostics fields
    r_squared = m['r_squared']
    mape = m['mape']
    # Residual std in original units → use as RMSE proxy (not exactly same but
    # generate_diagnostics_summary only uses r_squared + mape + r_hat + divergences)
    rmse_proxy = m.get('residual_std', 0.0) or 0.0
    n_obs = ols_diag['n_obs']
    n_params = ols_diag['n_params']

    mqs_full = generate_diagnostics_summary(
        r_squared=r_squared,
        mape=mape,
        rmse=rmse_proxy,
        r_hat_max=1.0,    # OLS has no MCMC chains → no R-hat; treat as converged
        divergences=0,    # same
        n_obs=n_obs,
        n_params=n_params,
        effective_params=None,  # OLS path: no posterior contraction; uses nominal ratio
    )
    mqs_data = mqs_full['mqs']

    # ── 5. Warning flags ─────────────────────────────────────────────────────
    overfit_warning = (mqs_data.get('thinness_cap') is not None)
    low_eff_params = (mqs_full['metrics']['ratio'] < 4.0)
    model_warning_str = dec.get('model_warning')   # OLS disclosure from decomposer

    warn_messages: list[str] = []
    if overfit_warning:
        warn_messages.append(
            f"Data-thinness cap active: ratio={mqs_full['metrics']['ratio']:.1f} "
            f"(cap={mqs_data['thinness_cap']} — high overfitting risk)"
        )
    if low_eff_params:
        warn_messages.append(
            f"Low obs/params ratio ({mqs_full['metrics']['ratio']:.1f} < 4.0): "
            "wide CIs likely, treat results as directional"
        )
    if model_warning_str:
        warn_messages.append(f"Model: {model_warning_str}")

    # ── 6. CI presence check ─────────────────────────────────────────────────
    channels_with_ci: list[str] = []
    ci_methods: set[str] = set()
    for ch in dec.get('channels', []):
        if ch.get('roi_ci_low') is not None and ch.get('roi_ci_high') is not None:
            channels_with_ci.append(ch['name'])
            m_str = ch.get('ci_method', 'unknown')
            ci_methods.add(m_str)

    ci_present = len(channels_with_ci) > 0
    ci_method_str = ', '.join(sorted(ci_methods)) if ci_methods else 'none'

    # ── 7. Build structured decomposition output ──────────────────────────
    channels_out = []
    for ch in dec.get('channels', []):
        channels_out.append({
            'name': ch['name'],
            'contribution_pct': ch.get('contribution_pct', 0.0),
            'roi': ch.get('roi'),
            'roi_ci_low': ch.get('roi_ci_low'),
            'roi_ci_high': ch.get('roi_ci_high'),
            'ci_method': ch.get('ci_method'),
            'verdict': ch.get('verdict', ''),
            'verdict_tone': ch.get('verdict_tone', ''),
            'spend': ch.get('spend'),
            'contribution': ch.get('contribution'),
        })

    signed_factors_out: dict[str, dict] = {}
    for fname, fdata in (dec.get('signed_factor_contributions') or {}).items():
        signed_factors_out[fname] = {
            'pct': fdata.get('pct', 0.0),
            'value': fdata.get('value', 0.0),
            'type': fdata.get('type', 'unknown'),
        }

    runtime = round(time.perf_counter() - t0, 2)

    return {
        # Fact 1: per-column roles
        'column_roles': column_roles,
        'unknown_columns': unknown_columns,

        # Fact 2: decomposition shares
        'decomposition': {
            'baseline_pct': dec.get('baseline_pct', 0.0),
            'total_sales': dec.get('total_sales'),
            'baseline': dec.get('baseline'),
            'media_contribution': dec.get('media_contribution'),
            'channels': channels_out,
            'signed_factors': signed_factors_out,
            'kpi_col': kpi_col,
            'kpi_kind': dec.get('kpi_kind', 'monetary'),
        },

        # Fact 3: MQS
        'mqs': {
            'score': mqs_data['score'],
            'raw_score': mqs_data.get('raw_score', mqs_data['score']),
            'tier': mqs_data['tier'],
            'tier_label': mqs_data['tier_label'],
            'thinness_cap': mqs_data.get('thinness_cap'),
            'ratio': mqs_full['metrics']['ratio'],
            'ratio_nominal': mqs_full['metrics']['ratio_nominal'],
            'effective_params': mqs_full['metrics']['effective_parameters'],
            'nominal_params': n_params,
            'n_obs': n_obs,
            'verdict_text': mqs_full['verdict'],
            'components': mqs_data.get('components', {}),
        },

        # Fact 4: overfitting / low-effective-params warnings
        'warnings': {
            'overfitting': overfit_warning,
            'low_effective_params': low_eff_params,
            'model_warning': model_warning_str,
            'messages': warn_messages,
        },

        # Fact 5: CI presence
        'ci_present': {
            'present': ci_present,
            'method': ci_method_str,
            'channels_with_ci': channels_with_ci,
            'note': (
                'OLS path: frequentist bootstrap ROI CI (no posterior Bayesian CI). '
                'For Bayesian posterior CI retrain with n>=30 on Bayesian engine.'
            ),
        },

        # Meta
        'model_path': {
            'engine': 'ols',
            'version': '1.0-ols',
            'project_tmp_dir': project_tmp,
        },
        'runtime_seconds': runtime,
    }


def _error_result(message: str) -> dict[str, Any]:
    return {'status': 'error', 'message': message}


# ─────────────────────────────────────────────────────────────────────────────
# __main__ — pretty-print report
# ─────────────────────────────────────────────────────────────────────────────

def _print_report(report: dict, xlsx_path: str) -> None:
    """Print a human-readable validation report to stdout."""
    if report.get('status') == 'error':
        print(f"\n[VALIDATION ERROR] {report['message']}")
        return

    bar = '=' * 70

    print(f"\n{bar}")
    print(f"  Aurora Econometrica — Headless Validation Report")
    print(f"  File : {xlsx_path}")
    print(f"  Time : {report['runtime_seconds']}s   Engine: OLS (v1.0-ols)")
    print(bar)

    # ── Fact 1: Column roles ────────────────────────────────────────────────
    print("\n[1] COLUMN ROLES")
    print(f"  {'Column':<30} {'Kind':<20} {'Media Format':<18} Unknown?")
    print(f"  {'-'*30} {'-'*20} {'-'*18} -------")
    for col, info in report['column_roles'].items():
        flagged = '  *** UNKNOWN ***' if info['flagged_unknown'] else ''
        fmt_str = info['media_format'] if info['media_format'] != 'n/a' else '-'
        print(f"  {col:<30} {info['kind']:<20} {fmt_str:<18}{flagged}")

    unknowns = report['unknown_columns']
    if unknowns:
        print(f"\n  *** {len(unknowns)} UNKNOWN column(s): {unknowns} ***")
    else:
        print(f"\n  All columns classified — no unknowns.")

    # ── Fact 2: Decomposition ───────────────────────────────────────────────
    dec = report['decomposition']
    print(f"\n[2] DECOMPOSITION  (KPI: {dec['kpi_col']}, kind={dec['kpi_kind']})")
    print(f"  Total sales : {dec['total_sales']:>15,.0f}")
    print(f"  Baseline    : {dec['baseline']:>15,.0f}   ({dec['baseline_pct']:.1f}%)")
    print(f"  Media total : {dec['media_contribution']:>15,.0f}")
    print()
    print(f"  {'Channel':<28} {'Share%':>7}  {'ROI':>8}  {'CI Low':>10}  {'CI High':>10}  Verdict")
    print(f"  {'-'*28} {'-'*7}  {'-'*8}  {'-'*10}  {'-'*10}  -------")
    for ch in dec['channels']:
        ci_lo = f"{ch['roi_ci_low']:.2f}" if ch['roi_ci_low'] is not None else '     -'
        ci_hi = f"{ch['roi_ci_high']:.2f}" if ch['roi_ci_high'] is not None else '     -'
        roi_s = f"{ch['roi']:.2f}" if ch['roi'] is not None else '    -'
        print(f"  {ch['name']:<28} {ch['contribution_pct']:>7.1f}  {roi_s:>8}  {ci_lo:>10}  {ci_hi:>10}  {ch['verdict']}")

    if dec['signed_factors']:
        print()
        print(f"  {'Signed factor':<28} {'Share%':>7}  {'Type'}")
        print(f"  {'-'*28} {'-'*7}  {'-'*20}")
        for fname, finfo in dec['signed_factors'].items():
            print(f"  {fname:<28} {finfo['pct']:>7.1f}  {finfo['type']}")

    # ── Fact 3: MQS ─────────────────────────────────────────────────────────
    mqs = report['mqs']
    print(f"\n[3] MQS (Model Quality Score)")
    print(f"  Score       : {mqs['score']} / 100  ({mqs['tier_label']}  tier={mqs['tier']})")
    if mqs['thinness_cap'] is not None:
        print(f"  Thinness cap: {mqs['thinness_cap']} (applied — data is thin)")
    else:
        print(f"  Thinness cap: none (data volume OK)")
    print(f"  Eff. params : {mqs['effective_params']} (nominal {mqs['nominal_params']}, n_obs {mqs['n_obs']})")
    print(f"  Eff. ratio  : {mqs['ratio']:.1f} obs/param  (nominal ratio {mqs['ratio_nominal']:.1f})")
    comps = mqs['components']
    if comps:
        r2c = comps.get('r_squared', {})
        mpec = comps.get('mape', {})
        cnvc = comps.get('convergence', {})
        print(f"  Components  : R²={r2c.get('value','?')} (score {r2c.get('score','?')}) | "
              f"MAPE={mpec.get('value','?')}% (score {mpec.get('score','?')}) | "
              f"convergence score={cnvc.get('score','?')}")
    print(f"  Verdict     : {mqs['verdict_text']}")

    # ── Fact 4: Warnings ─────────────────────────────────────────────────────
    w = report['warnings']
    print(f"\n[4] WARNINGS")
    print(f"  Overfitting flag   : {w['overfitting']}")
    print(f"  Low-eff-params flag: {w['low_effective_params']}")
    if w['messages']:
        for msg in w['messages']:
            print(f"  MSG: {msg}")
    else:
        print(f"  No active warnings.")

    # ── Fact 5: CI ───────────────────────────────────────────────────────────
    ci = report['ci_present']
    print(f"\n[5] CREDIBLE / BOOTSTRAP INTERVALS")
    print(f"  CI present : {ci['present']}")
    print(f"  Method     : {ci['method']}")
    print(f"  Channels   : {ci['channels_with_ci']}")
    print(f"  Note       : {ci['note']}")

    print(f"\n{bar}")
    print(f"  Validation complete.  Runtime: {report['runtime_seconds']}s")
    print(bar)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Headless MMM validation harness (Aurora Econometrica)'
    )
    parser.add_argument('xlsx_path', help='Path to .xlsx (or .csv) sample data file')
    parser.add_argument('--log-level', default='WARNING',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Python logging level (default: WARNING)')
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level),
                        format='%(levelname)s %(name)s: %(message)s')

    report = validate(args.xlsx_path)
    _print_report(report, args.xlsx_path)
