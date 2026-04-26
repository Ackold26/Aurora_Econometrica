"""
Phase 1.1 Pilot — logit-normal vs Beta-Beta hierarchical adstock prior.

Synthetic experiment per ADR §3.A1: compare two parameterizations of
hierarchical adstock decay across 4-7 channels on small-N (n=20-36).

ADR amendment recommended logit-normal default (avoids funnel geometry,
non-centers cleanly). This pilot validates that empirically before
committing 12-15h to Phase 1.1 implementation.

Compare on synthetic data with KNOWN per-channel decay:
- Divergences count
- Sampling time
- Per-channel decay recovery (within posterior 90% HDI)
- ESS / R-hat convergence diagnostics

Run:
    cd D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica
    python tools/pilot_phase11_hierarchy.py [--quick]

Quick mode: chains=2, draws=500, tune=500 (~1-2 min)
Full mode:  chains=4, draws=2000, tune=2000 (~5-10 min)

Outputs:
- stdout summary table
- docs/PHASE_1_1_PILOT_RESULTS.md (auto-written)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "sidecar"
sys.path.insert(0, str(SIDECAR / "econometrica"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def make_synthetic(
    n_obs: int = 36,
    n_channels: int = 5,
    true_decays: list[float] | None = None,
    true_alphas: list[float] | None = None,
    true_gammas: list[float] | None = None,
    true_betas: list[float] | None = None,
    noise_sigma: float = 0.1,
    seed: int = 42,
) -> dict:
    """Generate synthetic monthly MMM dataset with known parameters.

    Channels mix TV-like (long decay 0.4-0.5) with Digital-like (short decay 0.05-0.1)
    to test whether hierarchical pooling can recover bimodal decay structure.
    """
    rng = np.random.default_rng(seed)

    # Defaults: 2 TV-like + 3 Digital-like for n_channels=5
    if true_decays is None:
        if n_channels == 5:
            true_decays = [0.45, 0.40, 0.10, 0.08, 0.05]
        elif n_channels == 7:
            true_decays = [0.50, 0.45, 0.35, 0.10, 0.08, 0.05, 0.05]
        else:
            true_decays = [0.3] * n_channels
    if true_alphas is None:
        true_alphas = [1.5] * n_channels
    if true_gammas is None:
        true_gammas = [0.6] * n_channels
    if true_betas is None:
        true_betas = [0.3] * n_channels

    # Random monthly spend per channel
    raw_spend = rng.exponential(1.0, size=(n_obs, n_channels))

    # Apply per-channel adstock + Hill + sum
    y = np.zeros(n_obs)
    intercept_true = 2.0
    for j in range(n_channels):
        # Geometric adstock with true decay
        adstock = np.zeros(n_obs)
        adstock[0] = raw_spend[0, j]
        for t in range(1, n_obs):
            adstock[t] = raw_spend[t, j] + true_decays[j] * adstock[t - 1]
        # Normalize by mean (Robyn-style)
        mean_j = adstock.mean()
        x_norm = adstock / max(mean_j, 1e-10)
        # Hill
        sat = x_norm ** true_alphas[j] / (
            x_norm ** true_alphas[j] + true_gammas[j] ** true_alphas[j]
        )
        y += true_betas[j] * sat
    y += intercept_true
    y += rng.normal(0, noise_sigma, size=n_obs)

    return {
        "y": y,
        "raw_spend": raw_spend,
        "true_decays": np.array(true_decays),
        "true_alphas": np.array(true_alphas),
        "true_gammas": np.array(true_gammas),
        "true_betas": np.array(true_betas),
        "intercept_true": intercept_true,
        "n_obs": n_obs,
        "n_channels": n_channels,
    }


def fit_pymc_hierarchy(
    data: dict,
    parameterization: str,
    chains: int = 2,
    draws: int = 500,
    tune: int = 500,
    target_accept: float = 0.95,
    seed: int = 42,
) -> dict:
    """Fit Bayesian MMM with hierarchical adstock decay.

    parameterization: "beta_beta" (Beta(μ·κ, (1-μ)·κ)) or "logit_normal"
        (sigmoid(μ + σ·z), z ~ Normal(0,1) non-centered).

    Returns dict with sampling time, divergences, recovered decays, ESS, R-hat.
    """
    import pymc as pm
    import pytensor.tensor as pt
    import arviz as az

    n_obs = data["n_obs"]
    n_channels = data["n_channels"]
    raw_spend = data["raw_spend"]
    y_obs = data["y"]

    t0 = time.time()
    with pm.Model() as model:
        # Hierarchical adstock decay
        if parameterization == "beta_beta":
            mu_decay = pm.Beta("mu_decay", alpha=2.0, beta=5.0)
            kappa_decay = pm.Gamma("kappa_decay", alpha=3.0, beta=1.0)
            decay_alpha = mu_decay * kappa_decay
            decay_beta = (1.0 - mu_decay) * kappa_decay
            decay = pm.Beta("decay", alpha=decay_alpha, beta=decay_beta, shape=n_channels)
        elif parameterization == "logit_normal":
            mu_logit = pm.Normal("mu_logit", mu=-1.4, sigma=0.7)
            sigma_logit = pm.HalfNormal("sigma_logit", sigma=1.0)
            z = pm.Normal("z", mu=0.0, sigma=1.0, shape=n_channels)
            decay = pm.Deterministic("decay", pm.math.sigmoid(mu_logit + sigma_logit * z))
        else:
            raise ValueError(f"Unknown parameterization: {parameterization}")

        # Hill saturation params (NOT hierarchical for this pilot — focus on decay)
        alphas = pm.Gamma("alphas", alpha=5.0, beta=3.0, shape=n_channels)
        gammas = pm.Beta("gammas", alpha=3.0, beta=3.0, shape=n_channels)
        betas = pm.HalfNormal("betas", sigma=0.5, shape=n_channels)
        intercept = pm.Normal("intercept", mu=0.0, sigma=2.0)
        sigma_obs = pm.HalfNormal("sigma_obs", sigma=0.5)

        # Apply adstock (vectorized via scan would be ideal — use per-channel loop here)
        contributions = []
        for j in range(n_channels):
            x_j = raw_spend[:, j]
            # Geometric adstock (recursive)
            adstock_init = pt.as_tensor_variable(x_j[0])
            adstock_seq, _ = pm.pytensorf.scan(
                fn=lambda x_t, prev, d: x_t + d * prev,
                sequences=[pt.as_tensor_variable(x_j[1:])],
                outputs_info=[adstock_init],
                non_sequences=[decay[j]],
            )
            adstock_full = pt.concatenate([[adstock_init], adstock_seq])
            mean_j = adstock_full.mean()
            x_norm = adstock_full / pt.maximum(mean_j, 1e-10)
            sat = x_norm ** alphas[j] / (
                x_norm ** alphas[j] + gammas[j] ** alphas[j]
            )
            contributions.append(betas[j] * sat)
        media_total = pt.sum(pt.stack(contributions), axis=0)
        mu_y = intercept + media_total

        pm.Normal("y", mu=mu_y, sigma=sigma_obs, observed=y_obs)

        try:
            trace = pm.sample(
                draws=draws,
                tune=tune,
                chains=chains,
                target_accept=target_accept,
                nuts_sampler="numpyro",
                random_seed=seed,
                progressbar=False,
                return_inferencedata=True,
            )
        except Exception as e:
            return {
                "error": f"NumPyro failed: {type(e).__name__}: {str(e)[:200]}",
                "elapsed": time.time() - t0,
            }

    elapsed = time.time() - t0

    # Diagnostics
    divergences = int(trace.sample_stats.get("diverging", 0).sum().values) if "diverging" in trace.sample_stats else 0
    summary_df = az.summary(trace, var_names=["decay"], hdi_prob=0.9)

    decay_means = trace.posterior["decay"].mean(dim=["chain", "draw"]).values
    decay_hdi = az.hdi(trace.posterior["decay"], hdi_prob=0.9)["decay"].values  # shape (n_channels, 2)

    # Recovery: how many channels' true decay falls within 90% HDI?
    true_decays = data["true_decays"]
    in_ci = sum(
        1 for j in range(n_channels)
        if decay_hdi[j, 0] <= true_decays[j] <= decay_hdi[j, 1]
    )

    return {
        "parameterization": parameterization,
        "elapsed": elapsed,
        "divergences": divergences,
        "decay_means": decay_means.tolist(),
        "decay_hdi_low": decay_hdi[:, 0].tolist(),
        "decay_hdi_high": decay_hdi[:, 1].tolist(),
        "true_decays": true_decays.tolist(),
        "recovery_count": in_ci,
        "recovery_pct": float(in_ci / n_channels * 100),
        "rhat_max": float(summary_df["r_hat"].max()),
        "ess_bulk_min": float(summary_df["ess_bulk"].min()),
    }


def format_result(r: dict) -> str:
    """Pretty-print one fit result."""
    if "error" in r:
        return f"FAILED: {r['error']} (elapsed={r['elapsed']:.1f}s)"
    lines = [
        f"  parameterization: {r['parameterization']}",
        f"  elapsed:          {r['elapsed']:.1f} s",
        f"  divergences:      {r['divergences']}",
        f"  R-hat max:        {r['rhat_max']:.3f}",
        f"  ESS bulk min:     {r['ess_bulk_min']:.0f}",
        f"  recovery 90% HDI: {r['recovery_count']}/{len(r['true_decays'])} ({r['recovery_pct']:.0f}%)",
        "  per-channel:",
    ]
    for j in range(len(r['true_decays'])):
        lines.append(
            f"    ch{j}: true={r['true_decays'][j]:.2f} "
            f"posterior_mean={r['decay_means'][j]:.2f} "
            f"HDI=[{r['decay_hdi_low'][j]:.2f},{r['decay_hdi_high'][j]:.2f}]"
        )
    return "\n".join(lines)


def write_results_doc(results: dict, output_path: Path):
    """Write markdown summary for Антон + future implementation reference."""
    lines = [
        "# Phase 1.1 Pilot Results — logit-normal vs Beta-Beta hierarchy",
        "",
        f"**Generated:** 2026-04-26 by tools/pilot_phase11_hierarchy.py",
        "**Purpose:** ADR §3.A1 — validate prior choice before 12-15h Phase 1.1 implementation.",
        "",
        "## Synthetic data",
        f"- n_obs: {results['data']['n_obs']}",
        f"- n_channels: {results['data']['n_channels']}",
        f"- True decays: {results['data']['true_decays'].tolist()}",
        "",
        "## Beta-Beta hierarchy",
        "",
        "```",
        format_result(results['beta_beta']),
        "```",
        "",
        "## Logit-normal hierarchy",
        "",
        "```",
        format_result(results['logit_normal']),
        "```",
        "",
        "## Verdict",
        "",
    ]
    bb = results['beta_beta']
    ln = results['logit_normal']
    if 'error' in bb and 'error' in ln:
        lines.append("Both parameterizations FAILED — investigate model specification.")
    elif 'error' in bb:
        lines.append("Beta-Beta failed; **logit-normal is the only viable option**.")
    elif 'error' in ln:
        lines.append("Logit-normal failed; **fall back to Beta-Beta** (suboptimal but works).")
    else:
        # Compare
        bb_score = bb['recovery_pct']
        ln_score = ln['recovery_pct']
        time_ratio = ln['elapsed'] / max(bb['elapsed'], 1e-3)
        div_ratio = (ln['divergences'] + 1) / (bb['divergences'] + 1)
        lines.append(f"- Recovery: Beta-Beta {bb_score:.0f}%, logit-normal {ln_score:.0f}%")
        lines.append(f"- Divergences: Beta-Beta {bb['divergences']}, logit-normal {ln['divergences']}")
        lines.append(f"- Time ratio (LN/BB): {time_ratio:.2f}×")
        lines.append("")
        if ln['divergences'] <= bb['divergences'] and time_ratio <= 1.2:
            lines.append("**RECOMMENDATION: Adopt logit-normal** (fewer divergences, comparable speed).")
        elif bb['divergences'] <= ln['divergences'] and 1.0 / time_ratio <= 1.2:
            lines.append("**RECOMMENDATION: Adopt Beta-Beta** (fewer divergences, comparable speed).")
        else:
            lines.append("**RECOMMENDATION: Mixed signals** — proceed with logit-normal default per ADR (better theoretical properties), monitor empirically on real data.")
    lines.append("")
    lines.append("Refs: docs/SPRINT1_FOUNDATION_ADR.md §3.A1, §5 Phase 1.1 plan")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nResults written to {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Quick mode: chains=2, draws=500")
    args = parser.parse_args()

    if args.quick:
        chains, draws, tune = 2, 500, 500
    else:
        chains, draws, tune = 4, 2000, 2000

    print(f"Phase 1.1 Pilot — chains={chains}, draws={draws}, tune={tune}")
    print("Generating synthetic data (n=36, 5 channels, mixed TV/Digital decay)...")
    data = make_synthetic(n_obs=36, n_channels=5)
    print(f"  True decays: {data['true_decays']}")
    print()

    print("=" * 60)
    print("Fitting Beta-Beta hierarchy...")
    print("=" * 60)
    r_bb = fit_pymc_hierarchy(data, "beta_beta", chains, draws, tune)
    print(format_result(r_bb))

    print()
    print("=" * 60)
    print("Fitting logit-normal hierarchy...")
    print("=" * 60)
    r_ln = fit_pymc_hierarchy(data, "logit_normal", chains, draws, tune)
    print(format_result(r_ln))

    results = {
        "data": data,
        "beta_beta": r_bb,
        "logit_normal": r_ln,
    }
    output_path = REPO / "docs" / "PHASE_1_1_PILOT_RESULTS.md"
    write_results_doc(results, output_path)


if __name__ == "__main__":
    main()
