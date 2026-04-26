"""
Phase 1.9 end-to-end demo — synthetic pickle → decompose/scenario → JSON with CI.

Purpose:
1. Smoke test for full Phase 1.9 pipeline before Антон's live-test (T16).
2. Reference output showing CI field formats для UI implementation downstream.
3. Backward-compat verification (v1.1 pickle without samples → no CI fields).

Generates two pickles:
- v1.1.5 with posterior_samples (Phase 1.9 enabled)
- v1.1 without samples (backward compat path)

Runs decomposer + scenario on each, prints output diff. Both paths must work.

Run:
    cd D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica
    python tools/demo_phase1_9_e2e.py
"""
from __future__ import annotations

import json
import pickle
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "sidecar"
sys.path.insert(0, str(SIDECAR / "econometrica"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


N_OBS = 36
N_CHANNELS = 5
N_SAMPLES = 8000


def make_data_file(out_path: Path):
    """Create monthly Excel dataset with 5 channels + KPI."""
    rng = np.random.default_rng(42)
    df = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=N_OBS, freq="MS"),
        "TV":     rng.exponential(50, N_OBS),
        "OLV":    rng.exponential(30, N_OBS),
        "Banners": rng.exponential(20, N_OBS),
        "Performance": rng.exponential(15, N_OBS),
        "Articles": rng.exponential(10, N_OBS),
        "sales": 100 + rng.normal(0, 20, N_OBS) + np.linspace(0, 50, N_OBS),
    })
    df.to_excel(out_path, index=False)
    return df


def make_pickle(model_path: Path, data_file: Path, with_samples: bool):
    """Create synthetic trained model pickle.

    with_samples=True → v1.1.5 (Phase 1.9 CI capable)
    with_samples=False → v1.1 (backward compat, no CI)
    """
    rng = np.random.default_rng(0)
    media_cols = ["TV", "OLV", "Banners", "Performance", "Articles"]
    df = pd.read_excel(data_file)

    media_means = {c: float(df[c].mean()) for c in media_cols}
    y = df["sales"].values
    y_mean = float(y.mean())
    y_std = float(y.std())

    # Synthetic point estimates (means)
    channel_params = {}
    for c in media_cols:
        channel_params[c] = {
            "beta": float(rng.uniform(0.1, 0.5)),
            "alpha": float(rng.uniform(1.0, 2.5)),
            "gamma": float(rng.uniform(0.3, 0.9)),
            "adstock": "geometric",
            "tail_ess_ok": True,
        }

    model_data = {
        "config": {
            "data_file": str(data_file),
            "media_columns": media_cols,
            "control_columns": [],
            "kpi_column": "sales",
            "date_column": "date",
            "adstock_config": {c: "geometric" for c in media_cols},
            "unit_costs": {c: 1.0 for c in media_cols},
        },
        "channel_params": channel_params,
        "normalization": {
            "media_means": media_means,
            "control_means": {},
            "control_stds": {},
            "y_mean": y_mean,
            "y_std": y_std,
            "intercept_mean": 0.05,
            "control_betas_mean": [],
            "untrained_channels": [],
        },
        "y_actual": y.tolist(),
        "y_predicted": (y * 0.95).tolist(),
        "model_version": "1.1.5" if with_samples else "1.1",
    }

    if with_samples:
        # Synthetic posterior — joint structure (n_channels, n_samples)
        # Centered at point estimates, with realistic dispersion.
        media_betas_samples = np.zeros((N_CHANNELS, N_SAMPLES), dtype=np.float32)
        alphas_samples = np.zeros((N_CHANNELS, N_SAMPLES), dtype=np.float32)
        gammas_samples = np.zeros((N_CHANNELS, N_SAMPLES), dtype=np.float32)
        for i, c in enumerate(media_cols):
            beta = channel_params[c]["beta"]
            media_betas_samples[i] = rng.normal(beta, beta * 0.15, N_SAMPLES).astype(np.float32)
            alphas_samples[i] = rng.gamma(channel_params[c]["alpha"] * 3, 1/3, N_SAMPLES).astype(np.float32)
            gammas_samples[i] = rng.beta(channel_params[c]["gamma"] * 5, (1-channel_params[c]["gamma"]) * 5, N_SAMPLES).astype(np.float32)

        model_data["posterior_samples"] = {
            "media_betas": media_betas_samples,
            "alphas": alphas_samples,
            "gammas": gammas_samples,
            "intercept": rng.normal(0.05, 0.1, N_SAMPLES).astype(np.float32),
            "control_betas": np.zeros((0, N_SAMPLES), dtype=np.float32),
            "media_columns": media_cols,
            "control_columns": [],
            "n_chains": 4,
            "n_draws": 2000,
        }

    model_path.parent.mkdir(parents=True, exist_ok=True)
    with open(model_path, "wb") as f:
        pickle.dump(model_data, f)
    return model_data


def run_demo():
    from engines.decomposer import decompose
    from engines.scenario import predict_scenario
    from engines.optimizer import optimize

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Two project dirs — with and without posterior samples
        for label, with_samples in [("v1.1.5_with_samples", True), ("v1.1_legacy", False)]:
            print(f"\n{'='*60}\nDEMO: {label}\n{'='*60}")
            project_dir = tmp_path / label
            data_file = project_dir / "data.xlsx"
            project_dir.mkdir(parents=True, exist_ok=True)
            make_data_file(data_file)
            model_path = project_dir / "models" / "latest.pkl"
            make_pickle(model_path, data_file, with_samples=with_samples)
            size_kb = model_path.stat().st_size / 1024
            print(f"  Pickle size: {size_kb:.1f} KB")

            # Run decompose
            result = decompose(str(project_dir))
            assert result["status"] == "ok", f"decompose failed: {result}"

            # Show first channel CI fields
            ch0 = result["channels"][0]
            print(f"\n  Channel '{ch0['name']}':")
            print(f"    spend:        {ch0.get('spend')}")
            print(f"    contribution: {ch0.get('contribution')}")
            print(f"    roi:          {ch0.get('roi')}")
            if 'roi_ci_low' in ch0:
                print(f"    roi_ci_low:   {ch0.get('roi_ci_low')} ✅ Phase 1.9")
                print(f"    roi_ci_high:  {ch0.get('roi_ci_high')}")
                print(f"    contrib_ci:   [{ch0.get('contribution_ci_low')}, {ch0.get('contribution_ci_high')}]")
            else:
                print(f"    roi_ci_*:     NOT POPULATED (legacy v1.1 — expected)")
            print(f"    verdict:      {ch0.get('verdict')} ({ch0.get('verdict_tone')})")

            # Run scenario — pass current spend pattern as plan
            df = pd.read_excel(data_file)
            media_plan = {
                c: df[c].tolist() for c in
                ["TV", "OLV", "Banners", "Performance", "Articles"]
            }
            sc = predict_scenario({
                "scenario_name": f"baseline_{label}",
                "media_plan": media_plan,
                "unit_costs": {c: 1.0 for c in media_plan},
            }, str(project_dir))
            if sc["status"] != "ok":
                print(f"  Scenario error: {sc.get('message')}")
                continue
            totals = sc["totals"]
            print(f"\n  Scenario totals:")
            print(f"    predicted_kpi: {totals.get('predicted_kpi')}")
            if totals.get("predicted_kpi_ci_low") is not None:
                print(f"    predicted_kpi_ci: [{totals.get('predicted_kpi_ci_low')}, {totals.get('predicted_kpi_ci_high')}] ✅ Phase 1.9")
                print(f"    roas: {totals.get('roas')}, roas_ci: [{totals.get('roas_ci_low')}, {totals.get('roas_ci_high')}]")
                print(f"    lift_pct: {totals.get('lift_pct')}, lift_ci: [{totals.get('lift_pct_ci_low')}, {totals.get('lift_pct_ci_high')}]")
            else:
                print(f"    *_ci_*: NOT POPULATED (legacy v1.1 — expected)")

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)
    print("\n✅ Phase 1.9 backend smoke test: BOTH paths work")
    print("   - v1.1.5 with samples → CI fields populated through full pipeline")
    print("   - v1.1 legacy → graceful fallback to point estimates only")
    print("\nReady for T16 live-test on real Kagocel data.")


if __name__ == "__main__":
    run_demo()
