"""
Регресс-гейт демо-файлов: prior-check coverage + субоптимальный lift + детерминизм.

Антон (F-A1-10/20, 2026-07-05): demo-файлы = образец и первое впечатление клиента.
Гейты по ВСЕМ 4 категориям: fmcg / otc_pharma / real_estate / retail_ecom.

Prior-check (2026-07-06, фаза 2):
    prior_predictive_check теперь принимает dates и инжектирует в симуляцию те же
    компоненты, что modeler включает автоматически: Фурье-сезонность (period=12,
    n_harmonics=3 → 6 sin/cos колонок) + праздники РФ (12 fraction-дамми), нормализованные
    Z-score. Приоры: Normal(0.0, sigma=0.3) для обоих — строго из modeler.py:584-590
    (SSOT). После этого исправления coverage = 0.875-0.938 (все категории pass ≥ 0.80).

    Без dates (backward compat): симуляция без сезонности → coverage 38-50%, как раньше.
    Вызов из modeler.py:654 без dates — не ломается (graceful degradation).

Lift-тест (аналитический): проверяет что при субоптимальном стартовом сплите
(TV~60-76%, high-ROI channel ~4-10%) существует альтернативное распределение budget
с теоретически лучшим ROI. Использует weighted-average ROI метрику (до насыщения).
Реальный lift после Hill-насыщения будет меньше теоретического, но Aurora-оптимизатор
использует gradient-based поиск от другого start_point → находит +10-25%.

Детерминизм: seed-фиксирован, повторная генерация даёт идентичные строки.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'sidecar' / 'econometrica'))
sys.path.insert(0, str(ROOT / 'tools'))

from synthetic_pilot_data import (  # noqa: E402
    GROUND_TRUTH_FMCG,
    GROUND_TRUTH_OTC_PHARMA,
    GROUND_TRUTH_REAL_ESTATE,
    GROUND_TRUTH_RETAIL_ECOM,
    generate_fmcg_brand,
    generate_otc_pharma,
    generate_real_estate,
    generate_retail_ecom,
)

# ─── Константы ────────────────────────────────────────────────────────────────

# Порог coverage prior_predictive — тот же что видит клиент.
# PRIOR_PRED_COVERAGE_FAIL = 0.50 (из reliability_a4.py, SSOT).
# После фазы 2 (dates → Фурье+праздники) coverage = 0.875-0.938 → все pass.
PRIOR_CHECK_COVERAGE_MIN = 0.50

# Теоретический lift (weighted avg ROI) при оптимальном перераспределении.
# Реальный оптимизатор Aurora находит +10-25% (из аналитического min 15%).
# Гейт теста = 0.10 (консервативный), чтобы тест не флакал.
LIFT_THEORETICAL_MIN = 0.10

# ─── Вспомогательные функции ──────────────────────────────────────────────────

def _prior_check(df: pd.DataFrame, media_spend_cols: list[str], kpi_col: str) -> dict:
    """Запускает prior_predictive_check на spend-колонках с датами (полная симуляция).

    dates передаются чтобы prior_predictive_check инжектировал Фурье-сезонность
    и праздники РФ — те же компоненты, что modeler включает автоматически.
    Без дат coverage было бы 38-50% (сезонность не смоделирована).
    """
    from utils.reliability_a4 import prior_predictive_check

    y = df[kpi_col].values.astype(float)
    X = df[media_spend_cols].fillna(0).values.astype(float)
    dates = pd.to_datetime(df['date']).values if 'date' in df.columns else None
    return prior_predictive_check(y, X, dates=dates, n_samples=300, seed=42)


def _theoretical_lift(gt: dict, df: pd.DataFrame,
                      spend_cols: list[str]) -> float:
    """Теоретический lift = (opt_weighted_roi - curr_weighted_roi) / curr_weighted_roi.

    Metric: weighted average ROI по долям бюджета. Оптимальный сплит —
    пропорциональный ROI-таргетам (линейная аппроксимация; Hill-насыщение
    снизит реальный lift, но сохранит знак).

    Аргумент реалистичности субоптимального сплита:
    TV 60-76% vs ROI=2.0-2.6×; performance/retail_media 4-10% vs ROI=4.6-5.5×.
    Это типично для РФ рынка: ТВ исторически доминирует в budget структуре
    (Nielsen MMM Benchmarks 2022; Ebiquity «Re-evaluating Media» 2022 — TV
    перегрет в mix относительно mROAS; performance системно недоинвестирован
    в >60% рекламодателей). → перекос реалистичен.
    """
    channel_order = list(gt['roi_targets'].keys())
    roi_vals = np.array([gt['roi_targets'][ch] for ch in channel_order])

    total_budget = sum(df[col].sum() for col in spend_cols)
    curr_amounts = np.array([df[col].sum() for col in spend_cols])
    curr_shares = curr_amounts / max(total_budget, 1e-9)

    weighted_roi_curr = float((curr_shares * roi_vals).sum())
    optimal_shares = roi_vals / roi_vals.sum()
    weighted_roi_opt = float((optimal_shares * roi_vals).sum())

    if abs(weighted_roi_curr) < 1e-9:
        return 0.0
    return (weighted_roi_opt - weighted_roi_curr) / weighted_roi_curr


def _df_hash(df: pd.DataFrame) -> str:
    """Хэш ключевых статистик DataFrame для детерминизм-проверки."""
    # Хэшируем: shape + column names + sum + mean округлённые (устойчиво к float noise).
    sig = f'{df.shape}|{list(df.columns)}|{df.select_dtypes("number").sum().round(2).to_dict()}'
    return hashlib.sha256(sig.encode()).hexdigest()[:16]


# ─── Описание сценариев ────────────────────────────────────────────────────────

SCENARIOS = [
    {
        'name': 'fmcg',
        'generator': generate_fmcg_brand,
        'seed': 42,
        'media_spend_cols': ['tv_spend', 'digital_spend', 'ooh_spend', 'performance_spend'],
        'kpi_col': 'sales_rub',
        'gt': GROUND_TRUTH_FMCG,
        # Субоптимальный сплит: TV~63%, performance~4% (ROI 2.2× vs 5.5×)
        'suboptimal_description': 'TV 30-90 TRP > performance 8-30k clicks; ROI TV=2.2× vs perf=5.5×',
    },
    {
        'name': 'otc_pharma',
        'generator': generate_otc_pharma,
        'seed': 43,
        'media_spend_cols': ['tv_spend', 'apteka_spend', 'digital_spend', 'performance_spend'],
        'kpi_col': 'sales_packs',
        'gt': GROUND_TRUTH_OTC_PHARMA,
        # Субоптимальный сплит: TV~76%, performance~7%
        'suboptimal_description': 'TV 60-180 TRP > performance 25-100k clicks; ROI TV=2.6× vs perf=4.6×',
    },
    {
        'name': 'retail_ecom',
        'generator': generate_retail_ecom,
        'seed': 44,
        'media_spend_cols': ['tv_spend', 'digital_spend', 'ooh_spend', 'retail_media_spend'],
        'kpi_col': 'sales_rub',
        'gt': GROUND_TRUTH_RETAIL_ECOM,
        # Субоптимальный сплит: TV~61%, retail_media~10%
        'suboptimal_description': 'TV 200-600 TRP > retail_media 10-50M impressions; ROI TV=2.0× vs retail_media=4.8×',
    },
    {
        'name': 'real_estate',
        'generator': generate_real_estate,
        'seed': 45,
        'media_spend_cols': ['tv_spend', 'ooh_spend', 'digital_spend', 'performance_spend'],
        'kpi_col': 'leads',
        'gt': GROUND_TRUTH_REAL_ESTATE,
        # Субоптимальный сплит: TV~62%, performance~9%
        'suboptimal_description': 'TV 90-380 GRP > performance 25-110k clicks; ROI TV=2.2× vs perf=5.0×',
    },
]

# ─── Параметризованные тесты ──────────────────────────────────────────────────

@pytest.mark.parametrize('scenario', SCENARIOS, ids=[s['name'] for s in SCENARIOS])
def test_prior_check_runs_without_error(scenario):
    """prior_predictive_check запускается без исключений + возвращает coverage float."""
    df = scenario['generator'](seed=scenario['seed'])
    result = _prior_check(df, scenario['media_spend_cols'], scenario['kpi_col'])

    assert isinstance(result, dict), 'prior_predictive_check должен вернуть dict'
    assert 'coverage' in result, 'Результат должен содержать ключ coverage'
    assert 'status' in result, 'Результат должен содержать ключ status'

    cov = result['coverage']
    assert isinstance(cov, float), f'coverage должен быть float, получен {type(cov)}'
    assert 0.0 <= cov <= 1.0, f'coverage={cov:.3f} вне диапазона [0, 1]'


@pytest.mark.slow
@pytest.mark.parametrize('scenario', SCENARIOS, ids=[s['name'] for s in SCENARIOS])
def test_prior_check_coverage_not_degenerate(scenario):
    """prior_predictive_check coverage ��� 0.50 (продуктовый порог FAIL).

    С фазой 2 (dates → Фурье-сезонность + праздники РФ) coverage = 0.875-0.938,
    что соответствует продуктовому статусу 'pass' (≥ 0.80).

    Гейт = PRIOR_CHECK_COVERAGE_MIN = 0.50 — тот же порог, что видит клиент
    (PRIOR_PRED_COVERAGE_FAIL из reliability_a4.py). Если coverage падает ниже 0.50,
    prior_predictive_check либо сломан, либо даты не переданы (regression guard).
    """
    df = scenario['generator'](seed=scenario['seed'])
    result = _prior_check(df, scenario['media_spend_cols'], scenario['kpi_col'])

    cov = result['coverage']
    status = result.get('status', 'unknown')
    ctrl = result.get('control_components', {})
    assert cov >= PRIOR_CHECK_COVERAGE_MIN, (
        f'[{scenario["name"]}] prior_predictive coverage={cov:.3f} < '
        f'PRIOR_CHECK_COVERAGE_MIN={PRIOR_CHECK_COVERAGE_MIN:.2f} (=продукт��вый порог FAIL). '
        f'status={status}. control_components={ctrl}. '
        f'Возможные причины: dates не переданы в prior_predictive_check, '
        f'Фурье/праздники не инжектированы, или инструмент деградировал. '
        f'y_range={result.get("y_observed_range")}'
    )


@pytest.mark.parametrize('scenario', SCENARIOS, ids=[s['name'] for s in SCENARIOS])
def test_theoretical_lift_positive(scenario):
    """Теоретический lift (weighted avg ROI) при оптимальном перераспределении ≥ 10%.

    Проверяет что стартовый сплит субоптимален: большой budget идёт в каналы с низким
    ROI, что создаёт возможность для оптимизатора.

    Аргумент реалистичности: текущий сплит TV 60-76% при ROI TV 2.0-2.6× vs high-ROI
    канал 4-10% при ROI 4.6-5.5× — типичная ситуация в РФ рекламном рынке (TV-центричная
    медиамикс структура; см. docstring _theoretical_lift).
    """
    df = scenario['generator'](seed=scenario['seed'])
    lift = _theoretical_lift(scenario['gt'], df, scenario['media_spend_cols'])

    total_budget = df[scenario['media_spend_cols']].sum().sum()
    channel_shares = {
        col.replace('_spend', ''): float(df[col].sum() / total_budget)
        for col in scenario['media_spend_cols']
    }

    assert lift >= LIFT_THEORETICAL_MIN, (
        f'[{scenario["name"]}] Теоретический lift={lift:.1%} < '
        f'LIFT_THEORETICAL_MIN={LIFT_THEORETICAL_MIN:.0%}. '
        f'Субоптимальный сплит не создаёт достаточной разницы в ROI. '
        f'Описание: {scenario["suboptimal_description"]}. '
        f'Текущие доли бюджета: {channel_shares}. '
        f'ROI-таргеты: {scenario["gt"]["roi_targets"]}'
    )


@pytest.mark.parametrize('scenario', SCENARIOS, ids=[s['name'] for s in SCENARIOS])
def test_determinism(scenario):
    """Повторная генерация с тем же seed даёт идентичные данные."""
    df1 = scenario['generator'](seed=scenario['seed'])
    df2 = scenario['generator'](seed=scenario['seed'])

    assert df1.shape == df2.shape, (
        f'[{scenario["name"]}] Размеры не совпадают: {df1.shape} vs {df2.shape}'
    )
    assert list(df1.columns) == list(df2.columns), (
        f'[{scenario["name"]}] Колонки не совпадают'
    )

    # Числовые колонки должны совпадать точно
    numeric_cols = df1.select_dtypes('number').columns
    for col in numeric_cols:
        diff_max = abs(df1[col] - df2[col]).max()
        assert diff_max == 0, (
            f'[{scenario["name"]}] Колонка {col}: максимальная разница = {diff_max} '
            f'(ожидаем 0 при одинаковом seed). Генератор не детерминирован.'
        )


@pytest.mark.parametrize('scenario', SCENARIOS, ids=[s['name'] for s in SCENARIOS])
def test_column_count_and_format(scenario):
    """Файл содержит ожидаемое количество колонок и правильный диапазон дат."""
    df = scenario['generator'](seed=scenario['seed'])

    # Минимум 11 колонок: date + kpi + 4 пары spend/physical + controls
    assert len(df.columns) >= 11, (
        f'[{scenario["name"]}] Слишком мало колонок: {len(df.columns)}. '
        f'Ожидаем ≥11 (date + KPI + 4 пары + controls). Колонки: {list(df.columns)}'
    )

    # 48 строк (4 года месячных данных 2022-01 → 2025-12)
    assert len(df) == 48, (
        f'[{scenario["name"]}] Количество строк = {len(df)}, ожидаем 48.'
    )

    # Дата — первая колонка, datetime-совместимая
    assert 'date' in df.columns, f'[{scenario["name"]}] Нет колонки date'
    dates = pd.to_datetime(df['date'])
    assert dates.min().year == 2022, (
        f'[{scenario["name"]}] Первый год = {dates.min().year}, ожидаем 2022.'
    )
    assert dates.max().year == 2025, (
        f'[{scenario["name"]}] Последний год = {dates.max().year}, ожидаем 2025.'
    )

    # KPI-колонка присутствует и содержит только положительные значения
    kpi_col = scenario['kpi_col']
    assert kpi_col in df.columns, f'[{scenario["name"]}] Нет KPI-колонки {kpi_col}'
    assert (df[kpi_col] > 0).all(), (
        f'[{scenario["name"]}] KPI {kpi_col} содержит нулевые/отрицательные значения'
    )


@pytest.mark.parametrize('scenario', SCENARIOS, ids=[s['name'] for s in SCENARIOS])
def test_spend_columns_positive(scenario):
    """Все spend-колонки содержат только положительные значения."""
    df = scenario['generator'](seed=scenario['seed'])
    for col in scenario['media_spend_cols']:
        assert col in df.columns, f'[{scenario["name"]}] Нет колонки {col}'
        assert (df[col] > 0).all(), (
            f'[{scenario["name"]}] {col} содержит нулевые/отрицательные значения '
            f'(min={df[col].min():.0f}). Флайтинг с полными паузами нарушает prior check.'
        )


@pytest.mark.parametrize('scenario', SCENARIOS, ids=[s['name'] for s in SCENARIOS])
def test_suboptimal_split_high_roi_channel_underweighted(scenario):
    """Канал с наивысшим ROI недофинансирован: его доля бюджета < его ROI-справедливая доля.

    Инвариант субоптимальности: если бы budget распределялся оптимально
    (пропорционально ROI-таргетам), высокий-ROI канал получил бы бо́льшую долю.
    Значит, текущий сплит системно занижает его.

    Гейт: разрыв (roi_fair_share - actual_share) ≥ 5 п.п. (чтобы не флакал).
    Значения для all 4: fmcg ≈22 п.п., otc ≈21 п.п., retail ≈14 п.п., re ≈20 п.п.
    """
    df = scenario['generator'](seed=scenario['seed'])
    gt = scenario['gt']

    channel_order = [col.replace('_spend', '') for col in scenario['media_spend_cols']]
    total_budget = df[scenario['media_spend_cols']].sum().sum()
    channel_shares = {
        ch: float(df[f'{ch}_spend'].sum() / total_budget)
        for ch in channel_order
    }

    roi_items = list(gt['roi_targets'].items())
    best_roi_ch = max(roi_items, key=lambda x: x[1])[0]

    # Оптимальные доли = пропорционально ROI
    roi_vals_arr = np.array([gt['roi_targets'][ch] for ch in channel_order])
    roi_sum = roi_vals_arr.sum()
    roi_fair_shares = {ch: float(gt['roi_targets'][ch] / roi_sum)
                       for ch in channel_order}

    best_actual = channel_shares.get(best_roi_ch, 0.0)
    best_roi_fair = roi_fair_shares.get(best_roi_ch, 0.0)

    # Гейт: actual_share < roi_fair_share - 5 п.п.
    gap = best_roi_fair - best_actual
    assert gap >= 0.05, (
        f'[{scenario["name"]}] Канал с лучшим ROI ({best_roi_ch}, '
        f'ROI={gt["roi_targets"][best_roi_ch]:.1f}×) недофинансирован только на {gap:.1%} '
        f'(< 5 п.п.). Actual={best_actual:.1%}, ROI-fair={best_roi_fair:.1%}. '
        f'Субоптимальный сплит недостаточен. Все доли: {channel_shares}. '
        f'ROI-таргеты: {gt["roi_targets"]}'
    )
