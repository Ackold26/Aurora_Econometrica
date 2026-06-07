"""Tests для per-control contraction (#6 OVB-guardrail, 2026-06-07).

contraction = clip(1 − Var_post/Var_prior, 0, 1) на каждый control_beta.
<0.1 → контроль неинформативен (posterior≈prior) → OVB-safe убрать; ≥0.3 → информативен.
SSOT-формула в diagnostics — общая для modeler (train) и recompute_mqs (миграция).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.diagnostics import per_control_contraction  # noqa: E402

PRIOR = 0.3  # control_betas ~ N(mu, 0.3)


def test_classifies_informative_vs_uninformative():
    # post SD: 0.06 (сильное сжатие), 0.30 (=prior → 0), 0.29 (почти prior → ~0)
    r = per_control_contraction([0.06, 0.30, 0.29], PRIOR, ['informative', 'flat', 'weak'])
    assert r['informative'] > 0.9          # 1 − (0.06/0.3)^2 = 0.96
    assert r['flat'] < 0.1                  # 1 − (0.3/0.3)^2 = 0.0
    assert r['weak'] < 0.1                  # 1 − (0.29/0.3)^2 ≈ 0.066


def test_clip_bounds_0_1():
    # sd > prior → contraction clipped to 0 (не отрицательное)
    r = per_control_contraction([0.5], PRIOR, ['noisy'])
    assert r['noisy'] == 0.0
    # sd ≈ 0 → contraction ≈ 1
    r2 = per_control_contraction([1e-9], PRIOR, ['tight'])
    assert r2['tight'] == 1.0


def test_empty_and_guard_cases():
    assert per_control_contraction(None, PRIOR, ['a']) == {}
    assert per_control_contraction([0.1], 0, ['a']) == {}      # prior=0 → guard
    assert per_control_contraction([0.1], PRIOR, []) == {}     # нет контролей
    assert per_control_contraction([0.1], None, ['a']) == {}   # prior None → guard


def test_maps_to_control_names_in_order():
    r = per_control_contraction([0.06, 0.30], PRIOR, ['first', 'second'])
    assert set(r.keys()) == {'first', 'second'}
    assert r['first'] > r['second']  # first информативнее
