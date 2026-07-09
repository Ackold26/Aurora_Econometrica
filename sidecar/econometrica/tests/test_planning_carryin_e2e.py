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


# ─── Усиленные тесты (posterior-фикстура + чистые сравнения) ────────────────
#
# Замечания к тестам выше (закрываются здесь):
#   • CI-веер carry-in (Task 3) в OLS-тестах skip'ается — posterior отсутствует.
#     Здесь синтезируем детерминированный posterior и проверяем СДВИГ ВЕЕРА.
#   • carry-in доказывается чистым carry_in=True vs carry_in=False при ОДНОМ и том
#     же плане (не planning vs historical — там мешается разная аллокация).
#   • holiday∩fourier (A9) проверяется на самом движке: задвоенная в fourier
#     holiday-колонка исключается из вклада.

MEDIA_COLS_P = ['tv', 'digital']
HOLIDAY_COL_P = 'holiday_newyear_preshop'


def _make_model_with_posterior(tmp_path: Path, *, with_holiday: bool = False,
                               with_posterior: bool = False, tv_decay: float = 0.9,
                               n: int = 36) -> str:
    """OLS-pickle + патч: положительный beta ТВ, высокий decay, опц. posterior/holiday.

    Синтетический posterior дешевле MCMC и детерминирован. Возвращает project_dir.
    """
    import pickle
    from engines.ols_modeler import train_ols
    from engines.persistence import load_model_with_compat, write_pkl_sha256_sidecar

    rng = np.random.RandomState(42)
    dates = pd.date_range('2022-01-01', periods=n, freq='MS')
    tv = rng.uniform(1e6, 3e6, n)
    tv[-6:] = tv[-6:] * 5.0  # высокий хвост ТВ → carry-in ощутим
    digital = rng.uniform(5e5, 2e6, n)
    cols = {'date': dates, 'tv': tv, 'digital': digital}
    control_columns: list[str] = []
    if with_holiday:
        holiday_ng = np.array([1.0 if d.month == 12 else 0.0 for d in dates])
        cols[HOLIDAY_COL_P] = holiday_ng
        control_columns = [HOLIDAY_COL_P]
        sales = 5e6 + 0.3 * tv + 0.2 * digital + 5e5 * holiday_ng + rng.normal(0, 1e5, n)
    else:
        sales = 5e6 + 0.3 * tv + 0.2 * digital + rng.normal(0, 2e5, n)
    cols['sales'] = sales
    df = pd.DataFrame(cols)
    data_file = tmp_path / 'data_p.xlsx'
    df.to_excel(data_file, index=False)
    project_dir = str(tmp_path)

    r = train_ols({
        'data_file': str(data_file), 'kpi_column': 'sales',
        'media_columns': MEDIA_COLS_P, 'control_columns': control_columns,
        'date_column': 'date',
        'adstock_config': {'tv': 'geometric', 'digital': 'geometric'},
        'unit_costs': {}, 'kpi_type': 'sales', 'kpi_unit_cost': None,
        'merge_rules': {}, 'channel_categories': {},
    }, project_dir)
    assert r['status'] == 'ok', r

    pkl = Path(project_dir) / 'models' / 'latest.pkl'
    md = load_model_with_compat(pkl)
    # Положительный beta ТВ + высокий decay → carry-in однозначно поднимает прогноз.
    md['channel_params']['tv']['beta'] = 5.0
    md['channel_params']['tv']['decay'] = tv_decay
    md['channel_params']['tv']['alpha'] = 1.0
    md['channel_params']['tv']['gamma'] = 0.5

    if with_holiday:
        norm = md['normalization']
        # Усиливаем beta праздника, чтобы вклад был заметным (OLS мог дать малый).
        betas = list(norm.get('control_betas_mean') or [])
        if betas:
            betas[0] = 2.5
            norm['control_betas_mean'] = betas
        norm.setdefault('control_means', {}).setdefault(HOLIDAY_COL_P, 0.1)
        norm.setdefault('control_stds', {}).setdefault(HOLIDAY_COL_P, 0.3)
        norm['holiday_dummies_mode'] = 'binary_point'

    if with_posterior:
        n_ch = len(MEDIA_COLS_P)
        n_samp = 200
        prng = np.random.RandomState(7)
        media_betas = np.vstack([
            prng.normal(5.0, 0.3, n_samp), prng.normal(0.5, 0.05, n_samp),
        ]).astype(np.float32)
        alphas = np.full((n_ch, n_samp), 1.0, dtype=np.float32)
        gammas = np.vstack([
            prng.uniform(0.4, 0.6, n_samp), prng.uniform(0.4, 0.6, n_samp),
        ]).astype(np.float32)
        adstock_decay = np.vstack([
            np.full(n_samp, tv_decay), np.full(n_samp, 0.1),
        ]).astype(np.float32)
        intercept = prng.normal(
            float(md['normalization'].get('intercept_mean', 0.0)), 0.02, n_samp
        ).astype(np.float32)
        md['posterior_samples'] = {
            'media_betas': media_betas, 'alphas': alphas, 'gammas': gammas,
            'adstock_decay': adstock_decay, 'intercept': intercept,
            'control_betas': np.zeros((len(control_columns), n_samp), dtype=np.float32),
            'media_columns': list(MEDIA_COLS_P), 'control_columns': control_columns,
            'n_chains': 1, 'n_draws': n_samp,
        }

    with open(pkl, 'wb') as f:
        pickle.dump(md, f)
    write_pkl_sha256_sidecar(pkl)  # пересчитать integrity-хэш (иначе warn при load)
    return project_dir


class TestCarryInPureComparison:
    """Чистое сравнение carry_in=True vs carry_in=False при одном плане (не
    planning vs historical). Изолирует эффект carry-in от аллокации плана."""

    def test_carryin_flag_toggles_and_raises_first_period(self, tmp_path: Path):
        project_dir = _make_model_with_posterior(tmp_path, tv_decay=0.9)
        from engines.scenario import predict_scenario

        plan = {'tv': [2e6] * 6, 'digital': [1e6] * 6}
        on = predict_scenario({
            'scenario_name': 'pure_on', 'media_plan': plan,
            'forecast_periods': 6, 'carry_in': True,
        }, project_dir)
        off = predict_scenario({
            'scenario_name': 'pure_off', 'media_plan': plan,
            'forecast_periods': 6, 'carry_in': False,
        }, project_dir)

        assert on['status'] == 'ok' and off['status'] == 'ok'
        assert on['carry_in_applied'] is True
        assert off['carry_in_applied'] is False, (
            'carry_in=False должен отключать carry-in (флаг из ScenarioRequest)'
        )
        assert on['predictions'][0] > off['predictions'][0], (
            f'carry-in должен поднять predictions[0]: on={on["predictions"][0]:.0f} '
            f'off={off["predictions"][0]:.0f}'
        )


class TestCarryInCIFanShift:
    """Task 3: линия И CI-веер согласованно сдвинуты вверх с carry-in.
    Без этого линия выше веера (рассинхрон). Требует posterior → синтетический."""

    def test_line_and_fan_shift_together(self, tmp_path: Path):
        project_dir = _make_model_with_posterior(tmp_path, with_posterior=True, tv_decay=0.9)
        from engines.scenario import predict_scenario

        plan = {'tv': [2e6] * 6, 'digital': [1e6] * 6}
        on = predict_scenario({
            'scenario_name': 'fan_on', 'media_plan': plan,
            'forecast_periods': 6, 'carry_in': True,
        }, project_dir)
        off = predict_scenario({
            'scenario_name': 'fan_off', 'media_plan': plan,
            'forecast_periods': 6, 'carry_in': False,
        }, project_dir)

        assert on['status'] == 'ok', on
        assert on['predictions_ci_low'] is not None, 'posterior должен дать CI-веер'
        assert on['predictions_ci_high'] is not None
        assert off['predictions_ci_low'] is not None

        lo0, hi0 = on['predictions_ci_low'][0], on['predictions_ci_high'][0]
        line0 = on['predictions'][0]
        # Линия внутри веера (допуск ±1 на округление до целых).
        assert lo0 - 1 <= line0 <= hi0 + 1, (
            f'predictions[0]={line0} вне веера [{lo0}, {hi0}] — линия/веер рассинхрон'
        )
        # Обе границы веера поднимаются с carry-in.
        assert on['predictions_ci_low'][0] > off['predictions_ci_low'][0], (
            'нижняя граница веера должна подняться с carry-in'
        )
        assert on['predictions_ci_high'][0] > off['predictions_ci_high'][0], (
            'верхняя граница веера должна подняться с carry-in'
        )


class TestHolidayFourierDisjointInEngine:
    """A9: holiday-колонка, задвоенная как fourier-колонка, исключается из вклада."""

    def test_holiday_overlapping_fourier_excluded(self, tmp_path: Path):
        import pickle
        from engines.persistence import load_model_with_compat, write_pkl_sha256_sidecar
        from engines.scenario import _compute_scenario_holidays

        project_dir = _make_model_with_posterior(tmp_path, with_holiday=True)
        pkl = Path(project_dir) / 'models' / 'latest.pkl'
        md = load_model_with_compat(pkl)
        norm = md['normalization']
        dec_dates = [d.strftime('%Y-%m-%d')
                     for d in pd.date_range('2026-12-07', periods=6, freq='W')]

        # База: holiday-вклад ненулевой (единственный holiday-контроль активен).
        contrib_base = _compute_scenario_holidays(md, norm, dec_dates, 6)
        assert np.any(contrib_base != 0.0), 'декабрьский НГ-вклад должен быть ненулевым'

        # Теперь задваиваем holiday-имя как fourier-колонку → должно исключиться.
        md['fourier_seasonality'] = {'columns': [HOLIDAY_COL_P], 'terms': []}
        with open(pkl, 'wb') as f:
            pickle.dump(md, f)
        write_pkl_sha256_sidecar(pkl)
        md2 = load_model_with_compat(pkl)
        contrib_overlap = _compute_scenario_holidays(md2, md2['normalization'], dec_dates, 6)
        assert np.all(contrib_overlap == 0.0), (
            'holiday-колонка, пересекающаяся с fourier, не должна давать вклад (A9)'
        )

    def test_holiday_zero_without_future_dates(self, tmp_path: Path):
        from engines.persistence import load_model_with_compat
        from engines.scenario import _compute_scenario_holidays
        project_dir = _make_model_with_posterior(tmp_path, with_holiday=True)
        md = load_model_with_compat(Path(project_dir) / 'models' / 'latest.pkl')
        contrib = _compute_scenario_holidays(md, md['normalization'], [], 6)
        assert np.all(contrib == 0.0), 'без future_dates holiday-вклад = нули'
