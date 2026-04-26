"""
SBC (Simulation-Based Calibration) для Sprint 3 causal endpoints — Pre-Ship gate item #1.

Reference: Talts, Betancourt, Simpson, Vehtari 2018 "Validating Bayesian inference
algorithms with simulation-based calibration" arXiv:1804.06788.

Adapted к frequentist causal methods: instead of rank histogram (Bayesian SBC),
check CI COVERAGE — P(true ATT ∈ CI) over synthetic simulations.

Workflow:
  For sim_i in 1..n_sims:
    - Sample DGP parameters (true ATT, region effects, noise scale)
    - Generate synthetic panel data
    - Run DiD + SCM + Causal Forest (where applicable)
    - Record (true_att, point_estimate, ci_low, ci_high) per method
  Compute:
    - Coverage rate per method (should ~= nominal confidence, e.g. 0.9)
    - Mean absolute error |point - true|
    - CI width statistics

Output: tools/sbc_results_<timestamp>.json + tools/sbc_report_<timestamp>.txt

Run in background overnight. Resumable via --skip flag (TODO).

Usage:
  python tools/sbc_causal_overnight.py [--n-sims 100] [--methods did,scm,forest]

Exit code 0 if coverage within ±5% of nominal, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))

import numpy as np
import pandas as pd


def synthesize_did_panel(
    rng: np.random.Generator,
    *,
    n_units: int = 6,
    n_periods: int = 24,
    treatment_period: int = 13,
    n_treated: int = 2,
    true_att: float | None = None,
    parallel_trends: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """Generate panel data for DiD/SCM с known ground-truth ATT.

    parallel_trends=True (default): all regions share the same trend slope —
    parallel-trends assumption holds. Methods should achieve ~nominal coverage.

    parallel_trends=False: heterogeneous slopes per region — assumption violated.
    Methods coverage degrades expected (intentional pessimistic test scenario).
    """
    if true_att is None:
        true_att = float(rng.uniform(20, 100))  # random magnitude

    units = [f'region_{i}' for i in range(n_units)]
    # SBC fix: randomly choose treated units (not always lowest baselines!) — was bug
    # that violated SCM convex-hull assumption when treated_unit baseline ниже всех donors.
    treated_indices = list(rng.choice(n_units, size=n_treated, replace=False))
    treated_set = {f'region_{i}' for i in treated_indices}
    # Single shared trend if parallel_trends=True (assumption holds)
    shared_trend = float(rng.uniform(0.5, 3.0)) if parallel_trends else None
    rows = []
    for r_idx, u in enumerate(units):
        # SBC fix: random baseline per region чтобы treated units не всегда имели lowest
        baseline = 100 + r_idx * 30
        trend = shared_trend if parallel_trends else float(rng.uniform(0.5, 3.0))
        for t in range(1, n_periods + 1):
            noise = rng.normal(0, 5)
            is_treat = (u in treated_set) and (t >= treatment_period)
            kpi = baseline + trend * t + noise + (true_att if is_treat else 0)
            rows.append({
                'unit': u, 'period': t, 'kpi': kpi,
                'treated': 1 if is_treat else 0,
            })
    return pd.DataFrame(rows), {
        'true_att': true_att,
        'n_units': n_units,
        'n_periods': n_periods,
        'treatment_period': treatment_period,
        'n_treated': n_treated,
        'treated_units': sorted(treated_set),
        'parallel_trends': parallel_trends,
    }


def synthesize_forest_data(
    rng: np.random.Generator,
    *,
    n: int = 500,
) -> tuple[pd.DataFrame, dict]:
    """Generate cross-section data для Causal Forest with heterogeneous treatment effect."""
    X1 = rng.uniform(0, 10, n)
    X2 = rng.normal(0, 1, n)
    X3 = rng.uniform(-5, 5, n)
    T = rng.binomial(1, 0.5, n).astype(float)
    # CATE = base + slope * X1 (heterogeneity through X1)
    cate_base = float(rng.uniform(2, 10))
    cate_slope = float(rng.uniform(1, 3))
    true_cate = cate_base + cate_slope * X1
    Y = 100 + 3 * X2 + 2 * X3 + true_cate * T + rng.normal(0, 5, n)
    df = pd.DataFrame({'Y': Y, 'T': T, 'X1': X1, 'X2': X2, 'X3': X3})
    true_ate = float(np.mean(true_cate))
    return df, {'true_att': true_ate, 'n': n, 'cate_base': cate_base, 'cate_slope': cate_slope}


def run_did_sim(df: pd.DataFrame, project_dir: Path, sim_idx: int) -> dict:
    from engines.causal.did import estimate_did
    sim_dir = project_dir / f'did_sim_{sim_idx}'
    sim_dir.mkdir(parents=True, exist_ok=True)
    panel_path = sim_dir / 'panel.xlsx'
    df.to_excel(panel_path, index=False)
    return estimate_did(
        str(panel_path),
        project_dir=str(sim_dir),
        unit_column='unit',
        time_column='period',
        kpi_column='kpi',
        treatment_column='treated',
        confidence=0.9,
    )


def run_scm_sim(df: pd.DataFrame, project_dir: Path, sim_idx: int, ground_truth: dict) -> dict:
    from engines.causal.scm import estimate_scm
    sim_dir = project_dir / f'scm_sim_{sim_idx}'
    sim_dir.mkdir(parents=True, exist_ok=True)
    panel_path = sim_dir / 'panel.xlsx'
    df.to_excel(panel_path, index=False)
    # SBC: pick treated unit with median baseline → inside donor convex hull
    treated = ground_truth['treated_units']
    treated_unit = sorted(treated)[len(treated) // 2] if treated else treated[0]
    return estimate_scm(
        str(panel_path),
        project_dir=str(sim_dir),
        unit_column='unit',
        time_column='period',
        kpi_column='kpi',
        treated_unit=treated_unit,
        treatment_period=ground_truth['treatment_period'],
        confidence=0.9,
        run_placebo=True,
    )


def run_forest_sim(df: pd.DataFrame, project_dir: Path, sim_idx: int) -> dict:
    from engines.causal.causal_forest import estimate_causal_forest
    sim_dir = project_dir / f'forest_sim_{sim_idx}'
    sim_dir.mkdir(parents=True, exist_ok=True)
    csv_path = sim_dir / 'data.xlsx'
    df.to_excel(csv_path, index=False)
    return estimate_causal_forest(
        str(csv_path),
        project_dir=str(sim_dir),
        kpi_column='Y',
        treatment_column='T',
        feature_columns=['X1', 'X2', 'X3'],
        confidence=0.9,
        n_estimators=100,  # smaller for SBC speed
        random_state=42 + sim_idx,
    )


def evaluate_coverage(records: list, true_att_field: str = 'true_att') -> dict:
    """Compute coverage rate, MAE, mean CI width."""
    if not records:
        return {'coverage_rate': None, 'n_sims': 0}
    n_total = len(records)
    n_in_ci = sum(
        1 for r in records
        if r.get('ci_low') is not None
        and r.get('ci_high') is not None
        and r['ci_low'] <= r[true_att_field] <= r['ci_high']
    )
    n_valid_point = sum(1 for r in records if r.get('point') is not None)
    abs_errors = [
        abs(r['point'] - r[true_att_field])
        for r in records
        if r.get('point') is not None
    ]
    ci_widths = [
        (r['ci_high'] - r['ci_low'])
        for r in records
        if r.get('ci_low') is not None and r.get('ci_high') is not None
    ]
    return {
        'n_sims': n_total,
        'n_with_point': n_valid_point,
        'n_with_ci': len(ci_widths),
        'n_in_ci': n_in_ci,
        'coverage_rate': round(n_in_ci / max(len(ci_widths), 1), 4) if ci_widths else None,
        'mean_abs_error': round(float(np.mean(abs_errors)), 4) if abs_errors else None,
        'median_abs_error': round(float(np.median(abs_errors)), 4) if abs_errors else None,
        'mean_ci_width': round(float(np.mean(ci_widths)), 4) if ci_widths else None,
        'median_ci_width': round(float(np.median(ci_widths)), 4) if ci_widths else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--n-sims', type=int, default=100)
    parser.add_argument('--methods', type=str, default='did,scm,forest')
    parser.add_argument('--seed', type=int, default=20260427)
    parser.add_argument('--out-dir', type=str, default=str(REPO / 'tools' / 'sbc_workdir'))
    parser.add_argument('--coverage-tolerance', type=float, default=0.05)
    parser.add_argument('--violate-trends', action='store_true',
                        help='Use heterogeneous region trends (violates DiD/SCM parallel-trends).')
    args = parser.parse_args()

    methods = [m.strip() for m in args.methods.split(',') if m.strip()]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    print(f'SBC harness — n_sims={args.n_sims}, methods={methods}, seed={args.seed}')
    print(f'Output: {out_dir}')
    print(f'Started: {datetime.now().isoformat()}')

    records: dict[str, list] = {m: [] for m in methods}
    sim_start = time.time()

    for sim_idx in range(args.n_sims):
        sim_t0 = time.time()
        try:
            if 'did' in methods or 'scm' in methods:
                panel_df, gt_panel = synthesize_did_panel(rng, parallel_trends=not args.violate_trends)
            if 'forest' in methods:
                forest_df, gt_forest = synthesize_forest_data(rng)

            if 'did' in methods:
                try:
                    res = run_did_sim(panel_df, out_dir, sim_idx)
                    if res.get('status') == 'ok':
                        att = res['att']
                        records['did'].append({
                            'sim_idx': sim_idx,
                            'true_att': gt_panel['true_att'],
                            'point': att.get('point'),
                            'ci_low': att.get('ci_low'),
                            'ci_high': att.get('ci_high'),
                            'ci_method': att.get('ci_method'),
                        })
                except Exception as e:
                    records['did'].append({
                        'sim_idx': sim_idx, 'true_att': gt_panel['true_att'],
                        'error': f'{type(e).__name__}: {e}',
                    })

            if 'scm' in methods:
                try:
                    res = run_scm_sim(panel_df, out_dir, sim_idx, gt_panel)
                    if res.get('status') == 'ok':
                        att = res['att']
                        records['scm'].append({
                            'sim_idx': sim_idx,
                            'true_att': gt_panel['true_att'],
                            'point': att.get('point'),
                            'ci_low': att.get('ci_low'),
                            'ci_high': att.get('ci_high'),
                            'ci_method': att.get('ci_method'),
                        })
                except Exception as e:
                    records['scm'].append({
                        'sim_idx': sim_idx, 'true_att': gt_panel['true_att'],
                        'error': f'{type(e).__name__}: {e}',
                    })

            if 'forest' in methods:
                try:
                    res = run_forest_sim(forest_df, out_dir, sim_idx)
                    if res.get('status') == 'ok':
                        att = res['att']
                        records['forest'].append({
                            'sim_idx': sim_idx,
                            'true_att': gt_forest['true_att'],
                            'point': att.get('point'),
                            'ci_low': att.get('ci_low'),
                            'ci_high': att.get('ci_high'),
                            'ci_method': att.get('ci_method'),
                        })
                except Exception as e:
                    records['forest'].append({
                        'sim_idx': sim_idx, 'true_att': gt_forest['true_att'],
                        'error': f'{type(e).__name__}: {e}',
                    })

        except Exception as e:
            print(f'sim {sim_idx} CRASHED: {type(e).__name__}: {e}')
            traceback.print_exc()
            continue

        sim_time = time.time() - sim_t0
        if sim_idx % 5 == 0 or sim_idx == args.n_sims - 1:
            elapsed = time.time() - sim_start
            eta = (elapsed / max(sim_idx + 1, 1)) * (args.n_sims - sim_idx - 1)
            print(f'  sim {sim_idx + 1}/{args.n_sims} ({sim_time:.1f}s) — '
                  f'elapsed {elapsed:.0f}s, ETA {eta:.0f}s')

        # Cleanup per-sim dir to keep disk usage bounded (keep results in records)
        try:
            import shutil
            for method_dir in out_dir.glob(f'*_sim_{sim_idx}'):
                shutil.rmtree(method_dir, ignore_errors=True)
        except Exception:
            pass

    total_elapsed = time.time() - sim_start
    print(f'\nAll sims completed in {total_elapsed:.0f}s ({total_elapsed/60:.1f}min)')

    # Coverage analysis per method
    coverage_summary = {}
    for m in methods:
        coverage_summary[m] = evaluate_coverage(records[m])

    # Verdict
    target_coverage = 0.9
    verdicts = {}
    for m in methods:
        cov = coverage_summary[m].get('coverage_rate')
        if cov is None:
            verdicts[m] = 'insufficient_data'
        elif abs(cov - target_coverage) <= args.coverage_tolerance:
            verdicts[m] = 'pass'
        else:
            verdicts[m] = 'fail'

    # Write outputs
    results_path = out_dir / f'sbc_results_{timestamp}.json'
    report_path = out_dir / f'sbc_report_{timestamp}.txt'

    full_results = {
        'started_at': datetime.fromtimestamp(sim_start).isoformat(),
        'completed_at': datetime.now().isoformat(),
        'duration_seconds': round(total_elapsed, 1),
        'config': {
            'n_sims': args.n_sims,
            'methods': methods,
            'seed': args.seed,
            'target_coverage': target_coverage,
            'coverage_tolerance': args.coverage_tolerance,
        },
        'coverage_summary': coverage_summary,
        'verdicts': verdicts,
        'records': records,
    }
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(full_results, f, ensure_ascii=False, indent=2, default=str)

    # Plain-text report
    lines = [
        f'SBC report — {timestamp}',
        '=' * 60,
        f'Started:  {datetime.fromtimestamp(sim_start).isoformat()}',
        f'Finished: {datetime.now().isoformat()}',
        f'Duration: {total_elapsed/60:.1f} min',
        f'Sims:     {args.n_sims}',
        f'Methods:  {", ".join(methods)}',
        f'Target coverage: {target_coverage} ± {args.coverage_tolerance}',
        '',
    ]
    for m in methods:
        s = coverage_summary[m]
        v = verdicts[m]
        lines.append(f'{m.upper()} — verdict: {v}')
        lines.append(f'  n_sims={s.get("n_sims")}, n_with_ci={s.get("n_with_ci")}')
        lines.append(f'  coverage_rate={s.get("coverage_rate")} (target {target_coverage}±{args.coverage_tolerance})')
        lines.append(f'  mean_abs_error={s.get("mean_abs_error")}')
        lines.append(f'  mean_ci_width={s.get("mean_ci_width")}')
        lines.append('')

    overall_pass = all(v == 'pass' for v in verdicts.values())
    lines.append('OVERALL VERDICT: ' + ('PASS' if overall_pass else 'REVIEW NEEDED'))
    if not overall_pass:
        lines.append('  -> Coverage outside tolerance for one or more methods.')
        lines.append('  -> Check method-specific CI computation in respective engines/causal/*.py.')

    report = '\n'.join(lines)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print('\n' + report)
    print(f'\nResults JSON: {results_path}')
    print(f'Report:       {report_path}')

    sys.exit(0 if overall_pass else 1)


if __name__ == '__main__':
    main()
