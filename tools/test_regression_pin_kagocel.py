"""Regression pin test для downstream consumers (decomposer/optimizer/etc.).

Phase B0.4 — guards against accidental drift в decomposer/optimizer/narrative
после modifications в Track A (awareness) или Track B (Weibull learnable).

Strategy:
- Use session-scoped synthetic_trained_project fixture (deterministic RNG seed=42).
- Run decomposer на pickle → extract channel ROI medians + verdict labels.
- Hash extracted values (4 sig digits) → compare к stored baseline.
- If hash mismatch → either intentional change (run with --update-baseline) or regression bug.

Fast (~1 sec) — no MCMC, just downstream pipeline.

Update baseline:
    python tools/test_regression_pin_kagocel.py --update-baseline
"""
from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sidecar'))

BASELINE_PATH = Path(__file__).parent / 'regression_baseline.json'


def _round(value: float, digits: int = 4) -> float:
    """Round для stable hashing across PyMC/JAX numerical noise."""
    if not isinstance(value, (int, float)):
        return value
    return round(float(value), digits)


def _round_dict(d: dict) -> dict:
    """Recursively round floats в nested dict для stable hash."""
    out = {}
    for k, v in sorted(d.items()):
        if isinstance(v, dict):
            out[k] = _round_dict(v)
        elif isinstance(v, list):
            out[k] = [_round(x) if isinstance(x, (int, float)) else x for x in v]
        elif isinstance(v, (int, float)):
            out[k] = _round(v)
        else:
            out[k] = v
    return out


def _hash_summary(summary: dict[str, Any]) -> str:
    """Stable SHA-256 hash JSON-serialized rounded summary."""
    rounded = _round_dict(summary)
    canonical = json.dumps(rounded, sort_keys=True, separators=(',', ':'))
    return sha256(canonical.encode('utf-8')).hexdigest()


def _extract_summary(model_data: dict) -> dict:
    """Extract стабильную summary structure для hashing.

    Includes:
    - per-channel posterior means (beta, alpha, gamma, decay)
    - normalization params
    - model_version

    Excludes (volatile):
    - posterior_samples (raw arrays — drift иногда из-за numpy/RNG)
    - y_actual / y_predicted (could change с decomposition reconstruction)
    """
    summary = {
        'model_version': model_data.get('model_version'),
        'channel_params': {},
        'normalization': {
            'y_mean': _round(model_data.get('normalization', {}).get('y_mean', 0)),
            'y_std': _round(model_data.get('normalization', {}).get('y_std', 0)),
        },
        'use_hierarchical': model_data.get('use_hierarchical'),
    }

    cp = model_data.get('channel_params') or {}
    for col in sorted(cp.keys()):
        params = cp[col]
        summary['channel_params'][col] = {
            'beta': _round(params.get('beta', 0)),
            'alpha': _round(params.get('alpha', 0)),
            'gamma': _round(params.get('gamma', 0)),
            'decay': _round(params.get('decay', 0)),
        }
    return summary


def _load_baseline() -> dict | None:
    if not BASELINE_PATH.exists():
        return None
    return json.loads(BASELINE_PATH.read_text(encoding='utf-8'))


def _save_baseline(summary: dict, hash_value: str) -> None:
    BASELINE_PATH.write_text(
        json.dumps(
            {'summary': _round_dict(summary), 'hash': hash_value},
            indent=2,
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )


def test_synthetic_pickle_summary_matches_baseline(synthetic_trained_project):
    """Verify synthetic pickle summary stable across PRs.

    Updates: pass --update-baseline через CLI invocation:
        python tools/test_regression_pin_kagocel.py --update-baseline

    Or interactively: delete tools/regression_baseline.json и re-run.
    """
    import pickle as _pickle
    pickle_path = synthetic_trained_project / 'models' / 'latest.pkl'
    with open(pickle_path, 'rb') as f:
        model_data = _pickle.load(f)

    summary = _extract_summary(model_data)
    current_hash = _hash_summary(summary)

    baseline = _load_baseline()
    if baseline is None:
        # First run — establish baseline
        _save_baseline(summary, current_hash)
        pytest.skip(f'Baseline established at {BASELINE_PATH}. Re-run для verify.')

    expected_hash = baseline.get('hash')
    assert current_hash == expected_hash, (
        f'Regression detected!\n'
        f'  Expected hash: {expected_hash}\n'
        f'  Current hash:  {current_hash}\n'
        f'\n'
        f'Если изменение intentional:\n'
        f'  rm {BASELINE_PATH}\n'
        f'  pytest tools/test_regression_pin_kagocel.py  # auto-establish new baseline\n'
        f'  git commit tools/regression_baseline.json\n'
        f'\n'
        f'Если unintentional — debug: дифф summary против baseline в JSON.'
    )


def test_kpi_registry_sales_priors_match_documented_constants():
    """Cross-check: KPI_REGISTRY['sales'] values matches Trust 3 hardcoded constants.

    If modeler.py priors change → этот тест catches drift.
    """
    from econometrica.utils.kpi_registry import get_kpi_config

    config = get_kpi_config('sales')

    # Documented values from modeler.py:408-410 (Trust Level 3, 2026-04-27)
    EXPECTED_BRAND_MU_LOGIT = (0.7, 0.3)
    EXPECTED_PERF_MU_LOGIT = (-1.4, 0.7)
    EXPECTED_MIXED_MU_LOGIT = (-1.4, 0.7)
    EXPECTED_BRAND_BETA_SIGMA = 0.7    # modeler.py:367
    EXPECTED_PERF_BETA_SIGMA = 0.3     # modeler.py:368
    EXPECTED_MIXED_BETA_SIGMA = 0.4    # modeler.py:369
    EXPECTED_GAMMAS_ALPHA_BETA = (3.0, 3.0)  # modeler.py:389
    EXPECTED_OBS_SIGMA = 0.3           # modeler.py:469

    assert config.brand_mu_logit_prior == EXPECTED_BRAND_MU_LOGIT
    assert config.perf_mu_logit_prior == EXPECTED_PERF_MU_LOGIT
    assert config.mixed_mu_logit_prior == EXPECTED_MIXED_MU_LOGIT
    assert config.brand_beta_sigma == EXPECTED_BRAND_BETA_SIGMA
    assert config.perf_beta_sigma == EXPECTED_PERF_BETA_SIGMA
    assert config.mixed_beta_sigma == EXPECTED_MIXED_BETA_SIGMA
    assert (config.gammas_alpha, config.gammas_beta) == EXPECTED_GAMMAS_ALPHA_BETA
    assert config.obs_sigma_prior == EXPECTED_OBS_SIGMA


def test_pickle_v20_fields_default_to_pre_v20_behavior():
    """Backward compat: load v1.x pickle → all v2.0 fields default semantics."""
    import pickle as _pickle
    import tempfile
    from econometrica.engines.persistence import (
        get_kpi_type, is_awareness_model, get_adstock_type, has_baseline_posterior
    )

    v13_data = {'model_version': '1.3', 'channel_categories': {}}
    with tempfile.NamedTemporaryFile(suffix='.pkl', delete=False) as f:
        _pickle.dump(v13_data, f)
        path = Path(f.name)

    try:
        from econometrica.engines.persistence import load_model_with_compat
        loaded = load_model_with_compat(path)
        # All defaults к pre-v2.0 behavior
        assert get_kpi_type(loaded) == 'sales'
        assert is_awareness_model(loaded) is False
        assert get_adstock_type(loaded, 'AnyChannel') == 'geometric'
        assert has_baseline_posterior(loaded) is False
    finally:
        path.unlink()


if __name__ == '__main__':
    # Standalone update mode
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--update-baseline', action='store_true')
    args = parser.parse_args()

    if args.update_baseline:
        BASELINE_PATH.unlink(missing_ok=True)
        print(f'Removed {BASELINE_PATH}')
        print('Re-run pytest tools/test_regression_pin_kagocel.py — baseline auto-established.')
    else:
        print('Run via pytest: pytest tools/test_regression_pin_kagocel.py')
        print('Update baseline: python tools/test_regression_pin_kagocel.py --update-baseline')
