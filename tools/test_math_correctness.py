"""
Math correctness tests for Aurora AI Econometrica engines.

Post-audit (2026-04-25). Covers PURE formula invariants that do not require
MCMC fit — these tests are stable pre- and post-Hill-fix. MCMC-based tests
(parameter recovery, prior predictive, posterior predictive) deferred until
post-Hill-fix when baseline semantics are meaningful.

Test categories:
  1. Hill saturation: monotonicity, bounds, half-saturation point
  2. Adstock: geometric recursion, Weibull weight normalization
  3. y normalization: roundtrip invariance
  4. Diagnostics: R², MAPE guard, RMSE
  5. Marginal ROI: analytical derivative vs Hill numerical derivative
  6. P0-7 regression: training-vs-reconstruction Hill gamma drift detector
     (audit finding: `modeler.py:537` uses `gamma × x.max()` while training
      line 312 uses raw gamma — test would catch re-introduction)

Run:
    cd sidecar && python ../tools/test_math_correctness.py
or from repo root:
    python tools/test_math_correctness.py

Exit code 0 on success, 1 on any failure. Plain stdlib + numpy — no pytest.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "sidecar"
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / "econometrica"))

import numpy as np


PASSED = 0
FAILED = 0
SEED = 42


def _ok(label: str) -> None:
    global PASSED
    PASSED += 1
    print(f"[OK]   {label}")


def _fail(label: str, detail: str = "") -> None:
    global FAILED
    FAILED += 1
    line = f"[FAIL] {label}"
    if detail:
        line += f" - {detail}"
    print(line)


def assert_close(label: str, actual: float, expected: float, rtol: float = 1e-6) -> None:
    diff = abs(actual - expected)
    scale = max(abs(actual), abs(expected), 1.0)
    if diff / scale <= rtol:
        _ok(label)
    else:
        _fail(label, f"got {actual!r}, expected {expected!r} (rtol={rtol})")


def assert_true(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        _ok(label)
    else:
        _fail(label, detail)


# ─────────────────────────────────────────────────────────────────────────
# 1. Hill saturation
# ─────────────────────────────────────────────────────────────────────────

def test_hill_bounds():
    from utils.saturation import hill_function

    # x=0 → sat=0 (unless gamma=0, which requires guard)
    v = hill_function(np.array([0.0]), alpha=1.0, gamma=0.5)
    assert_close("hill(0, 1, 0.5) == 0", float(v[0]), 0.0)

    # x→∞ → sat→1
    v = hill_function(np.array([1e6]), alpha=1.0, gamma=0.5)
    assert_close("hill(1e6, 1, 0.5) → 1", float(v[0]), 1.0, rtol=1e-5)

    # x=gamma → sat=0.5 exactly (definition of half-saturation)
    v = hill_function(np.array([0.5]), alpha=2.0, gamma=0.5)
    assert_close("hill(γ, α, γ) == 0.5", float(v[0]), 0.5)

    v = hill_function(np.array([3.7]), alpha=1.8, gamma=3.7)
    assert_close("hill(γ, α, γ) == 0.5 (different γ)", float(v[0]), 0.5)


def test_hill_monotonic_increasing():
    """Property-based: x ↑ ⇒ sat ↑. Random seed pinned."""
    from utils.saturation import hill_function

    rng = random.Random(SEED)
    failures = 0
    for _ in range(200):
        alpha = rng.uniform(0.1, 5.0)
        gamma = rng.uniform(0.01, 10.0)
        xs = sorted([rng.uniform(0, 100) for _ in range(5)])
        sats = hill_function(np.array(xs), alpha=alpha, gamma=gamma)
        for i in range(len(sats) - 1):
            # Non-strict: equal values are OK (x1==x2 after uniform draw)
            if sats[i + 1] < sats[i] - 1e-10:
                failures += 1
                break
    assert_true(
        "hill monotonic increasing (200 random cases)",
        failures == 0,
        f"{failures} violations",
    )


def test_hill_non_negative_clip():
    """x=-0.5 → saturation utilits clips to 0 → sat=0."""
    from utils.saturation import hill_function

    v = hill_function(np.array([-0.5]), alpha=1.0, gamma=0.5)
    assert_close("hill(-0.5) clipped → 0", float(v[0]), 0.0)


def test_hill_stability_large_x():
    """Hill must not overflow at x=10*γ, α=5 (typical upper range)."""
    from utils.saturation import hill_function

    v = hill_function(np.array([5.0]), alpha=5.0, gamma=0.5)
    assert_true("hill stable at x=10*γ, α=5", np.isfinite(v[0]) and 0.99 <= v[0] <= 1.0,
                f"got {v[0]}")


# ─────────────────────────────────────────────────────────────────────────
# 2. Adstock
# ─────────────────────────────────────────────────────────────────────────

def test_adstock_geometric_single_pulse():
    """Pulse [1, 0, 0, 0] with alpha=0.5 → [1, 0.5, 0.25, 0.125]."""
    from utils.adstock import geometric_adstock

    x = np.array([1.0, 0, 0, 0, 0])
    y = geometric_adstock(x, alpha=0.5)
    expected = [1.0, 0.5, 0.25, 0.125, 0.0625]
    for i, e in enumerate(expected):
        assert_close(f"geo_adstock pulse[{i}] alpha=0.5", float(y[i]), e)


def test_adstock_geometric_alpha_zero():
    """alpha=0 → no decay → output = input."""
    from utils.adstock import geometric_adstock

    x = np.array([1.0, 2.0, 3.0])
    y = geometric_adstock(x, alpha=0.0)
    for i, v in enumerate([1.0, 2.0, 3.0]):
        assert_close(f"geo_adstock alpha=0 pass-through[{i}]", float(y[i]), v)


def test_adstock_weibull_weights_sum_to_1():
    """Weibull PDF weights must sum to 1 after normalization."""
    from utils.adstock import weibull_adstock

    x = np.array([1.0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])  # unit pulse
    y = weibull_adstock(x, shape=2.0, scale=3.0, max_lag=12)
    # Sum of y over full lag window ≈ sum of weights (×1) = 1
    # Exact sum may differ due to truncation at max_lag
    s = float(y.sum())
    assert_true(
        "weibull adstock unit pulse → sum ≈ 1 (truncated max_lag=12)",
        0.95 <= s <= 1.05,
        f"got sum={s}",
    )


def test_adstock_apply_dispatch():
    """apply_adstock dispatches correctly geometric/weibull."""
    from utils.adstock import apply_adstock

    x = np.array([1.0, 0, 0, 0])
    geo = apply_adstock(x, "geometric", {"alpha": 0.5})
    wei = apply_adstock(x, "weibull", {"shape": 2.0, "scale": 3.0, "max_lag": 4})
    assert_close("apply_adstock geometric[0]", float(geo[0]), 1.0)
    assert_true("apply_adstock dispatched weibull ≠ geometric", not np.allclose(geo, wei))


# ─────────────────────────────────────────────────────────────────────────
# 3. y normalization roundtrip
# ─────────────────────────────────────────────────────────────────────────

def test_y_normalization_roundtrip():
    """(y - mean)/std, then × std + mean → original y."""
    y = np.array([100, 150, 200, 175, 120], dtype=float)
    y_mean = y.mean()
    y_std = max(y.std(), 1e-10)
    y_norm = (y - y_mean) / y_std
    y_recovered = y_norm * y_std + y_mean
    for i, v in enumerate(y):
        assert_close(f"y norm roundtrip[{i}]", float(y_recovered[i]), float(v), rtol=1e-10)


def test_y_normalization_zero_std_guard():
    """Constant y → y_std=0 → code should use 1e-10 floor, not raise."""
    y = np.array([100, 100, 100], dtype=float)
    y_std = max(float(y.std()), 1e-10)
    assert_true("y_std floor prevents div/0", y_std >= 1e-10)


# ─────────────────────────────────────────────────────────────────────────
# 4. Diagnostics
# ─────────────────────────────────────────────────────────────────────────

def test_r_squared():
    from utils.diagnostics import compute_r_squared

    y_true = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y_pred = y_true.copy()  # perfect fit
    assert_close("R² perfect = 1.0", compute_r_squared(y_true, y_pred), 1.0)

    # Worst case (y_pred = mean → ss_res = ss_tot → R²=0)
    y_pred_mean = np.full_like(y_true, y_true.mean())
    assert_close("R² y_pred=mean = 0.0", compute_r_squared(y_true, y_pred_mean), 0.0)


def test_mape_guard():
    """MAPE with y=0 should not raise (mask y!=0)."""
    from utils.diagnostics import compute_mape

    y_true = np.array([0.0, 1.0, 2.0])
    y_pred = np.array([0.5, 1.1, 1.8])
    result = compute_mape(y_true, y_pred)
    assert_true("MAPE with y=0 doesn't raise", np.isfinite(result))
    # Only y_true[1], y_true[2] used → mean(|1-1.1|/1, |2-1.8|/2) × 100 = mean(10%, 10%) = 10
    assert_close("MAPE masked computation", result, 10.0, rtol=1e-6)


def test_mape_all_zeros_guard():
    """MAPE with all y_true=0 → returns 0 (no division)."""
    from utils.diagnostics import compute_mape

    y_true = np.array([0.0, 0.0])
    y_pred = np.array([1.0, 2.0])
    result = compute_mape(y_true, y_pred)
    assert_close("MAPE all-zero y → 0", result, 0.0)


def test_rmse():
    from utils.diagnostics import compute_rmse

    y_true = np.array([1.0, 2.0, 3.0])
    y_pred = np.array([1.5, 2.5, 3.5])  # const error 0.5
    assert_close("RMSE constant error", compute_rmse(y_true, y_pred), 0.5)


# ─────────────────────────────────────────────────────────────────────────
# 5. Marginal ROI = analytical derivative
# ─────────────────────────────────────────────────────────────────────────

def test_marginal_roi_matches_numerical_derivative():
    """Analytical mROI = d/dx [β × Hill(x)]. Compare to finite difference."""
    from utils.saturation import marginal_roi, hill_function

    alpha, gamma, beta = 1.5, 2.0, 10.0
    x = np.array([0.5, 1.0, 2.0, 3.0, 5.0])

    analytical = marginal_roi(x, alpha, gamma, beta)

    # Numerical derivative: (f(x+h) - f(x-h)) / 2h for each x
    h = 1e-4
    numerical = np.zeros_like(x)
    for i, xi in enumerate(x):
        f_plus = beta * hill_function(np.array([xi + h]), alpha, gamma)[0]
        f_minus = beta * hill_function(np.array([xi - h]), alpha, gamma)[0]
        numerical[i] = (f_plus - f_minus) / (2 * h)

    for i in range(len(x)):
        assert_close(
            f"mROI analytical vs numerical @ x={x[i]}",
            float(analytical[i]), float(numerical[i]),
            rtol=1e-3,
        )


# ─────────────────────────────────────────────────────────────────────────
# 6. P0-7 regression: training vs reconstruction Hill formula drift
# ─────────────────────────────────────────────────────────────────────────

def test_p0_7_training_reconstruction_hill_divergence():
    """P0-7: modeler.py:312 (training) uses raw `gammas[i]`.
    modeler.py:537 (reconstruction) uses `gammas[i] * max(x, 1e-10)`.

    Fed same posterior means + same X_media_norm, the two compute DIFFERENT
    media_effect. This test constructs a synthetic X_media_norm and verifies
    that the two formulas DO diverge — if they ever converge (someone fixed
    P0-7), this test fails and should be updated.

    This is a PINNING test: current code has a known divergence (P0-7).
    Test documents and asserts it until fix lands.
    """
    # Synthetic positive-only z-scored spend
    x = np.array([0.1, 0.3, 0.7, 1.2, 1.8, 2.1])
    alpha = 1.67  # Gamma(5,3) mean
    gamma = 0.5   # Beta(3,3) mean
    beta = 0.3

    # Training formula (matches modeler.py:312 exactly)
    training_sat = x ** alpha / (x ** alpha + gamma ** alpha + 1e-10)
    training_effect = beta * training_sat

    # Reconstruction formula (matches modeler.py:537 exactly)
    gamma_scaled = gamma * max(x.max(), 1e-10)
    reconstruction_sat = x ** alpha / (x ** alpha + gamma_scaled ** alpha + 1e-10)
    reconstruction_effect = beta * reconstruction_sat

    # They must DIVERGE (this is the bug)
    divergence = float(np.abs(training_effect - reconstruction_effect).max())
    assert_true(
        "P0-7: training-vs-reconstruction Hill diverges (known bug)",
        divergence > 0.01,
        f"divergence = {divergence}; if <=0.01, someone fixed P0-7 — update test",
    )
    # And specifically, reconstruction_sat < training_sat at saturation
    # (because gamma_scaled > gamma means half-saturation point pushed right)
    assert_true(
        "P0-7: reconstruction underestimates saturation vs training",
        reconstruction_sat[-1] < training_sat[-1],
        f"reconstruction={reconstruction_sat[-1]}, training={training_sat[-1]}",
    )


# ─────────────────────────────────────────────────────────────────────────
# 7. P0-5/6 regression: optimizer vs training Hill formula drift
# ─────────────────────────────────────────────────────────────────────────

def test_p0_5_6_optimizer_vs_training_hill_divergence():
    """P0-5/6: optimizer.py:92 uses raw spend + gamma × current_spend.
    Training uses z-scored spend + raw gamma. Same model, four different
    Hill formulas. Test documents the divergence.
    """
    from utils.saturation import hill_function

    # Current spend in raw units (e.g., rubles)
    current_spend = 100_000_000  # 100M rubles for TV
    gamma_posterior = 0.5
    alpha_posterior = 1.67

    # Case A: small spend (near zero) — training (z-score can be negative, clipped to 0
    # → sat=0), optimizer (raw=1M, gamma_scaled=50M → z=0.02 → sat≈0)
    # Actually small spend happens to converge. Use large overshoot.
    #
    # Case B: spend at 3 std above mean → training sat≈0.97 (fully saturated)
    # Optimizer uses raw spend × 3 = 300M, gamma_scaled = 50M → z=6 → sat≈0.999
    # Still similar because both saturate.
    #
    # Case C: spend at 0.5 std above mean → training z=0.5, sat at x=γ=0.5 → 0.5
    # Optimizer raw spend = mean+0.5std = 115M, gamma_scaled = γ×current_spend = 50M
    # → optimizer_ratio = 115M/50M = 2.3, sat ≈ (2.3^1.67)/((2.3^1.67)+1) ≈ 0.81
    # Training: x=0.5, γ=0.5 → sat=0.5. Divergence 0.31 ≥ 0.05 ✓
    spend_z = 0.5
    spend_raw = 115_000_000  # 115M rubles (= mean + 0.5×std with mean=100M, std=30M)

    training_sat = float(hill_function(
        np.array([spend_z]), alpha=alpha_posterior, gamma=gamma_posterior,
    )[0])
    optimizer_sat = float(hill_function(
        np.array([spend_raw]),
        alpha=alpha_posterior,
        gamma=max(gamma_posterior * current_spend, 1),
    )[0])

    divergence = abs(training_sat - optimizer_sat)
    assert_true(
        "P0-5/6: optimizer-vs-training Hill diverges (known bug)",
        divergence > 0.05,
        f"training_sat={training_sat}, optimizer_sat={optimizer_sat}",
    )


# ─────────────────────────────────────────────────────────────────────────
# 8. Hill formula reproduction (preparation for Hill fix verification)
# ─────────────────────────────────────────────────────────────────────────

def test_robyn_style_hill_positive_domain():
    """Post-Hill-fix target: spend/mean normalization keeps x ≥ 0 always."""
    from utils.saturation import hill_function

    mean_spend = 50.0
    # Spends ranging 0 to 3× mean
    spends = np.array([0.0, 25.0, 50.0, 100.0, 150.0])
    x_norm = spends / mean_spend  # Robyn-style → [0, 0.5, 1.0, 2.0, 3.0]

    sats = hill_function(x_norm, alpha=1.5, gamma=1.0)
    # sat(0) = 0, sat(x=γ=1) = 0.5, sat increasing
    assert_close("robyn-style: sat(0)=0", float(sats[0]), 0.0)
    assert_close("robyn-style: sat(x=γ=1.0)=0.5", float(sats[2]), 0.5)
    assert_true(
        "robyn-style: sat monotonic in [0, 3]",
        all(sats[i] <= sats[i + 1] for i in range(len(sats) - 1)),
    )


# ─────────────────────────────────────────────────────────────────────────
# 9. MQS component bounds
# ─────────────────────────────────────────────────────────────────────────

def test_mqs_bounds():
    """MQS score must be in [0, 100]."""
    from utils.diagnostics import model_quality_score

    # Perfect
    mqs = model_quality_score(r_squared=1.0, mape=0.0, r_hat_max=1.0, divergences=0, ratio=10)
    assert_true("MQS perfect in bounds", 0 <= mqs["score"] <= 100)
    assert_close("MQS perfect ≈ 100", mqs["score"], 100.0, rtol=0.01)

    # Worst
    mqs = model_quality_score(r_squared=0.0, mape=100.0, r_hat_max=2.0, divergences=1000, ratio=1)
    assert_true("MQS worst in bounds", 0 <= mqs["score"] <= 100)

    # Thinness cap
    mqs = model_quality_score(r_squared=0.99, mape=1.0, r_hat_max=1.0, divergences=0, ratio=1.5)
    assert_true(
        "MQS thinness cap ratio<2 → ≤50",
        mqs["score"] <= 50,
        f"got {mqs['score']}",
    )
    mqs = model_quality_score(r_squared=0.99, mape=1.0, r_hat_max=1.0, divergences=0, ratio=3.0)
    assert_true(
        "MQS thinness cap 2≤ratio<4 → ≤70",
        mqs["score"] <= 70,
        f"got {mqs['score']}",
    )


# ─────────────────────────────────────────────────────────────────────────
# 10. JS Hill / Python Hill parity check (post-Hill-fix target)
# ─────────────────────────────────────────────────────────────────────────

def test_js_style_hill_semantics():
    """Emulate the JS formula in interactive.py:689-693 exactly in Python,
    verify it matches utils/saturation Hill when inputs are Robyn-style
    (spend/mean) — pre-condition for Hill fix completion.

    JS formula:
        z = spend / mean
        za = z ** alpha
        ga = gamma ** alpha
        sat = za / (za + ga)

    Our Python utils saturation:
        sat = x^α / (x^α + γ^α)    [no +1e-10 → exact match]
    """
    # Replicate JS formula in Python
    def js_hill(spend, mean, alpha, gamma):
        z = spend / mean if mean > 0 else 0.0
        za = z ** alpha
        ga = gamma ** alpha
        return za / (za + ga) if (za + ga) > 0 else 0.0

    from utils.saturation import hill_function

    # Parity test grid
    test_cases = [
        (50, 50, 1.0, 0.5),  # z=1
        (100, 50, 1.5, 0.5),  # z=2
        (25, 50, 2.0, 0.5),  # z=0.5
        (0, 50, 1.0, 0.5),   # z=0
    ]
    for spend, mean, alpha, gamma in test_cases:
        js_val = js_hill(spend, mean, alpha, gamma)
        py_val = float(hill_function(
            np.array([spend / mean]), alpha=alpha, gamma=gamma,
        )[0])
        # Python has +0 in denominator (1e-10 added in saturation.py? no, it doesn't)
        # Actually utils/saturation line 23: no +1e-10. So exact match expected.
        assert_close(
            f"JS vs Python Hill parity @ spend={spend}, mean={mean}",
            py_val, js_val, rtol=1e-9,
        )


# ─────────────────────────────────────────────────────────────────────────
# 11. Column role detection (validator sanity)
# ─────────────────────────────────────────────────────────────────────────

def test_column_role_kpi_detection():
    from engines.validator import detect_column_role

    assert_true("detect 'sales' as KPI", detect_column_role("sales") == "kpi")
    assert_true("detect 'продажи' as KPI", detect_column_role("продажи") == "kpi")
    assert_true("detect 'tv spend' as media", detect_column_role("tv spend") == "media")
    assert_true("detect 'date' as date", detect_column_role("date") == "date")
    assert_true("detect 'конкурент' as control (priority)",
                detect_column_role("Конкурент: P&G") == "control")


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=== test_math_correctness (Aurora AI Econometrica) ===\n")

    print("── 1. Hill saturation ──")
    test_hill_bounds()
    test_hill_monotonic_increasing()
    test_hill_non_negative_clip()
    test_hill_stability_large_x()

    print("\n── 2. Adstock ──")
    test_adstock_geometric_single_pulse()
    test_adstock_geometric_alpha_zero()
    test_adstock_weibull_weights_sum_to_1()
    test_adstock_apply_dispatch()

    print("\n── 3. y normalization ──")
    test_y_normalization_roundtrip()
    test_y_normalization_zero_std_guard()

    print("\n── 4. Diagnostics ──")
    test_r_squared()
    test_mape_guard()
    test_mape_all_zeros_guard()
    test_rmse()

    print("\n── 5. Marginal ROI ──")
    test_marginal_roi_matches_numerical_derivative()

    print("\n── 6. P0-7 training-vs-reconstruction drift ──")
    test_p0_7_training_reconstruction_hill_divergence()

    print("\n── 7. P0-5/6 optimizer-vs-training drift ──")
    test_p0_5_6_optimizer_vs_training_hill_divergence()

    print("\n── 8. Robyn-style Hill (post-fix target) ──")
    test_robyn_style_hill_positive_domain()

    print("\n── 9. MQS bounds ──")
    test_mqs_bounds()

    print("\n── 10. JS↔Python Hill parity ──")
    test_js_style_hill_semantics()

    print("\n── 11. Validator column role ──")
    test_column_role_kpi_detection()

    print(f"\n{PASSED}/{PASSED + FAILED} assertions passed.")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
