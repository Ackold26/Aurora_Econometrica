"""MQS-1 (2026-06-02): verdict-текст не должен противоречить сам себе.

Корень: tier weak/poor достигается двумя путями — реально низкий fit ИЛИ высокий R²,
зажатый data-thinness cap (короткий ряд → переобучение). Во втором случае старая
формулировка «объясняет ТОЛЬКО 98%» вводит в заблуждение: 98% — высокий fit, проблема
в переобучении. INV-50: честно про корень неопределённости.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.diagnostics import generate_diagnostics_summary, model_quality_score


def test_high_r2_thin_data_verdict_not_misleading():
    """Кагоцел-кейс: R²=98%, ratio<2 → tier weak. Не должно быть «только 98%»."""
    summary = generate_diagnostics_summary(
        r_squared=0.98, mape=5.0, rmse=100.0,
        r_hat_max=1.0, divergences=0, n_obs=31, n_params=18,
    )
    assert summary['mqs']['tier'] == 'weak'  # ratio 1.7 → cap 50
    verdict = summary['verdict']
    assert 'только' not in verdict, f"Вводящее в заблуждение «только» при R²=98%: {verdict}"
    assert '98%' in verdict
    # Тон McElreath (2026-06-20): высокий fit на коротких данных объясняем через
    # ограниченность точечной надёжности / priors / доверительные интервалы, а не
    # алармизмом «переобучение» (синхрон с optimizer_honesty.py).
    assert ('надёжность ограничена' in verdict.lower() or 'априорн' in verdict.lower()
            or 'доверительн' in verdict.lower()), \
        f"Должно честно объяснять ограниченность на коротких данных: {verdict}"


def test_genuinely_low_r2_keeps_honest_verdict():
    """Реально низкий fit (R²=20%, плохая сходимость) → честное «только 20%»."""
    summary = generate_diagnostics_summary(
        r_squared=0.20, mape=60.0, rmse=500.0,
        r_hat_max=1.2, divergences=5, n_obs=200, n_params=18,
    )
    assert summary['mqs']['tier'] == 'poor'
    verdict = summary['verdict']
    assert 'только' in verdict, f"Низкий fit — «только» уместно: {verdict}"
    assert '20%' in verdict


def test_excellent_verdict_unchanged():
    """Регрессия: надёжная модель — текст не тронут."""
    summary = generate_diagnostics_summary(
        r_squared=0.92, mape=8.0, rmse=100.0,
        r_hat_max=1.0, divergences=0, n_obs=200, n_params=18,
    )
    assert summary['mqs']['tier'] in ('excellent', 'good')
    assert 'Надёжный результат' in summary['verdict']
    assert 'только' not in summary['verdict']


def test_good_tier_thin_data_no_reliability_claim():
    """Sub-finding b (2026-06-13): tier good/excellent НО данных мало (ratio<4) → лид
    НЕ должен заявлять «надёжно для бюджетных решений» (противоречило бы предупреждению
    о переобучении). Согласовано с M2: тонкая «хорошая» модель = uncertain, не reliable.
    Кагоцел-кейс: эффективный ratio 2.4 → tier good, но thin_note присутствует."""
    summary = generate_diagnostics_summary(
        r_squared=0.98, mape=6.0, rmse=100.0,
        r_hat_max=1.0, divergences=0, n_obs=31, n_params=20,
        effective_params=13.1,  # эфф. ratio 31/13.1 ≈ 2.4 → tier good + thin
    )
    assert summary['mqs']['tier'] in ('excellent', 'good'), summary['mqs']['tier']
    assert summary['checks']['ratio'] is False  # тонко
    verdict = summary['verdict']
    assert 'Надёжный результат для принятия бюджетных решений' not in verdict, \
        f"Тонкая «хорошая» модель не должна заявлять надёжность для бюджета: {verdict}"
    assert 'ориентировочные' in verdict.lower() or 'переобуч' in verdict.lower()
    assert 'Ratio' in verdict  # thin_note присутствует


def test_thinness_cap_low_r2_still_honest():
    """Граничный: thin data НО реально низкий R² (<0.7) → остаётся «только»."""
    summary = generate_diagnostics_summary(
        r_squared=0.45, mape=30.0, rmse=300.0,
        r_hat_max=1.0, divergences=0, n_obs=20, n_params=15,
    )
    # ratio 1.3 → cap 50; raw mqs с R²=45 ниже → tier weak/poor, fit реально низкий
    verdict = summary['verdict']
    assert 'только' in verdict, f"R²=45% — низкий fit, «только» уместно: {verdict}"
