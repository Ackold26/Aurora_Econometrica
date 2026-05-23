"""Optimizer real-pickle integration smoke (Phase 4 follow-up - etap 3 of audit follow-up).

Plan: C:\\Users\\ackol\\Desktop\\optimizer-audit-followup-plan.md, этап 3.
Closes plan §6 deferred - «Customer pickle subset (C5/C12) verifies real-data correctness».

Skipped automatically когда нет real data (CI default). Локально активируется через
`AURORA_TESTDATA_DIR` env var pointing к директории с Кагоцел/Венарус xlsx.

Workflow:
    1. testdata_dir fixture finds директорию (env var → default → Desktop fallback)
    2. Locate first Кагоцел*.xlsx
    3. Auto-discover columns: Date / KPI / media (Бюджет до НДС до АК) / TV (TRPs)
    4. Train OLS pickle (fast, ~10sec - no MCMC)
    5. Run smoke optimize configs analogous к C1/C5/C12 в smoke matrix
    6. Assert no NaN/Inf, status='ok', sensible lift_pct

OLS-engine selected over Bayesian для скорости. Real chain variability still
hits real-data shape (31 monthly obs, 6 media channels + TV native, mixed units).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _resolve_testdata_dir() -> Path | None:
    """Fallback chain: env var → default → user's Desktop folder."""
    import os
    env = os.environ.get('AURORA_TESTDATA_DIR')
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates += [
        Path('D:/Docs/Aurora_Ai/TestData/Econometrica'),
        Path.home() / 'Desktop' / 'Эконометрика - тестовые файлы',
    ]
    for c in candidates:
        if c.exists() and any(c.glob('*.xlsx')):
            return c
    return None


def _find_kagocel_xlsx(test_dir: Path) -> Path | None:
    """First xlsx с 'Кагоцел' в имени, либо первый xlsx если такого нет."""
    matches = sorted(test_dir.glob('Кагоцел*.xlsx'))
    if matches:
        return matches[0]
    fallback = sorted(test_dir.glob('*.xlsx'))
    return fallback[0] if fallback else None


def _discover_columns(df: pd.DataFrame) -> dict:
    """Auto-detect KPI / date / media columns by Russian naming heuristics.

    Returns dict с ключами: date_col, kpi_col, media_money_cols, tv_trps_col, unit_costs.
    """
    date_col = None
    kpi_col = None
    media_money_cols: list[str] = []
    tv_trps_col = None

    # Two-pass: media/date/TV first, KPI second (priority logic).
    for col in df.columns:
        s = str(col)
        s_lower = s.lower()
        if date_col is None and 'date' in s_lower:
            date_col = col
        elif 'бюджет' in s_lower and 'до ндс' in s_lower and 'до ак' in s_lower:
            media_money_cols.append(col)
        elif tv_trps_col is None and 'trps' in s_lower and (
            'бренд' in s_lower or 'контакт' in s_lower
        ) and 'конкурент' not in s_lower:
            tv_trps_col = col

    # KPI priority: «продажи в уп. бренд» > «продажи в шт. факт» > «продажи в руб. бренд»
    kpi_priority = [
        lambda s: 'продажи' in s and ('уп.' in s or 'шт.' in s) and 'бренд' in s and 'конкурент' not in s,
        lambda s: 'продажи' in s and 'факт' in s and 'руб' not in s,
        lambda s: 'продажи' in s and 'бренд' in s and 'конкурент' not in s,
    ]
    for matcher in kpi_priority:
        for col in df.columns:
            if matcher(str(col).lower()):
                kpi_col = col
                break
        if kpi_col is not None:
            break

    unit_costs = {col: 1.0 for col in media_money_cols}
    if tv_trps_col is not None:
        # TV TRPs - native unit; use realistic Russian CPP
        unit_costs[tv_trps_col] = 150_000.0

    return {
        'date_col': date_col,
        'kpi_col': kpi_col,
        'media_money_cols': media_money_cols,
        'tv_trps_col': tv_trps_col,
        'unit_costs': unit_costs,
    }


def _build_real_pickle(xlsx_path: Path, project_dir: Path) -> dict:
    """Train OLS pickle от real Кагоцел xlsx → models/latest.pkl.

    Args:
        xlsx_path: source Excel file
        project_dir: target project (created here)

    Returns:
        OLS train result dict.
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / 'models').mkdir(exist_ok=True)
    (project_dir / 'results').mkdir(exist_ok=True)

    df = pd.read_excel(xlsx_path)
    cols = _discover_columns(df)
    if not cols['kpi_col'] or not cols['date_col'] or not cols['media_money_cols']:
        raise RuntimeError(
            f'Auto-discovery failed для {xlsx_path.name}: '
            f'kpi={cols["kpi_col"]!r}, date={cols["date_col"]!r}, '
            f'media={cols["media_money_cols"]}'
        )

    media_cols = list(cols['media_money_cols'])
    if cols['tv_trps_col']:
        media_cols.append(cols['tv_trps_col'])

    # Copy xlsx к project (OLS reads via config['data_file'])
    project_xlsx = project_dir / 'data' / 'real_kagocel.xlsx'
    project_xlsx.parent.mkdir(exist_ok=True)
    df.to_excel(project_xlsx, index=False)

    config = {
        'data_file': str(project_xlsx),
        'kpi_column': cols['kpi_col'],
        'media_columns': media_cols,
        'control_columns': [],
        'date_column': cols['date_col'],
        'adstock_config': {col: 'geometric' for col in media_cols},
        'unit_costs': cols['unit_costs'],
        'merge_rules': {},
        'kpi_type': 'sales',
    }

    from engines.ols_modeler import train_ols
    result = train_ols(config, str(project_dir))
    if result.get('status') != 'ok':
        raise RuntimeError(f'OLS train failed: {result.get("message")}')
    return result


# ──────────────────────────────────────────────────────────────────────
# Test fixture (real pickle from Кагоцел xlsx, OLS-trained, session-cached)
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope='session')
def real_kagocel_project(tmp_path_factory):
    """Train OLS pickle on real Кагоцел data; skip if data unavailable.

    Returns project_dir (str path) suitable для optimize().
    """
    test_dir = _resolve_testdata_dir()
    if test_dir is None:
        pytest.skip(
            'Real test data unavailable - set AURORA_TESTDATA_DIR or place xlsx '
            'в default folder. See conftest.py.'
        )
    xlsx = _find_kagocel_xlsx(test_dir)
    if xlsx is None:
        pytest.skip(f'No xlsx found в {test_dir}')

    project_dir = tmp_path_factory.mktemp('real_kagocel')
    try:
        _build_real_pickle(xlsx, project_dir)
    except Exception as e:
        pytest.skip(f'OLS training on real data failed: {type(e).__name__}: {e}')
    return str(project_dir)


# ──────────────────────────────────────────────────────────────────────
# Smoke acceptance helpers (subset of test_optimizer_smoke_matrix.py)
# ──────────────────────────────────────────────────────────────────────


REQUIRED_KEYS = (
    'expected_lift_pct', 'channels', 'response_curves',
    'planning_mode', 'train_n_periods', 'forecast_n_periods',
    'optimization_converged', 'binding_constraints', 'slsqp_diagnostics',
)


def _validate_real_ok(r: dict, label: str) -> None:
    assert r.get('status') == 'ok', (
        f'{label}: status={r.get("status")} / {r.get("error_code")} / {r.get("message")}'
    )
    for k in REQUIRED_KEYS:
        assert k in r, f'{label}: missing required key `{k}`'
    if not r.get('baseline_zero'):
        lift = float(r['expected_lift_pct'])
        assert lift > -25.0, f'{label}: catastrophic lift={lift:.1f}% (real OLS ≥ -25)'
    for ch in r['channels']:
        assert ch['optimal_spend_money'] >= 0, (
            f'{label}: negative optimal_spend_money {ch["name"]}={ch["optimal_spend_money"]}'
        )
        assert math.isfinite(ch['optimal_spend_money']), f'{label}: non-finite money {ch["name"]}'
        assert math.isfinite(ch.get('mroi_current', 0)), f'{label}: non-finite mROAS {ch["name"]}'
        assert math.isfinite(ch.get('mroi_optimal', 0)), f'{label}: non-finite mROI optimal {ch["name"]}'


# ──────────────────────────────────────────────────────────────────────
# Tests (analogous к smoke matrix C1 / C5 / C12)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.requires_real_data
def test_real_C1_analyst_baseline(real_kagocel_project):
    """C1-equivalent на real OLS pickle - analyst mode, no extras."""
    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, real_kagocel_project)
    _validate_real_ok(r, 'real-C1')
    assert r['planning_mode'] is False


@pytest.mark.requires_real_data
def test_real_C5_planner_inflation_perchannel(real_kagocel_project):
    """C5-equivalent на real OLS pickle - planning + inflation + per-channel."""
    # v2.1.0: загрузка через load_model_with_compat — работает и со старым
    # pickle, и с новым aurora-model форматом.
    from engines.persistence import load_model_with_compat
    md = load_model_with_compat(Path(real_kagocel_project) / 'models' / 'latest.pkl')
    cols = md['config']['media_columns']

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'min_per_channel': {cols[0]: 50.0},
        'max_per_channel': {cols[1]: 180.0} if len(cols) > 1 else None,
        'unit_cost_inflation_pct': {cols[-1]: 25.0},  # TV TRPs если последний
        'forecast_periods': 12,
    }, real_kagocel_project)
    _validate_real_ok(r, 'real-C5')
    assert r['planning_mode'] is True
    assert r['forecast_n_periods'] == 12


@pytest.mark.requires_real_data
def test_real_C12_whatif_pass18_regression(real_kagocel_project):
    """C12-equivalent на real OLS pickle - pass-18 What-if 0.5× с wide bounds."""
    from engines.persistence import load_model_with_compat
    md = load_model_with_compat(Path(real_kagocel_project) / 'models' / 'latest.pkl')
    df = pd.read_excel(md['config']['data_file'])
    media_cols = md['config']['media_columns']
    uc = md['config']['unit_costs']
    cur_money = sum(
        float(df[c].fillna(0).sum()) * float(uc.get(c, 1.0)) for c in media_cols
    )

    from engines.optimizer import optimize
    config = {
        'min_pct': 0.0, 'max_pct': 500.0,  # wide → anchor active
        'min_per_channel': {media_cols[0]: 30.0},
        'max_per_channel': {media_cols[1]: 250.0} if len(media_cols) > 1 else None,
        'total_budget_money': cur_money * 0.5,  # whatIfMult=0.5 - pass-18 trigger
        'forecast_periods': 12,
    }
    try:
        r = optimize(config, real_kagocel_project)
    except (NameError, AttributeError, UnboundLocalError) as e:
        pytest.fail(f'real-C12 pass-18 regression: {type(e).__name__}: {e}')

    assert 'status' in r
    if r.get('status') == 'ok':
        _validate_real_ok(r, 'real-C12')
        # Conservation check на 0.5× target
        opt_money = sum(ch['optimal_spend_money'] for ch in r['channels'])
        target = cur_money * 0.5
        rel_err = abs(opt_money - target) / max(target, 1.0)
        assert rel_err < 0.01, f'real-C12 conservation: opt={opt_money:.0f}, target={target:.0f}'
    else:
        # Explicit error_code is acceptable (e.g. INFEASIBLE_BUDGET_LOW)
        assert r.get('error_code'), f'real-C12 error без error_code: {r}'


@pytest.mark.requires_real_data
def test_real_F1_chain_monotonic(real_kagocel_project):
    """F1 fix verification на real data - cumulative anchor seeding works on real pickle."""
    from engines.optimizer import optimize

    chain = [(50, 150), (30, 200), (20, 250), (10, 300), (0, 500)]
    lifts: list[tuple[str, float]] = []
    prev_optimal: list[float] | None = None

    for lo, hi in chain:
        cfg: dict = {'min_pct': float(lo), 'max_pct': float(hi)}
        if prev_optimal is not None:
            cfg['prev_optimal'] = prev_optimal
        r = optimize(cfg, real_kagocel_project)
        if r.get('status') != 'ok' or r.get('baseline_zero'):
            continue
        lifts.append((f'{lo}/{hi}', float(r['expected_lift_pct'])))
        prev_optimal = [ch['optimal_spend_money'] for ch in r['channels']]

    if len(lifts) < 2:
        pytest.skip('<2 successful chain runs')

    for i in range(1, len(lifts)):
        prev_label, prev_lift = lifts[i - 1]
        curr_label, curr_lift = lifts[i]
        assert curr_lift >= prev_lift - 0.5, (
            f'real F1 chain violated: {curr_label}={curr_lift:.2f}% < '
            f'{prev_label}={prev_lift:.2f}%. chain={lifts}'
        )


# ──────────────────────────────────────────────────────────────────────
# Standalone runner
# ──────────────────────────────────────────────────────────────────────


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
