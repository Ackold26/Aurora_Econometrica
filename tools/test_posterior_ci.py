"""
Posterior CI propagation tests (Phase 1.9).

End-to-end coverage for posterior_propagation utility + integration with
optimizer/decomposer/scenario engines + verdict tier classification.

Run:
    cd sidecar && python ../tools/test_posterior_ci.py
or from repo root:
    python tools/test_posterior_ci.py

Exit code 0 on success, 1 on any failure. Plain stdlib + numpy — no pytest.
"""
from __future__ import annotations

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

from utils.posterior_propagation import (
    compute_ci_hdi,
    tail_ess_threshold,
    load_posterior_samples,
    verdict_tier,
    per_channel_samples,
    channel_index,
    DEFAULT_HDI_PROB,
)
from utils.saturation import (
    hill_function,
    hill_function_batch,
    hill_function_batch_2d,
    hill_derivative_batch,
    marginal_roi,
)
from utils.adstock import (
    apply_adstock,
    geometric_adstock,
    geometric_adstock_batch,
    adstock_factor_batch,
)
from engines.optimizer import _compute_mroas_money, _compute_mroas_money_samples
from engines.narrative_adapter import _merge_channels


PASSED = 0
FAILED = 0


def check(label: str, cond: bool, detail: str = ""):
    global PASSED, FAILED
    mark = "[OK]  " if cond else "[FAIL]"
    if cond:
        PASSED += 1
    else:
        FAILED += 1
    extra = f" — {detail}" if detail else ""
    print(f"{mark} {label}{extra}")


# ────────────────────────────────────────────────────────────────────
# 1. compute_ci_hdi — HDI computation correctness
# ────────────────────────────────────────────────────────────────────

print("\n── compute_ci_hdi ──")
np.random.seed(42)

# Normal posterior — HDI ≈ 1.645 sigmas each side at 90%
samples_normal = np.random.normal(2.0, 0.5, size=8000)
mean_n, low_n, high_n = compute_ci_hdi(samples_normal)
expected_width_normal = 2 * 1.645 * 0.5  # ~1.645
check(
    "HDI normal mean ≈ 2.0",
    abs(mean_n - 2.0) < 0.05,
    f"got {mean_n:.3f}",
)
check(
    "HDI normal width ≈ 1.645 (90% CI)",
    abs((high_n - low_n) - expected_width_normal) < 0.1,
    f"got width={high_n - low_n:.3f}",
)

# Lognormal (skewed — typical mROAS shape)
samples_skew = np.random.lognormal(mean=0.5, sigma=0.5, size=8000)
mean_s, low_s, high_s = compute_ci_hdi(samples_skew)
check(
    "HDI lognormal: low < mean < high",
    low_s < mean_s < high_s,
    f"low={low_s:.3f} mean={mean_s:.3f} high={high_s:.3f}",
)
# HDI on right-skewed distribution should be tighter on left vs equal-tail percentile
check("HDI lognormal: low > 0 (positive support)", low_s > 0)

# Degenerate cases
check("HDI empty array → (0,0,0)", compute_ci_hdi(np.array([])) == (0.0, 0.0, 0.0))
check("HDI scalar → (x,x,x)", compute_ci_hdi(np.array([1.5])) == (1.5, 1.5, 1.5))

# All-NaN
check(
    "HDI all-NaN → (0,0,0)",
    compute_ci_hdi(np.full(100, np.nan)) == (0.0, 0.0, 0.0),
)

# 80% HDI tighter than 90% HDI on same data
mean80, low80, high80 = compute_ci_hdi(samples_normal, hdi_prob=0.8)
check(
    "HDI 80% tighter than 90%",
    (high80 - low80) < (high_n - low_n),
    f"80%={high80-low80:.3f} 90%={high_n-low_n:.3f}",
)

# DEFAULT_HDI_PROB matches industry standard 90%
check("DEFAULT_HDI_PROB == 0.9", DEFAULT_HDI_PROB == 0.9)


# ────────────────────────────────────────────────────────────────────
# 2. verdict_tier — 3-tier + conditional gates
# ────────────────────────────────────────────────────────────────────

print("\n── verdict_tier ──")

# Standard tiers (no gates)
label, tone, _ = verdict_tier(2.0, 1.8, 2.2)  # rw=0.2
check("Tier good: narrow CI", label == "Уверенная" and tone == "good")

label, tone, _ = verdict_tier(2.0, 1.5, 2.6)  # rw=0.55
check("Tier warn: medium CI", label == "Направленная" and tone == "warn")

label, tone, _ = verdict_tier(2.0, 0.5, 4.0)  # rw=1.75
check("Tier bad: wide CI", label == "Высокая неопределённость" and tone == "bad")

# Conditional gate: small N + narrow CI → forced warn
label, tone, _ = verdict_tier(2.0, 1.8, 2.2, n_obs=20)
check("Small-N gate: forced warn on narrow CI", label == "Направленная")

# n=29 still triggers small-N gate (boundary at 30)
label, tone, _ = verdict_tier(2.0, 1.8, 2.2, n_obs=29)
check("Small-N gate boundary: n=29 triggers", label == "Направленная")

# n=30 just clears (no gate)
label, tone, _ = verdict_tier(2.0, 1.8, 2.2, n_obs=30)
check("Small-N gate clear: n=30 → good", label == "Уверенная")

# r_hat hard gate (overrides everything)
label, tone, _ = verdict_tier(2.0, 1.8, 2.2, r_hat=1.06)
check("R-hat gate: forced bad on non-converged", label == "Высокая неопределённость")

# Degenerate: mean=0
label, tone, _ = verdict_tier(0.0, -0.1, 0.1)
check("Degenerate mean=0 → bad", label == "Высокая неопределённость")

# Degenerate: missing inputs
label, tone, _ = verdict_tier(None, None, None)
check("Degenerate None → bad", label == "Высокая неопределённость")


# ────────────────────────────────────────────────────────────────────
# 3. tail_ess_threshold — Vehtari rule
# ────────────────────────────────────────────────────────────────────

print("\n── tail_ess_threshold ──")
check("Tail-ESS threshold 4 chains = 400", tail_ess_threshold(4) == 400)
check("Tail-ESS threshold 2 chains = 200", tail_ess_threshold(2) == 200)
check("Tail-ESS threshold 0 → 100 (minimum 1 chain)", tail_ess_threshold(0) == 100)


# ────────────────────────────────────────────────────────────────────
# 4. load_posterior_samples — backward compat
# ────────────────────────────────────────────────────────────────────

print("\n── load_posterior_samples ──")
check("v1.0/v1.1 pickle (no key) → None", load_posterior_samples({}) is None)
check(
    "Empty posterior_samples dict → None (corrupted)",
    load_posterior_samples({"posterior_samples": {}}) is None,
)
check(
    "Missing required key → None",
    load_posterior_samples({"posterior_samples": {"alphas": []}}) is None,
)
valid = {
    "posterior_samples": {
        "media_betas": np.zeros((2, 8000), dtype=np.float32),
        "alphas": np.ones((2, 8000), dtype=np.float32),
        "gammas": np.ones((2, 8000), dtype=np.float32) * 0.5,
        "intercept": np.zeros(8000, dtype=np.float32),
        "control_betas": np.zeros((0, 8000), dtype=np.float32),
        "media_columns": ["TV", "Digital"],
    }
}
loaded = load_posterior_samples(valid)
check("Valid v1.1.5 pickle → loaded dict", loaded is not None)


# ────────────────────────────────────────────────────────────────────
# 5. per_channel_samples — joint correlation preservation (fix Hidden Problem H1)
# ────────────────────────────────────────────────────────────────────

print("\n── per_channel_samples ──")
samples_dict = valid["posterior_samples"]
ch_tv = per_channel_samples(samples_dict, "TV")
check("per_channel found TV", ch_tv is not None)
# M1 fix (2026-04-26): 'decay' key always present (None when missing) for API ergonomics
check("per_channel keys include alpha/gamma/beta/decay", set(ch_tv.keys()) == {"alpha", "gamma", "beta", "decay"})
check("per_channel arrays shape (8000,)", ch_tv["alpha"].shape == (8000,))
check("per_channel α index 0 (TV)", float(ch_tv["alpha"][0]) == 1.0)
check("per_channel decay None (no adstock_decay в samples)", ch_tv["decay"] is None)

ch_unknown = per_channel_samples(samples_dict, "NotFound")
check("per_channel unknown channel → None", ch_unknown is None)


# ────────────────────────────────────────────────────────────────────
# 6. hill_function_batch — vectorization correctness
# ────────────────────────────────────────────────────────────────────

print("\n── hill_function_batch ──")
# Single sample → matches scalar
sat_scalar = hill_function(np.array([0.5, 1.0, 2.0]), 1.5, 0.8)
sat_batch = hill_function_batch(
    np.array([0.5, 1.0, 2.0]), np.array([1.5]), np.array([0.8])
)
check("hill batch shape (1, 3)", sat_batch.shape == (1, 3))
check("hill batch[0] == scalar", np.allclose(sat_scalar, sat_batch[0]))

# 8000 samples × 36 periods (Kagocel scale)
alpha_8k = np.random.gamma(5, 1 / 3, size=8000)
gamma_8k = np.random.beta(3, 3, size=8000)
x_36 = np.random.uniform(0, 5, size=36)
sat_full = hill_function_batch(x_36, alpha_8k, gamma_8k)
check("hill batch shape (8000, 36)", sat_full.shape == (8000, 36))
check("hill batch values [0, 1]", np.all((sat_full >= 0) & (sat_full <= 1)))

# Derivative batch — non-negative
deriv = hill_derivative_batch(x_36, alpha_8k, gamma_8k)
check("hill_derivative_batch shape (8000, 36)", deriv.shape == (8000, 36))
check("hill_derivative_batch ≥ 0", np.all(deriv >= 0))


# ────────────────────────────────────────────────────────────────────
# 7. _compute_mroas_money_samples — scalar/batch parity
# ────────────────────────────────────────────────────────────────────

print("\n── _compute_mroas_money_samples ──")

scalar = _compute_mroas_money(
    current_spend_native=1000, n_periods=10, mean=100,
    alpha=1.5, gamma=0.8, beta=100, adstock_type="noop",
    y_std=1000, unit_cost=5,
)
batch = _compute_mroas_money_samples(
    current_spend_native=1000, n_periods=10, mean=100,
    alpha_samples=np.array([1.5]), gamma_samples=np.array([0.8]),
    beta_samples=np.array([100.0]),
    adstock_type="noop", y_std=1000, unit_cost=5,
)
check("mROAS scalar/batch parity", abs(scalar - float(batch[0])) < 1e-6)

# 8000 samples
alpha_8k = np.random.gamma(5, 1 / 3, size=8000)
gamma_8k = np.random.beta(3, 3, size=8000)
beta_8k = np.random.normal(100, 20, size=8000)
batch_8k = _compute_mroas_money_samples(
    current_spend_native=1000, n_periods=10, mean=100,
    alpha_samples=alpha_8k, gamma_samples=gamma_8k, beta_samples=beta_8k,
    adstock_type="noop", y_std=1000, unit_cost=5,
)
check("mROAS samples shape (8000,)", batch_8k.shape == (8000,))

# Zero spend → all zeros
zero_spend = _compute_mroas_money_samples(
    current_spend_native=0, n_periods=10, mean=100,
    alpha_samples=alpha_8k, gamma_samples=gamma_8k, beta_samples=beta_8k,
    adstock_type="noop", y_std=1000, unit_cost=5,
)
check("mROAS zero spend → zeros", np.all(zero_spend == 0))

# Compute CI from samples
m_mean, m_low, m_high = compute_ci_hdi(batch_8k)
check("mROAS CI ordering: low < mean < high", m_low < m_mean < m_high)


# ────────────────────────────────────────────────────────────────────
# 8. _merge_channels CI preservation (T11)
# ────────────────────────────────────────────────────────────────────

print("\n── _merge_channels CI preservation ──")
decomp = [{
    "name": "TV", "spend": 1000, "contribution": 500, "roi": 0.5,
    "roi_ci_low": 0.3, "roi_ci_high": 0.8,
    "contribution_ci_low": 300, "contribution_ci_high": 800,
}]
opt = [{
    "name": "TV", "mroi_current": 0.45,
    "mroi_current_ci_low": 0.25, "mroi_current_ci_high": 0.7,
    "mroi_optimal_ci_low": 0.3, "mroi_optimal_ci_high": 0.85,
}]
merged = _merge_channels(decomp, opt)
check("Merged: roi_ci_low preserved", merged[0].get("roi_ci_low") == 0.3)
check("Merged: roi_ci_high preserved", merged[0].get("roi_ci_high") == 0.8)
check("Merged: mroas_ci_low aliased from mroi_current_ci_low", merged[0].get("mroas_ci_low") == 0.25)
check("Merged: mroas_optimal_ci_low aliased", merged[0].get("mroas_optimal_ci_low") == 0.3)

# Backward compat: no CI in input → no CI in output
decomp2 = [{"name": "TV", "spend": 1000, "contribution": 500, "roi": 0.5}]
opt2 = [{"name": "TV", "mroi_current": 0.45}]
merged2 = _merge_channels(decomp2, opt2)
check("Merged backward compat: no CI input → no CI output", "roi_ci_low" not in merged2[0])
check("Merged backward compat: no mroas CI", "mroas_ci_low" not in merged2[0])


# ────────────────────────────────────────────────────────────────────
# 9. Phase 1.1 — geometric_adstock_batch + adstock_factor_batch
# ────────────────────────────────────────────────────────────────────

print("\n── Phase 1.1: geometric_adstock_batch ──")

# Single-sample matches scalar
raw = np.array([1.0, 2.0, 1.5, 0.5, 3.0])
batch_single = geometric_adstock_batch(raw, np.array([0.5]))
scalar = geometric_adstock(raw, alpha=0.5)
check("geometric_adstock_batch shape (1, n)", batch_single.shape == (1, 5))
check("geometric_adstock_batch[0] == scalar(0.5)", np.allclose(batch_single[0], scalar))

# Multiple decays — first sample 0.0 (no carryover) = raw, second 0.9 (long decay) = ramping
batch_multi = geometric_adstock_batch(raw, np.array([0.0, 0.9]))
check("Adstock decay=0 returns raw", np.allclose(batch_multi[0], raw))
check("Adstock decay=0.9 increases monotonically (long carryover)", batch_multi[1, -1] > batch_multi[1, 0])
check("Adstock decay=0.9 > decay=0 at each step except first", np.all(batch_multi[1, 1:] >= batch_multi[0, 1:]))

# 8000 samples × 36 periods (Kagocel-scale)
decays_8k = np.random.uniform(0.05, 0.6, size=8000)
raw_36 = np.random.exponential(2.0, size=36)
batch_full = geometric_adstock_batch(raw_36, decays_8k)
check("Adstock batch shape (8000, 36)", batch_full.shape == (8000, 36))
check("Adstock all finite", np.all(np.isfinite(batch_full)))
check("Adstock non-negative for non-negative input", np.all(batch_full >= 0))

print("\n── Phase 1.1: adstock_factor_batch ──")

# Geometric factor at theta=0.5 для n=10: should match scalar _adstock_factor
from engines.optimizer import _adstock_factor as _af_scalar
factor_batch_05 = adstock_factor_batch(np.array([0.5]), n_periods=10, adstock_type='geometric')
factor_scalar_05 = _af_scalar(1.0, 10, 'geometric', decay=0.5)
check("adstock_factor_batch theta=0.5 matches scalar", abs(factor_batch_05[0] - factor_scalar_05) < 1e-9)

# theta=0 → factor=1.0
check("adstock_factor_batch theta=0 → 1.0", abs(adstock_factor_batch(np.array([0.0]), 10, 'geometric')[0] - 1.0) < 1e-9)

# noop → 1.0
check("adstock_factor_batch noop → 1.0", abs(adstock_factor_batch(np.array([0.5]), 10, 'noop')[0] - 1.0) < 1e-9)

# Vectorized: 8000 samples
factor_8k = adstock_factor_batch(decays_8k, n_periods=36, adstock_type='geometric')
check("adstock_factor_batch shape (8000,)", factor_8k.shape == (8000,))
check("adstock_factor_batch finite", np.all(np.isfinite(factor_8k)))
check("adstock_factor_batch ≥ 1.0 for any decay≥0", np.all(factor_8k >= 1.0 - 1e-9))

print("\n── Phase 1.1: hill_function_batch_2d ──")

# Per-sample x_norm + per-sample alpha/gamma
x_norm_2d = np.random.uniform(0, 5, size=(100, 36))
alphas_100 = np.random.gamma(5, 1/3, size=100)
gammas_100 = np.random.beta(3, 3, size=100)
sat_2d = hill_function_batch_2d(x_norm_2d, alphas_100, gammas_100)
check("hill_function_batch_2d shape (100, 36)", sat_2d.shape == (100, 36))
check("hill_function_batch_2d values [0, 1]", np.all((sat_2d >= 0) & (sat_2d <= 1)))

# Cross-check: batch_2d with constant x_norm row matches batch_1d
x_const = np.array([1.0, 2.0, 3.0])
x_2d_replicated = np.tile(x_const, (10, 1))  # (10, 3) all rows = x_const
alphas_10 = np.full(10, 1.5)
gammas_10 = np.full(10, 0.5)
sat_2d_repl = hill_function_batch_2d(x_2d_replicated, alphas_10, gammas_10)
sat_1d = hill_function_batch(x_const, alphas_10, gammas_10)
check("batch_2d vs batch_1d parity (constant x)", np.allclose(sat_2d_repl, sat_1d))

print("\n── Phase 1.1: per_channel_samples decay support ──")

# v1.2 pickle includes adstock_decay
samples_with_decay = {
    'media_betas': np.zeros((2, 8000), dtype=np.float32),
    'alphas': np.ones((2, 8000), dtype=np.float32),
    'gammas': np.ones((2, 8000), dtype=np.float32) * 0.5,
    'intercept': np.zeros(8000, dtype=np.float32),
    'control_betas': np.zeros((0, 8000), dtype=np.float32),
    'media_columns': ["TV", "Digital"],
    'adstock_decay': np.array([[0.4]*8000, [0.05]*8000], dtype=np.float32),  # (2 ch, 8000)
}
ch_tv = per_channel_samples(samples_with_decay, "TV")
check("per_channel_samples returns 'decay' for v1.2", 'decay' in ch_tv)
check("decay shape (8000,)", ch_tv['decay'].shape == (8000,))
check("decay value matches synthesis", abs(float(ch_tv['decay'][0]) - 0.4) < 1e-6)

# v1.1.5 pickle without adstock_decay — M1 fix: 'decay' key present but None
samples_v1_1_5 = {k: v for k, v in samples_with_decay.items() if k != 'adstock_decay'}
ch_tv_legacy = per_channel_samples(samples_v1_1_5, "TV")
check("per_channel_samples v1.1.5 has 'decay' key set to None", ch_tv_legacy.get('decay') is None)

print("\n── Phase 1.1: _compute_mroas_money_samples with decay_samples ──")

from engines.optimizer import _compute_mroas_money_samples

alpha_s = np.full(1000, 1.5)
gamma_s = np.full(1000, 0.5)
beta_s = np.full(1000, 100.0)
decay_s = np.full(1000, 0.3)

# With decay_samples
mroas_with_decay = _compute_mroas_money_samples(
    current_spend_native=1000, n_periods=10, mean=100,
    alpha_samples=alpha_s, gamma_samples=gamma_s, beta_samples=beta_s,
    adstock_type='geometric', y_std=1000, unit_cost=5,
    decay_samples=decay_s,
)
check("mroas with decay_samples shape (1000,)", mroas_with_decay.shape == (1000,))
check("mroas with constant samples → all values ≈ same", np.std(mroas_with_decay) < 1e-6)

# Without decay_samples (Phase 1.9 fallback uses default 0.5)
mroas_without = _compute_mroas_money_samples(
    current_spend_native=1000, n_periods=10, mean=100,
    alpha_samples=alpha_s, gamma_samples=gamma_s, beta_samples=beta_s,
    adstock_type='geometric', y_std=1000, unit_cost=5,
)
check("mroas without decay (default 0.5) differs from decay=0.3 path",
      not np.isclose(float(mroas_with_decay[0]), float(mroas_without[0]), atol=1e-3))

# Variable decay → mROAS varies per sample
decay_var = np.linspace(0.05, 0.8, 1000)
mroas_var = _compute_mroas_money_samples(
    current_spend_native=1000, n_periods=10, mean=100,
    alpha_samples=alpha_s, gamma_samples=gamma_s, beta_samples=beta_s,
    adstock_type='geometric', y_std=1000, unit_cost=5,
    decay_samples=decay_var,
)
check("Variable decay → mROAS varies", np.std(mroas_var) > 1e-3)

# Higher decay → higher adstock_factor BUT also higher x_norm → may saturate
# Hill differential. Net effect mROAS may go either way. Just check finite + monotonic
# behavior of adstock_factor itself (already in adstock_factor_batch tests above).
af_low = adstock_factor_batch(np.array([0.1]), 10, 'geometric')[0]
af_high = adstock_factor_batch(np.array([0.7]), 10, 'geometric')[0]
check("Higher decay → higher adstock_factor (chain rule input)", af_high > af_low)

# ────────────────────────────────────────────────────────────────────
# Summary
# ────────────────────────────────────────────────────────────────────

print(f"\n{PASSED}/{PASSED + FAILED} assertions passed.")
sys.exit(0 if FAILED == 0 else 1)
