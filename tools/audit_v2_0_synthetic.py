"""Phase 2.0 - Forecast Horizon Math Audit (synthetic harness, Part 1).

Standalone numerical comparison of Option A vs Option B vs analytical ground truth
for the forecast_periods × forecast_budget matrix. Does NOT train Aurora MMM -
uses known synthetic params directly. Closes L1 (adstock kernel decision),
L2 (stationarity cap), L3 (seasonality) decisions in MATH_AUDIT_v2_0_FORECAST_HORIZON.md.

L4 (epistemic γ calibration) and L5 (hierarchical interaction) require real MMM
training and are deferred to Phase 2.0 Part 2.

Usage:
    cd D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica
    python tools/audit_v2_0_synthetic.py

Output: prints results tables; writes JSON snapshot to docs/audit_v2_0_synthetic_results.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

# Make sidecar importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'sidecar' / 'econometrica'))

from utils.adstock import apply_adstock  # noqa: E402
from utils.saturation import hill_function  # noqa: E402


# ─── Synthetic ground-truth params (known, не learned) ─────────────────
# 4 channels matching Kagocel-scale reality:
#   TV: slow decay (brand), high volume
#   OLV: medium decay (mixed)
#   Search: fast decay (performance), small spend
#   Programmatic: fast decay (performance), medium spend
TRUE_PARAMS = {
    'TV':           {'decay': 0.85, 'alpha': 2.5, 'gamma': 0.6, 'beta': 0.08, 'unit_cost': 1.0},
    'OLV':          {'decay': 0.65, 'alpha': 2.0, 'gamma': 0.5, 'beta': 0.06, 'unit_cost': 1.0},
    'Search':       {'decay': 0.30, 'alpha': 1.8, 'gamma': 0.4, 'beta': 0.05, 'unit_cost': 1.0},
    'Programmatic': {'decay': 0.40, 'alpha': 2.2, 'gamma': 0.55, 'beta': 0.04, 'unit_cost': 1.0},
}

# Training characterization (frozen - these would normally come from MMM fit)
TRAIN_N = 156  # 3-year weekly training horizon
Y_STD = 100.0  # KPI scale

# Compute mean_train per channel ASSUMING training data was at "training average spend"
# applied with full geometric adstock for TRAIN_N periods.
# In reality MMM learns mean_train from actual training series; here we approximate
# from steady-state assumption (sufficient for L1 decision since both A and B use this same mean).
TRAIN_AVG_SPEND_PER_PERIOD = {
    'TV':           1000.0,
    'OLV':           500.0,
    'Search':        200.0,
    'Programmatic':  300.0,
}


def _flat_alloc_adstock_avg(raw_per_period: float, n_periods: int, decay: float) -> float:
    """Replicate optimizer.py _flat_alloc_adstock_avg semantics for geometric adstock."""
    if n_periods < 1 or raw_per_period <= 0:
        return float(raw_per_period)
    flat = np.full(n_periods, float(raw_per_period))
    adstocked = apply_adstock(flat, 'geometric', {'alpha': float(decay)})
    return float(adstocked.mean())


def compute_train_means() -> dict[str, float]:
    """Compute per-channel mean_train (kernel length = TRAIN_N)."""
    means = {}
    for col, p in TRUE_PARAMS.items():
        x_avg = TRAIN_AVG_SPEND_PER_PERIOD[col]
        means[col] = _flat_alloc_adstock_avg(x_avg, TRAIN_N, p['decay'])
    return means


# ─── Three KPI computers ────────────────────────────────────────────────


def kpi_option_a(allocation_money: dict[str, float], forecast_n: int, mean_train: dict) -> float:
    """Option A - kernel length frozen at TRAIN_N.

    `_flat_alloc_adstock_avg(x_avg, TRAIN_N, decay)` → matches training calibration.
    Aggregation × forecast_n.
    """
    total = 0.0
    for col, p in TRUE_PARAMS.items():
        x_native_total = allocation_money[col] / p['unit_cost']
        x_avg_raw = x_native_total / forecast_n
        x_avg_adstock = _flat_alloc_adstock_avg(x_avg_raw, TRAIN_N, p['decay'])  # ← TRAIN_N
        x_norm = x_avg_adstock / max(mean_train[col], 1e-10)
        sat = hill_function(np.array([max(x_norm, 0)]), alpha=p['alpha'], gamma=p['gamma'])
        total += p['beta'] * sat[0] * forecast_n * Y_STD
    return total


def kpi_option_b(allocation_money: dict[str, float], forecast_n: int, mean_train: dict) -> float:
    """Option B - kernel length recomputed for forecast_n.

    `_flat_alloc_adstock_avg(x_avg, forecast_n, decay)` → matches planning horizon.
    Aggregation × forecast_n.
    """
    total = 0.0
    for col, p in TRUE_PARAMS.items():
        x_native_total = allocation_money[col] / p['unit_cost']
        x_avg_raw = x_native_total / forecast_n
        x_avg_adstock = _flat_alloc_adstock_avg(x_avg_raw, forecast_n, p['decay'])  # ← forecast_n
        x_norm = x_avg_adstock / max(mean_train[col], 1e-10)
        sat = hill_function(np.array([max(x_norm, 0)]), alpha=p['alpha'], gamma=p['gamma'])
        total += p['beta'] * sat[0] * forecast_n * Y_STD
    return total


def kpi_ground_truth(allocation_money: dict[str, float], forecast_n: int, mean_train: dict) -> float:
    """Analytical ground truth: simulate full per-period flat allocation, sum response.

    No flat-mean approximation - actually applies geometric adstock to flat series of
    forecast_n periods, computes Hill(adstock_t / mean_train) per period, sums × β.
    This is what optimizer SHOULD predict if simulation is perfect.
    """
    total = 0.0
    for col, p in TRUE_PARAMS.items():
        x_native_total = allocation_money[col] / p['unit_cost']
        x_avg_raw = x_native_total / forecast_n
        flat_series = np.full(forecast_n, x_avg_raw)
        adstock_series = apply_adstock(flat_series, 'geometric', {'alpha': p['decay']})
        x_norm_series = adstock_series / max(mean_train[col], 1e-10)
        sat_series = hill_function(x_norm_series, alpha=p['alpha'], gamma=p['gamma'])
        total += p['beta'] * sat_series.sum() * Y_STD  # sum (не mean × n) = exact aggregation
    return total


# ─── Test matrix runner ────────────────────────────────────────────────


def make_uniform_allocation(total_money: float, n_channels: int = 4) -> dict[str, float]:
    """Equal split across channels (simple baseline)."""
    per = total_money / n_channels
    return {col: per for col in TRUE_PARAMS}


def make_proportional_allocation(total_money: float, base: dict[str, float]) -> dict[str, float]:
    """Scale base allocation to total_money preserving proportions."""
    base_sum = sum(base.values())
    return {col: total_money * v / base_sum for col, v in base.items()}


def run_l1_kernel_audit() -> list[dict]:
    """Run 5×5 forecast_n × budget matrix. Compare Option A / B / ground truth."""
    mean_train = compute_train_means()

    # Baseline training allocation = TRAIN_AVG × TRAIN_N per channel
    base_alloc = {col: TRAIN_AVG_SPEND_PER_PERIOD[col] * TRAIN_N for col in TRUE_PARAMS}
    train_total_money = sum(base_alloc.values())

    forecast_n_grid = [26, 52, 104, 156, 312]
    budget_mult_grid = [0.5, 1.0, 1.5, 3.0, 5.0]

    results = []
    for fn in forecast_n_grid:
        for mult in budget_mult_grid:
            # Budget scaled per-period to forecast_n, preserving training proportions
            forecast_total = train_total_money * (fn / TRAIN_N) * mult
            alloc = make_proportional_allocation(forecast_total, base_alloc)

            kpi_a = kpi_option_a(alloc, fn, mean_train)
            kpi_b = kpi_option_b(alloc, fn, mean_train)
            kpi_gt = kpi_ground_truth(alloc, fn, mean_train)

            err_a = abs(kpi_a - kpi_gt) / max(abs(kpi_gt), 1e-9) * 100
            err_b = abs(kpi_b - kpi_gt) / max(abs(kpi_gt), 1e-9) * 100

            results.append({
                'forecast_n': fn,
                'budget_mult': mult,
                'kpi_a': round(kpi_a, 2),
                'kpi_b': round(kpi_b, 2),
                'kpi_gt': round(kpi_gt, 2),
                'err_a_pct': round(err_a, 3),
                'err_b_pct': round(err_b, 3),
            })
    return results


def print_l1_table(results: list[dict]) -> None:
    print("\n=== §8.1 L1 Adstock kernel audit (5×5 matrix) ===\n")
    print(f"{'fn':>5} {'budget×':>8} {'kpi_A':>10} {'kpi_B':>10} {'kpi_gt':>10} {'err_A%':>9} {'err_B%':>9}")
    print("-" * 70)
    for r in results:
        print(
            f"{r['forecast_n']:>5} {r['budget_mult']:>8.2f} "
            f"{r['kpi_a']:>10.2f} {r['kpi_b']:>10.2f} {r['kpi_gt']:>10.2f} "
            f"{r['err_a_pct']:>9.3f} {r['err_b_pct']:>9.3f}"
        )

    err_a_arr = np.array([r['err_a_pct'] for r in results])
    err_b_arr = np.array([r['err_b_pct'] for r in results])
    print(f"\nOption A:  median {np.median(err_a_arr):.3f}%  max {err_a_arr.max():.3f}%  p90 {np.percentile(err_a_arr, 90):.3f}%")
    print(f"Option B:  median {np.median(err_b_arr):.3f}%  max {err_b_arr.max():.3f}%  p90 {np.percentile(err_b_arr, 90):.3f}%")


# ─── L2: stationarity cap sensitivity ───────────────────────────────────


def run_l2_cap_sensitivity() -> list[dict]:
    """Test 1.5×, 2×, 3×, 5× caps. Measure Option-A error at boundary cases."""
    mean_train = compute_train_means()
    base_alloc = {col: TRAIN_AVG_SPEND_PER_PERIOD[col] * TRAIN_N for col in TRUE_PARAMS}
    train_total_money = sum(base_alloc.values())

    multipliers = [1.0, 1.5, 2.0, 3.0, 5.0]
    out = []
    for mult in multipliers:
        fn = int(TRAIN_N * mult)
        # Hold per-period budget at training average (1×)
        forecast_total = train_total_money * mult
        alloc = make_proportional_allocation(forecast_total, base_alloc)
        kpi_a = kpi_option_a(alloc, fn, mean_train)
        kpi_gt = kpi_ground_truth(alloc, fn, mean_train)
        err = abs(kpi_a - kpi_gt) / max(abs(kpi_gt), 1e-9) * 100
        out.append({
            'horizon_mult': mult,
            'forecast_n': fn,
            'err_pct': round(err, 3),
        })
    return out


def print_l2_table(results: list[dict]) -> None:
    print("\n=== §8.2 L2 Stationarity cap sensitivity (Option A error at horizon multipliers) ===\n")
    print(f"{'horizon×':>9} {'fn':>5} {'err_pct':>10}")
    print("-" * 30)
    for r in results:
        print(f"{r['horizon_mult']:>9.1f} {r['forecast_n']:>5} {r['err_pct']:>10.3f}")


# ─── L3: seasonality bias ──────────────────────────────────────────────


def run_l3_seasonality_audit(seasonality_amplitude: float = 0.3) -> list[dict]:
    """Compare flat-allocation KPI prediction vs seasonal-realized KPI.

    Realistic data has seasonality (e.g., FMCG Q4 spike). Forecast at uniform
    per-period budget assumes no seasonality. If actual realized period has Q4
    spike, KPI realizes higher; Q3 trough realizes lower. Measure divergence
    при start_pos ∈ {Q1, Q2, Q3, Q4}.
    """
    mean_train = compute_train_means()
    forecast_n = 12  # one quarter (3 months × 4 weeks)
    base_alloc = {col: TRAIN_AVG_SPEND_PER_PERIOD[col] * TRAIN_N for col in TRUE_PARAMS}
    train_total = sum(base_alloc.values())
    forecast_total = train_total * (forecast_n / TRAIN_N)
    alloc = make_proportional_allocation(forecast_total, base_alloc)

    kpi_uniform = kpi_ground_truth(alloc, forecast_n, mean_train)

    out = []
    for start_pos_label, start_t in [('Q1', 0), ('Q2', 13), ('Q3', 26), ('Q4', 39)]:
        # Realized KPI: per-period spend has seasonal multiplier
        # period_t multiplier = 1 + amp × sin(2π × (start_t + t) / 52)
        kpi_realized = 0.0
        for col, p in TRUE_PARAMS.items():
            x_native_total = alloc[col] / p['unit_cost']
            x_avg_raw = x_native_total / forecast_n
            seasonal_series = np.array([
                x_avg_raw * (1 + seasonality_amplitude * np.sin(2 * np.pi * (start_t + t) / 52))
                for t in range(forecast_n)
            ])
            adstock_series = apply_adstock(seasonal_series, 'geometric', {'alpha': p['decay']})
            x_norm_series = adstock_series / max(mean_train[col], 1e-10)
            sat_series = hill_function(x_norm_series, alpha=p['alpha'], gamma=p['gamma'])
            kpi_realized += p['beta'] * sat_series.sum() * Y_STD

        divergence = abs(kpi_realized - kpi_uniform) / max(abs(kpi_uniform), 1e-9) * 100
        out.append({
            'start': start_pos_label,
            'start_t': start_t,
            'kpi_uniform': round(kpi_uniform, 2),
            'kpi_realized': round(kpi_realized, 2),
            'divergence_pct': round(divergence, 3),
        })
    return out


def print_l3_table(results: list[dict]) -> None:
    print("\n=== §8.3 L3 Seasonality bias (12-period forecast at 4 start positions) ===\n")
    print(f"{'start':>6} {'kpi_uniform':>12} {'kpi_realized':>13} {'divergence%':>13}")
    print("-" * 50)
    for r in results:
        print(f"{r['start']:>6} {r['kpi_uniform']:>12.2f} {r['kpi_realized']:>13.2f} {r['divergence_pct']:>13.3f}")
    max_div = max(r['divergence_pct'] for r in results)
    print(f"\nMax divergence: {max_div:.3f}%")
    if max_div < 5:
        verdict = "ship Phase 2 без auto-correction (warning-only)"
    elif max_div < 15:
        verdict = "ship warning + suggest «оптимальный старт»"
    else:
        verdict = "blocking gate: require user confirm + auto-corrected baseline"
    print(f"L3 verdict: {verdict}")


# ─── Main ──────────────────────────────────────────────────────────────


def main():
    print("=" * 72)
    print("Phase 2.0 - Forecast Horizon Math Audit (Part 1: L1 + L2 + L3)")
    print("Standalone analytical comparison; L4 (gamma) + L5 (hierarchical) deferred")
    print("=" * 72)

    l1 = run_l1_kernel_audit()
    print_l1_table(l1)

    l2 = run_l2_cap_sensitivity()
    print_l2_table(l2)

    l3 = run_l3_seasonality_audit()
    print_l3_table(l3)

    snapshot = {
        'l1_kernel_matrix': l1,
        'l2_cap_sensitivity': l2,
        'l3_seasonality': l3,
        'true_params': TRUE_PARAMS,
        'train_n': TRAIN_N,
        'mean_train': compute_train_means(),
    }
    out_path = ROOT / 'docs' / 'audit_v2_0_synthetic_results.json'
    out_path.write_text(json.dumps(snapshot, indent=2, default=float), encoding='utf-8')
    print(f"\nResults snapshot → {out_path}")


if __name__ == '__main__':
    main()
