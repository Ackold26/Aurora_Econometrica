"""Goal-Seek «бюджет под вероятность» — характеризующие тесты OPP-02 (2026-07-03).

Суть фичи: прежний goal-seek отдаёт медианный бюджет — бисекция останавливается
на S(B*) ≈ target, поэтому цель достигается лишь в ~половине posterior-сценариев
(P(hit) ≈ 0.5 by construction, см. F-03 мат-аудита). Режим confidence=0.8 ищет
минимальный B, при котором квантиль уровня (1−0.8) распределения posterior-draws
S(B) ≥ target, т.е. P(S(B) ≥ target) ≥ 0.8.

Монотонность квантильного forward — из per-draw монотонности S_s(B) (сумма
Hill-откликов растёт по B при фиксированных параметрах draw ⇒ стохастическое
доминирование ⇒ квантиль монотонен). Подтверждено зондом
tmp/probe_a2_sampler_cost.py: q20 монотонен на 11 точках; бисекция 13 итераций
≈ 163 мс; надбавка к медианному бюджету narrow +5.8% / wide +86.1%;
p_hit@B*(0.8) = 0.800 ровно.

Переиспользует _build_project из tools/test_goalseek_honesty.py (narrow/wide
posterior фикстуры).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_goalseek_honesty import _build_project, _moderate_target  # noqa: E402
from optimize.inverse import optimize_inverse  # noqa: E402


# ─── Ядро фичи: осторожный бюджет ≥ медианного, надбавка растёт с разбросом ──

@pytest.mark.parametrize('seed', [7, 23])
def test_confidence_budget_geq_median_and_grows_with_uncertainty(tmp_path, seed):
    """B*(0.8) ≥ B*(медиана); надбавка на wide-posterior ≫ надбавки на narrow.

    Зонд: narrow +5.8%, wide +86.1% — «осторожность растёт с неопределённостью».
    """
    premiums = {}
    for label, sd in [('narrow', 0.03), ('wide', 0.40)]:
        pdir = _build_project(tmp_path, f'{label}_{seed}', beta_sd=sd, seed=seed)
        target = _moderate_target(pdir)
        res_med = optimize_inverse(str(pdir), target_sales=target, kpi_kind='monetary')
        res_conf = optimize_inverse(str(pdir), target_sales=target, kpi_kind='monetary',
                                    confidence=0.8)
        assert res_med['achievable'] and res_conf['achievable']
        b_med = res_med['total_budget']['p50']
        b_conf = res_conf['total_budget']['p50']
        # Допуск дискретности бисекции (rel_tol=1e-3 от budget_hi).
        assert b_conf >= b_med * 0.995, (
            f'{label}: осторожный бюджет {b_conf:,.0f} МЕНЬШЕ медианного '
            f'{b_med:,.0f} — квантильная бисекция сломана'
        )
        premiums[label] = (b_conf - b_med) / b_med
    assert premiums['wide'] > premiums['narrow'] + 0.10, (
        f'Надбавка не растёт с неопределённостью: narrow={premiums["narrow"]:.3f}, '
        f'wide={premiums["wide"]:.3f} (зонд давал 0.058 vs 0.861)'
    )


def test_confidence_p_hit_self_consistent(tmp_path):
    """При B*(0.8): p_hit ≥ ~0.8 (дискретность 200 draws), метод posterior,
    маркер confidence в результате, медианный прогноз при бюджете — выше
    квантильного (гарантия ≤ типичный сценарий)."""
    pdir = _build_project(tmp_path, 'selfcons', beta_sd=0.40, seed=7)
    target = _moderate_target(pdir)
    res = optimize_inverse(str(pdir), target_sales=target, kpi_kind='monetary',
                           confidence=0.8)
    assert res['achievable'] is True
    assert res['confidence'] == pytest.approx(0.8)
    assert res['confidence_unavailable'] is False
    assert res['p_hit_method'] == 'posterior'
    assert res['p_hit_target'] >= 0.75, (
        f'p_hit={res["p_hit_target"]:.3f} при бюджете под 80% — само-подтверждение '
        f'сломано (зонд давал ровно 0.800)'
    )
    assert res['expected_sales_median'] is not None
    # Квантиль 0.2 ≤ типичного сценария (медианная траектория при том же B).
    assert res['expected_sales_median'] >= res['expected_sales'] * 0.99


# ─── Back-compat: прежнее поведение не тронуто ───────────────────────────────

def test_backcompat_no_confidence_param_identical(tmp_path):
    """Вызов без confidence == вызов с confidence=None == прежнее поведение
    (медианная бисекция, p_hit из posterior-доли, поля OPP-02 нейтральны)."""
    pdir = _build_project(tmp_path, 'backcompat', beta_sd=0.2, seed=11)
    target = _moderate_target(pdir)
    res_default = optimize_inverse(str(pdir), target_sales=target, kpi_kind='monetary')
    res_none = optimize_inverse(str(pdir), target_sales=target, kpi_kind='monetary',
                                confidence=None)
    assert res_default['achievable'] and res_none['achievable']
    assert res_default['total_budget']['p50'] == pytest.approx(
        res_none['total_budget']['p50'], rel=1e-12), 'confidence=None изменил медианный бюджет'
    assert res_default['confidence'] is None
    assert res_default['confidence_unavailable'] is False
    assert res_default['expected_sales_median'] is None


# ─── Честная деградация без posterior (INV-50) ───────────────────────────────

def test_confidence_without_posterior_marked_not_silent(tmp_path):
    """OLS/legacy pickle: просили 0.8 → медианный расчёт с ЯВНЫМ маркером
    (confidence_unavailable=True, confidence=None), не тихая подмена."""
    pdir = _build_project(tmp_path, 'nopost', beta_sd=0.05, with_posterior=False)
    target = _moderate_target(pdir)
    res = optimize_inverse(str(pdir), target_sales=target, kpi_kind='monetary',
                           confidence=0.8)
    assert res['achievable'] is True
    assert res['confidence'] is None, 'confidence НЕ применён — поле обязано быть None'
    assert res['confidence_unavailable'] is True
    assert res['confidence_unavailable_reason'] == 'no_posterior_samples'
    assert res['p_hit_method'] == 'heuristic'


# ─── Валидация уровня ────────────────────────────────────────────────────────

@pytest.mark.parametrize('bad', [0.0, 1.0, 1.5, -0.3, 'abc'])
def test_confidence_invalid_rejected(tmp_path, bad):
    pdir = _build_project(tmp_path, f'invalid_{str(bad)[:3]}', beta_sd=0.1)
    res = optimize_inverse(str(pdir), target_sales=1.0, kpi_kind='monetary',
                           confidence=bad)
    assert res['achievable'] is False
    assert res['error'] == 'INVALID_CONFIDENCE'


# ─── Недостижимость в квантильном режиме: честная формулировка ───────────────

def test_confidence_unreachable_message_names_probability(tmp_path):
    """Цель ×1000: недостижимо; message называет вероятность, fallback_max_sales =
    квантильный максимум (≤ медианного потолка)."""
    pdir = _build_project(tmp_path, 'unreach', beta_sd=0.40, seed=7)
    fwd_target = _moderate_target(pdir, growth=1000.0)
    res_conf = optimize_inverse(str(pdir), target_sales=fwd_target, kpi_kind='monetary',
                                confidence=0.8)
    res_med = optimize_inverse(str(pdir), target_sales=fwd_target, kpi_kind='monetary')
    assert res_conf['achievable'] is False and res_med['achievable'] is False
    assert 'вероятностью 80' in res_conf['message']
    assert res_conf['confidence'] == pytest.approx(0.8)
    # Квантильный потолок консервативнее медианного.
    assert res_conf['fallback_max_sales'] <= res_med['fallback_max_sales'] * (1 + 1e-9)


# ─── Экстраполяция и семантика expected_sales в квантильном режиме ───────────

def test_confidence_extrapolation_and_quantile_sales_semantics(tmp_path):
    """Маркер экстраполяции жив в осторожном режиме; expected_sales = квантильное
    значение при B* — не ниже цели (бисекция гарантирует q(B*) ≥ target)."""
    pdir = _build_project(tmp_path, 'extra_conf', beta_sd=0.40, seed=7)
    target = _moderate_target(pdir)
    res = optimize_inverse(str(pdir), target_sales=target, kpi_kind='monetary',
                           confidence=0.8)
    assert res['achievable'] is True
    assert res['extrapolation'] is not None
    assert res['expected_sales'] >= target * (1 - 1e-6), (
        'Квантильные продажи при B*(0.8) ниже цели — бисекция по квантильному '
        'forward не сошлась'
    )


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
