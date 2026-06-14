"""Unit-тесты M2 verdict-gate (utils.optimizer_honesty.model_reliability_verdict).

Тестируем ВНЕШНЕЕ поведение: на каком diagnostics → какой verdict/refused.
Диагностики смоделированы по реальной структуре results/model-diagnostics.json
(generate_diagnostics_summary output). Prior art: tools/test_optimizer_*.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sidecar'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sidecar' / 'econometrica'))

from utils.optimizer_honesty import model_reliability_verdict  # noqa: E402


def _diag(*, ratio_ok, r_hat=1.0, divergences=0, tier='good', ratio=5.0,
          chains=4, draws=2000, score=75):
    """Сборка diagnostics-словаря в форме model-diagnostics.json."""
    return {
        'mqs': {'score': score, 'tier': tier, 'tier_label': tier, 'thinness_cap': None},
        'metrics': {
            'r_hat_max': r_hat, 'divergences': divergences, 'ratio': ratio,
            'n_observations': 31, 'n_parameters': 20,
            'mcmc': {'chains': chains, 'draws': draws, 'tune': draws},
        },
        'checks': {'convergence': r_hat < 1.05 and divergences == 0,
                   'fit': True, 'ratio': ratio_ok},
    }


def test_reliable_all_checks_pass():
    v = model_reliability_verdict(_diag(ratio_ok=True, ratio=5.0, r_hat=1.0,
                                        divergences=0, tier='good'))
    assert v['verdict'] == 'reliable'
    assert v['refused'] is False
    assert v['reasons'] == []
    assert v['caveat_text'] == ''


def test_uncertain_thin_data_kagocel_like():
    # Реальный Кагоцел: Ratio 2.4<4, r_hat 1.0, 1 дивергенция, tier good.
    v = model_reliability_verdict(_diag(ratio_ok=False, ratio=2.4, r_hat=1.0,
                                        divergences=1, tier='good'))
    assert v['verdict'] == 'uncertain'
    assert v['refused'] is False
    assert any('тонк' in r.lower() or 'ratio' in r.lower() for r in v['reasons'])
    assert v['caveat_text']  # непустой баннер


def test_uncertain_weak_tier_even_if_ratio_ok():
    v = model_reliability_verdict(_diag(ratio_ok=True, ratio=6.0, tier='weak', score=35))
    assert v['verdict'] == 'uncertain'
    assert v['refused'] is False


def test_unreliable_high_rhat_refuses():
    v = model_reliability_verdict(_diag(ratio_ok=True, ratio=5.0, r_hat=1.12,
                                        divergences=0, tier='good'))
    assert v['verdict'] == 'unreliable'
    assert v['refused'] is True
    assert any('сош' in r.lower() or 'r-hat' in r.lower() for r in v['reasons'])


def test_unreliable_many_divergences_refuses():
    # 8000 черновиков → порог max(20, 80)=80; 200>80 → refuse.
    v = model_reliability_verdict(_diag(ratio_ok=True, ratio=5.0, r_hat=1.0,
                                        divergences=200, chains=4, draws=2000))
    assert v['verdict'] == 'unreliable'
    assert v['refused'] is True


def test_few_divergences_not_refused_but_uncertain():
    # 1 дивергенция на 8000 → не refuse, но uncertain (mild_div).
    v = model_reliability_verdict(_diag(ratio_ok=True, ratio=5.0, r_hat=1.0,
                                        divergences=1, chains=4, draws=2000, tier='good'))
    assert v['verdict'] == 'uncertain'
    assert v['refused'] is False


def test_divergence_abs_floor_when_draws_unknown():
    # mcmc отсутствует → абс. пол 20; 25>20 → refuse.
    d = _diag(ratio_ok=True, ratio=5.0, divergences=25)
    d['metrics'].pop('mcmc')
    v = model_reliability_verdict(d)
    assert v['verdict'] == 'unreliable'
    assert v['refused'] is True


def test_unknown_when_no_diagnostics():
    v = model_reliability_verdict({})
    assert v['verdict'] == 'unknown'
    assert v['refused'] is False
    assert v['reasons']  # есть пояснение «недоступна»


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
