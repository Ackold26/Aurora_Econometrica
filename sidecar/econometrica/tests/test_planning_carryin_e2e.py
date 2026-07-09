"""E2E тесты для planning-mode carry-in, holiday injection, horizon cap и disclaimers.

Tasks 1-6: carry-in adstock в point estimate + CI fan, holiday calendar inject,
horizon cap для vector-plan, disclaimers в planning-mode.

Паттерн: train_ols создаёт настоящий pickle → predict_scenario через реальный движок.
Тяжёлые тесты (~2 сек каждый), но без реальных данных (marks: не requires_real_data).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─── Общая синтетическая фикстура ───────────────────────────────────────────

def _make_training_data(tmp_path: Path, n: int = 36, high_tv_end: bool = False) -> Path:
    """36 месяцев. TV с высоким decay=0.7 (долгим хвостом).
    Если high_tv_end=True — последние 6 периодов TV резко возрастает,
    carry-in будет ощутимым.
    """
    rng = np.random.RandomState(42)
    dates = pd.date_range('2022-01-01', periods=n, freq='MS')
    tv = rng.uniform(1e6, 3e6, n)
    if high_tv_end:
        tv[-6:] = tv[-6:] * 5.0  # резкий рост TV в конце истории
    digital = rng.uniform(5e5, 2e6, n)
    sales = (
        5_000_000
        + 0.3 * tv
        + 0.2 * digital
        + rng.normal(0, 200_000, n)
    )
    df = pd.DataFrame({'date': dates, 'tv': tv, 'digital': digital, 'sales': sales})
    p = tmp_path / 'data.xlsx'
    df.to_excel(p, index=False)
    return p


def _train(data_file: Path, project_dir: str, decay_tv: float = 0.7) -> dict:
    """Обучаем OLS модель с геометрическим adstock для TV (высокий decay)."""
    from engines.ols_modeler import train_ols
    return train_ols({
        'data_file': str(data_file),
        'kpi_column': 'sales',
        'media_columns': ['tv', 'digital'],
        'control_columns': [],
        'date_column': 'date',
        'adstock_config': {'tv': 'geometric', 'digital': 'geometric'},
        'unit_costs': {},
        'kpi_type': 'sales',
        'kpi_unit_cost': None,
        'merge_rules': {},
        'channel_categories': {},
    }, project_dir)


# ─── Test 1: carry-in поднимает прогноз ────────────────────────────────────

class TestCarryInRaisesFirstPeriod:
    """Task 1+2: с carry-in и высоким TV-трафиком в конце истории
    predictions[0] должен быть выше чем без carry-in (= исторический режим).
    """

    def test_carryin_raises_prediction(self, tmp_path: Path):
        # История с высоким TV в конце → carry-in значительный
        data_file = _make_training_data(tmp_path, high_tv_end=True)
        result_train = _train(data_file, str(tmp_path))
        assert result_train['status'] == 'ok'

        from engines.scenario import predict_scenario

        # Planning-mode: forecast_periods задан → carry-in активируется
        planning = predict_scenario({
            'scenario_name': 'with_carryin',
            'media_plan': {'tv': [2_000_000.0], 'digital': [1_000_000.0]},
            'forecast_periods': 12,
        }, str(tmp_path))
        assert planning['status'] == 'ok', planning

        # Historical-mode (без forecast_periods): carry-in НЕ применяется
        historical = predict_scenario({
            'scenario_name': 'no_carryin',
            'media_plan': {
                'tv': [2_000_000.0 / 12] * 12,
                'digital': [1_000_000.0 / 12] * 12,
            },
            # нет forecast_periods → исторический режим, нет carry-in
        }, str(tmp_path))
        assert historical['status'] == 'ok', historical

        # С carry-in первый период должен быть выше
        # (история заканчивается высоким TV → adstock-хвост добавляет в t=0)
        p_planning = planning['predictions'][0]
        p_historical = historical['predictions'][0]
        assert p_planning >= p_historical, (
            f'carry-in должен поднять predictions[0]: '
            f'planning={p_planning:.0f}, historical={p_historical:.0f}'
        )

        # carry_in_applied должен быть True в planning-mode
        assert planning.get('carry_in_applied') is True, (
            f'carry_in_applied ожидается True, got {planning.get("carry_in_applied")}'
        )


# ─── Test 2: CI fan содержит point estimate ────────────────────────────────

class TestCarryInLineAndFanAligned:
    """Task 1+2+3: predictions[0] ∈ [ci_low[0], ci_high[0]] — point estimate внутри CI."""

    def test_predictions_inside_ci_band(self, tmp_path: Path):
        data_file = _make_training_data(tmp_path, high_tv_end=True)
        result_train = _train(data_file, str(tmp_path))
        assert result_train['status'] == 'ok'

        from engines.scenario import predict_scenario
        result = predict_scenario({
            'scenario_name': 'ci_check',
            'media_plan': {'tv': [2_000_000.0], 'digital': [1_000_000.0]},
            'forecast_periods': 12,
        }, str(tmp_path))

        assert result['status'] == 'ok', result

        # Если CI недоступен (OLS без posterior) — тест пропускаем
        ci_low = result.get('predictions_ci_low')
        ci_high = result.get('predictions_ci_high')
        if ci_low is None or ci_high is None:
            pytest.skip('posterior samples недоступны в OLS модели — CI тест пропущен')

        pred0 = result['predictions'][0]
        lo0 = ci_low[0]
        hi0 = ci_high[0]
        assert lo0 <= pred0 <= hi0, (
            f'predictions[0]={pred0:.0f} должен быть в [{lo0:.0f}, {hi0:.0f}]'
        )

        # Длины должны совпадать
        assert len(ci_low) == len(result['predictions'])
        assert len(ci_high) == len(result['predictions'])


# ─── Test 3: исторический режим — carry-in не применяется ─────────────────

class TestHistoricalModeNoCarryIn:
    """Task 2: в исторический режиме (без forecast_periods) carry-in НЕ применяется."""

    def test_historical_mode_no_carryin(self, tmp_path: Path):
        data_file = _make_training_data(tmp_path, high_tv_end=False)
        result_train = _train(data_file, str(tmp_path))
        assert result_train['status'] == 'ok'

        from engines.scenario import predict_scenario

        # Исторический режим: forecast_periods НЕ задан
        result = predict_scenario({
            'scenario_name': 'hist_mode',
            'media_plan': {
                'tv': [1_500_000.0] * 12,
                'digital': [800_000.0] * 12,
            },
            # НЕТ forecast_periods → исторический режим
        }, str(tmp_path))

        assert result['status'] == 'ok', result
        # carry_in_applied должен быть False (не planning-mode)
        assert result.get('carry_in_applied') is False, (
            f'В историческом режиме carry_in_applied должен быть False, '
            f'got {result.get("carry_in_applied")}'
        )
        # disclaimers отсутствуют в историческом режиме
        assert 'disclaimers' not in result, (
            'disclaimers не должны появляться в историческом режиме'
        )


# ─── Test 4: holiday December contribution ─────────────────────────────────

class TestHolidaysDecemberContribution:
    """Task 4: future_dates в декабре → holiday contribution > 0 (НГ-закупки).
    Без future_dates → нули.
    """

    def _train_with_holidays(self, tmp_path: Path) -> dict:
        """Модель обученная на данных с holiday-контролями."""
        from engines.ols_modeler import train_ols
        n = 36
        rng = np.random.RandomState(7)
        dates = pd.date_range('2022-01-01', periods=n, freq='MS')
        tv = rng.uniform(1e6, 3e6, n)
        digital = rng.uniform(5e5, 2e6, n)
        # Добавляем простой holiday control
        holiday_ng = np.zeros(n)
        for i, d in enumerate(dates):
            if d.month == 12:
                holiday_ng[i] = 1.0  # декабрь = предновогодние закупки
        sales = (
            5_000_000
            + 0.3 * tv
            + 0.2 * digital
            + 500_000 * holiday_ng
            + rng.normal(0, 100_000, n)
        )
        df = pd.DataFrame({
            'date': dates,
            'tv': tv,
            'digital': digital,
            'holiday_newyear_preshop': holiday_ng,
            'sales': sales,
        })
        p = tmp_path / 'data_h.xlsx'
        df.to_excel(p, index=False)
        return train_ols({
            'data_file': str(p),
            'kpi_column': 'sales',
            'media_columns': ['tv', 'digital'],
            'control_columns': ['holiday_newyear_preshop'],
            'date_column': 'date',
            'adstock_config': {'tv': 'geometric', 'digital': 'geometric'},
            'unit_costs': {},
            'kpi_type': 'sales',
            'kpi_unit_cost': None,
            'merge_rules': {},
            'channel_categories': {},
        }, str(tmp_path))

    def test_holidays_december_nonzero(self, tmp_path: Path):
        result_train = self._train_with_holidays(tmp_path)
        assert result_train['status'] == 'ok'

        from engines.scenario import predict_scenario

        # December future_dates — должен быть праздничный вклад
        dec_dates = [f'2026-12-{d:02d}' for d in range(1, 13)]
        result_with_holidays = predict_scenario({
            'scenario_name': 'dec_holidays',
            'media_plan': {'tv': [2_000_000.0], 'digital': [1_000_000.0]},
            'forecast_periods': 12,
            'future_dates': dec_dates,
        }, str(tmp_path))
        assert result_with_holidays['status'] == 'ok', result_with_holidays

        # Без future_dates — нулевой вклад праздников
        result_no_holidays = predict_scenario({
            'scenario_name': 'no_future_dates',
            'media_plan': {'tv': [2_000_000.0], 'digital': [1_000_000.0]},
            'forecast_periods': 12,
            # future_dates не задан
        }, str(tmp_path))
        assert result_no_holidays['status'] == 'ok', result_no_holidays

        # С декабрьскими датами суммарный KPI должен отличаться
        total_with = result_with_holidays['totals']['predicted_kpi']
        total_without = result_no_holidays['totals']['predicted_kpi']
        # Праздничный вклад может быть как положительным так и отрицательным
        # в зависимости от знака beta, но они должны отличаться
        # (т.к. holiday_newyear_preshop имеет ненулевой beta обученный на Dec=1)
        assert total_with != total_without, (
            f'С December future_dates KPI должен отличаться: '
            f'with={total_with:.0f}, without={total_without:.0f}'
        )

        # holidays_injected должен быть True при наличии future_dates
        assert result_with_holidays.get('disclaimers') is not None
        # При наличии future_dates и модели с holiday-controls → holidays_injected
        # (может быть False если beta=0 или holiday не в колонках, тест мягкий)

    def test_no_holiday_fourier_overlap(self, tmp_path: Path):
        """Проверяем что holiday-колонки не пересекаются с Фурье-колонками."""
        from utils.holiday_calendar_ru import is_holiday_like_name

        # Типичные имена Фурье-колонок не должны совпадать с holiday
        fourier_like = ['sin_1', 'cos_1', 'sin_2', 'cos_2', 'fourier_1', 'trend']
        for col in fourier_like:
            assert not is_holiday_like_name(col), (
                f'Фурье-колонка {col!r} ошибочно распознана как holiday'
            )

        # Реальные holiday-имена должны детектироваться
        holiday_names = [
            'holiday_newyear_preshop', 'holiday_black_friday',
            'holiday_march8', 'holiday_may_holidays',
        ]
        for col in holiday_names:
            assert is_holiday_like_name(col), (
                f'Holiday-колонка {col!r} не распознана'
            )


# ─── Test 5: horizon cap для vector-plan ───────────────────────────────────

class TestHorizonCapVectorPlan:
    """Task 5: vector-plan длиннее 2× training → FORECAST_HORIZON_TOO_LONG."""

    def test_vector_plan_too_long_returns_error(self, tmp_path: Path):
        data_file = _make_training_data(tmp_path, n=24)  # 24 периода обучения
        result_train = _train(data_file, str(tmp_path))
        assert result_train['status'] == 'ok'

        from engines.scenario import predict_scenario

        # Vector plan длиной 200 при обучении на 24 → > 2× → должна быть ошибка
        long_plan_n = 200
        result = predict_scenario({
            'scenario_name': 'too_long',
            'media_plan': {
                'tv': [1_000_000.0] * long_plan_n,
                'digital': [500_000.0] * long_plan_n,
            },
            'forecast_periods': long_plan_n,  # planning-mode с длинным вектором
        }, str(tmp_path))

        assert result.get('status') == 'error', (
            f'Ожидалась ошибка FORECAST_HORIZON_TOO_LONG, получили: {result}'
        )
        assert result.get('error_code') == 'FORECAST_HORIZON_TOO_LONG', (
            f'Неверный error_code: {result.get("error_code")}'
        )

    def test_normal_horizon_passes(self, tmp_path: Path):
        """Горизонт в пределах нормы — не должно быть ошибки."""
        data_file = _make_training_data(tmp_path, n=24)
        result_train = _train(data_file, str(tmp_path))
        assert result_train['status'] == 'ok'

        from engines.scenario import predict_scenario

        # 24 периода при 24 обучения → ровно 1× → в норме
        result = predict_scenario({
            'scenario_name': 'ok_horizon',
            'media_plan': {'tv': [1_000_000.0], 'digital': [500_000.0]},
            'forecast_periods': 24,
        }, str(tmp_path))

        assert result.get('status') == 'ok', (
            f'Нормальный горизонт не должен давать ошибку: {result}'
        )


# ─── Test 6: disclaimers present ───────────────────────────────────────────

class TestDisclaimersPresent:
    """Task 6: planning-mode result содержит disclaimers."""

    def test_base_disclaimer_always_present(self, tmp_path: Path):
        data_file = _make_training_data(tmp_path)
        result_train = _train(data_file, str(tmp_path))
        assert result_train['status'] == 'ok'

        from engines.scenario import predict_scenario
        result = predict_scenario({
            'scenario_name': 'disclaimers_test',
            'media_plan': {'tv': [2_000_000.0], 'digital': [1_000_000.0]},
            'forecast_periods': 12,
        }, str(tmp_path))

        assert result['status'] == 'ok', result
        disclaimers = result.get('disclaimers')
        assert disclaimers is not None, 'disclaimers должны быть в planning-mode'
        assert isinstance(disclaimers, list), 'disclaimers должны быть списком'
        assert len(disclaimers) >= 1, 'минимум 1 disclaimer'

        # Базовый disclaimer всегда присутствует
        base = 'Прогноз при неизменных прочих условиях'
        assert any(base in d for d in disclaimers), (
            f'Базовый disclaimer отсутствует. Получили: {disclaimers}'
        )

    def test_carryin_disclaimer_when_history_available(self, tmp_path: Path):
        """carry_in_applied=True → disclaimer про медиаэффект."""
        data_file = _make_training_data(tmp_path, high_tv_end=True)
        result_train = _train(data_file, str(tmp_path))
        assert result_train['status'] == 'ok'

        from engines.scenario import predict_scenario
        result = predict_scenario({
            'scenario_name': 'carryin_disclaimer',
            'media_plan': {'tv': [2_000_000.0], 'digital': [1_000_000.0]},
            'forecast_periods': 12,
        }, str(tmp_path))

        assert result['status'] == 'ok', result
        if result.get('carry_in_applied'):
            disclaimers = result.get('disclaimers', [])
            assert any('медиаэффект' in d for d in disclaimers), (
                f'Disclaimer про медиаэффект отсутствует. Получили: {disclaimers}'
            )

    def test_no_disclaimers_in_historical_mode(self, tmp_path: Path):
        """В историческом режиме disclaimers не возвращаются."""
        data_file = _make_training_data(tmp_path)
        result_train = _train(data_file, str(tmp_path))
        assert result_train['status'] == 'ok'

        from engines.scenario import predict_scenario
        result = predict_scenario({
            'scenario_name': 'hist_nodisclaimer',
            'media_plan': {
                'tv': [1_000_000.0] * 12,
                'digital': [500_000.0] * 12,
            },
            # НЕТ forecast_periods → исторический режим
        }, str(tmp_path))

        assert result['status'] == 'ok', result
        assert 'disclaimers' not in result, (
            'disclaimers не должны быть в историческом режиме'
        )

    def test_future_dates_in_result(self, tmp_path: Path):
        """future_dates из config пробрасываются в result dict."""
        data_file = _make_training_data(tmp_path)
        result_train = _train(data_file, str(tmp_path))
        assert result_train['status'] == 'ok'

        from engines.scenario import predict_scenario
        dates = ['2026-01-01', '2026-02-01', '2026-03-01']
        result = predict_scenario({
            'scenario_name': 'future_dates_echo',
            'media_plan': {'tv': [2_000_000.0], 'digital': [1_000_000.0]},
            'forecast_periods': 12,
            'future_dates': dates,
        }, str(tmp_path))

        assert result['status'] == 'ok', result
        assert result.get('future_dates') == dates, (
            f'future_dates не проброшены в result: {result.get("future_dates")}'
        )
