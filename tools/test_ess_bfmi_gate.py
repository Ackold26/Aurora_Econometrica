"""ESS/E-BFMI gate — характеризующие тесты мат-аудита 2026-07-02 (F-11/F-12).

MATH_REFERENCE «Diagnostics gate» декларировал ESS_bulk/tail < 400 → WARN и
BFMI < 0.3 → WARN, но в коде гейтов НЕ БЫЛО (diagnostics.py не знал про
ESS/BFMI вовсе; modeler собирал только per-channel tail_ess_ok без потребителя
в вердикте). Теперь: modeler собирает min bulk/tail-ESS (Vehtari et al. 2021 —
recommended threshold 400; при ESS < 400 сам R-hat ненадёжен) и min E-BFMI
(эвристика Stan/PyMC 0.3) → metrics + checks → optimizer_honesty понижает
вердикт до uncertain. MQS-формула НЕ изменена (клиентские числа стабильны).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from utils.diagnostics import generate_diagnostics_summary  # noqa: E402
from utils.optimizer_honesty import model_reliability_verdict  # noqa: E402


GOOD = dict(r_squared=0.92, mape=8.0, rmse=100.0, r_hat_max=1.0,
            divergences=0, n_obs=200, n_params=18)


# ─── diagnostics: metrics + checks ───────────────────────────────────────────

def test_metrics_and_checks_present_when_measured():
    d = generate_diagnostics_summary(**GOOD, ess_bulk_min=850.0, ess_tail_min=620.0,
                                     bfmi_min=0.9)
    assert d['metrics']['ess_bulk_min'] == 850.0
    assert d['metrics']['ess_tail_min'] == 620.0
    assert d['metrics']['bfmi_min'] == 0.9
    assert d['checks']['ess'] is True
    assert d['checks']['bfmi'] is True


def test_low_ess_flags_check_false():
    d = generate_diagnostics_summary(**GOOD, ess_bulk_min=120.0, ess_tail_min=980.0)
    assert d['checks']['ess'] is False  # bulk < 400 (Vehtari 2021)


def test_low_bfmi_flags_check_false():
    d = generate_diagnostics_summary(**GOOD, bfmi_min=0.21)
    assert d['checks']['bfmi'] is False


def test_backcompat_no_kwargs_no_keys():
    """Старые вызовы (OLS/recompute/старые тесты) — ключей ess/bfmi в checks НЕТ
    (unknown ≠ pass), metrics — null; MQS не изменился."""
    d = generate_diagnostics_summary(**GOOD)
    assert 'ess' not in d['checks']
    assert 'bfmi' not in d['checks']
    assert d['metrics']['ess_bulk_min'] is None
    assert d['metrics']['bfmi_min'] is None
    d_with = generate_diagnostics_summary(**GOOD, ess_bulk_min=100.0,
                                          ess_tail_min=100.0, bfmi_min=0.1)
    assert d_with['mqs']['score'] == d['mqs']['score'], 'ESS/BFMI не должны менять MQS'


# ─── honesty-gate: uncertain при low ESS / low BFMI ──────────────────────────

def _diag(**kw):
    return generate_diagnostics_summary(**GOOD, **kw)


def test_honesty_uncertain_on_low_ess():
    v = model_reliability_verdict(_diag(ess_bulk_min=150.0, ess_tail_min=900.0))
    assert v['verdict'] == 'uncertain'
    assert v['refused'] is False
    assert any('400' in r and 'Vehtari' in r for r in v['reasons']), v['reasons']


def test_honesty_uncertain_on_low_bfmi():
    v = model_reliability_verdict(_diag(bfmi_min=0.15))
    assert v['verdict'] == 'uncertain'
    assert any('E-BFMI' in r for r in v['reasons']), v['reasons']
    # Урок T3.10: порог 0.3 — эвристика Stan/PyMC, НЕ приписывать Betancourt.
    assert not any('Betancourt' in r for r in v['reasons'])


def test_honesty_reliable_when_ess_bfmi_good():
    v = model_reliability_verdict(_diag(ess_bulk_min=900.0, ess_tail_min=800.0,
                                        bfmi_min=0.95))
    assert v['verdict'] == 'reliable', v


def test_honesty_backcompat_absent_keys_not_failure():
    """OLS/legacy диагностика без ess/bfmi ключей — вердикт как раньше."""
    v = model_reliability_verdict(_diag())
    assert v['verdict'] == 'reliable', v


# ─── F-13: prior predictive (in-train preflight) → honesty ───────────────────

def test_honesty_uncertain_on_prior_predictive_fail():
    d = _diag()
    d['preflight'] = {'prior_predictive': {'status': 'fail', 'coverage': 0.3}}
    v = model_reliability_verdict(d)
    assert v['verdict'] == 'uncertain'
    assert any('Prior predictive' in r for r in v['reasons']), v['reasons']


def test_honesty_prior_predictive_warn_not_uncertain():
    """warn — информируем warnings-каналом, вердикт не понижаем (только fail)."""
    d = _diag(ess_bulk_min=900.0, ess_tail_min=800.0, bfmi_min=0.9)
    d['preflight'] = {'prior_predictive': {'status': 'warn', 'coverage': 0.7}}
    v = model_reliability_verdict(d)
    assert v['verdict'] == 'reliable', v


def test_honesty_preflight_absent_backcompat():
    """Нет preflight-ключа (legacy diagnostics) — не считается провалом."""
    d = _diag(ess_bulk_min=900.0, ess_tail_min=800.0, bfmi_min=0.9)
    assert 'preflight' not in d
    v = model_reliability_verdict(d)
    assert v['verdict'] == 'reliable', v


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
