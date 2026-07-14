"""
B7 Backtest framework - out-of-sample validation against business reality.

Sprint 1.5 (B7 from audit) - validates Aurora's ROI converges with real business
outcomes (post-campaign sales lift). Hold out last K periods, fit on rest,
predict, compare with actual. Catches "math correct, predictions wrong" failures
that unit tests + SBC + Coverage Probability cannot detect.

Why critical: SBC, Coverage Probability - synthetic-data validation. Real
business test: did Aurora's predicted ROI actually materialize? If model says
"+15% lift" and actual sales lift is +3%, Aurora's math may be technically
correct but practically useless.

Workflow:
1. Load original training dataset (n_obs total)
2. Split: train = first (n_obs - holdout) rows, test = last holdout rows
3. Train model on train subset (Bayesian or OLS based on n)
4. For each test period, predict expected y given media spend
5. Compare predicted vs actual:
   - Out-of-sample R² (ideal: close to in-sample R²)
   - Out-of-sample MAPE
   - Prediction interval coverage (% of actuals within 90% PI)

Acceptance: out-of-sample R² gap from in-sample < 15pp. If gap > 25pp →
overfit warning. Recommended holdout: ~20-30% of total observations
(default 8 periods for monthly data with n=36-50).

Integration (E1 2026-07-03): run_backtest — legacy однооконный примитив
(исторически НЕ был доставлен: endpoint/Rust/UI отсутствовали). Витрина E1 —
run_rolling_backtest ниже: rolling-origin, coverage 90% PI (главная метрика),
наивные бенчмарки, вердикт. Доставка: POST /compute/backtest → econ_backtest
(Rust) → карточка UI + слайд PPTX + narrative.

Math reference: rolling-origin out-of-sample evaluation (общепринятый термин
Hyndman, tscv). Канон честности: Gelman, Bayesian Workflow §9.4 (CV predictive
checking выявляет расхождения, невидимые in-sample PPC); McElreath, Statistical
Rethinking §7.5 (in-sample fit всегда благоволит сложным моделям); Robyn
(Meta 2024, arXiv 2403.14674) — out-of-sample gate как индустриальный стандарт MMM.
"""
from __future__ import annotations

import json
import logging
import pickle
import shutil
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def run_backtest(
    project_dir: str,
    holdout_periods: int = 8,
    mode: str = 'bayesian',
    *,
    use_horseshoe: bool = False,
) -> dict[str, Any]:
    """Run out-of-sample backtest on existing project's data.

    Args:
        project_dir: project with data file + (optional) existing model
        holdout_periods: how many trailing periods to hold out (default 8 = ~6mo monthly)
        mode: 'bayesian' (NUTS, accurate but 3-15min) | 'ols' (closed-form, <1sec)
        use_horseshoe: opt-in sparse priors (only if mode='bayesian')

    Returns:
        dict with:
          - status: 'ok' | 'error'
          - in_sample: {r_squared, mape}
          - out_of_sample: {r_squared, mape, pi_coverage_90}
          - r_squared_gap_pp: in-sample minus out-of-sample (lower = better)
          - verdict: 'reliable' | 'directional' | 'overfit'
          - per_period: list of {date, predicted, actual, residual, pi_low, pi_high}
          - recommendation: human-readable next step
    """
    project_path = Path(project_dir)

    # Find data file
    model_path = project_path / 'models' / 'latest.pkl'
    if not model_path.exists():
        return {
            'status': 'error',
            'error_code': 'NO_MODEL',
            'message': 'Модель не найдена - обучите модель перед backtest',
        }

    # Trust Level 3: централизованный pickle compat helper.
    from engines.persistence import load_model_with_compat
    model_data = load_model_with_compat(model_path)

    config = model_data['config']
    data_file = config['data_file']
    if not Path(data_file).exists():
        return {
            'status': 'error',
            'error_code': 'NO_DATA',
            'message': f'Файл данных не найден: {data_file}',
        }

    # Load data
    if data_file.endswith('.csv'):
        df = pd.read_csv(data_file)
    else:
        df = pd.read_excel(data_file)

    n_obs = len(df)
    if holdout_periods >= n_obs - 4:
        return {
            'status': 'error',
            'error_code': 'HOLDOUT_TOO_LARGE',
            'message': (
                f'holdout_periods={holdout_periods} оставляет {n_obs - holdout_periods} '
                f'обучающих периодов - слишком мало. Уменьшите holdout или соберите больше данных.'
            ),
        }

    # Split: train_df + test_df (forward-chaining)
    train_df = df.iloc[:-holdout_periods].copy()
    test_df = df.iloc[-holdout_periods:].copy()

    # Save train subset to temp file for re-training
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        train_data_file = tmp_path / 'train_subset.xlsx'
        train_df.to_excel(train_data_file, index=False)

        train_project_dir = tmp_path / 'backtest_project'
        train_project_dir.mkdir(parents=True, exist_ok=True)

        # Build train config (same as original, but pointing to subset data)
        train_config = dict(config)
        train_config['data_file'] = str(train_data_file)
        train_config['mode'] = mode
        if use_horseshoe:
            train_config['use_horseshoe'] = True

        # Re-train on subset
        if mode == 'ols':
            from engines.ols_modeler import train_ols as _train
        else:
            from engines.modeler import train_model as _train

        try:
            train_result = _train(train_config, str(train_project_dir))
        except Exception as e:
            return {
                'status': 'error',
                'error_code': 'TRAIN_FAILED',
                'message': f'Re-training на subset failed: {type(e).__name__}: {e}',
            }
        if train_result.get('status') != 'ok':
            return {
                'status': 'error',
                'error_code': 'TRAIN_NOT_OK',
                'message': train_result.get('message') or 'Re-training returned non-ok',
            }

        # Predict on test period via scenario engine (uses retrained model)
        test_media_plan = {
            col: test_df[col].fillna(0).tolist()
            for col in config['media_columns']
        }
        # A3 (carryover через границу окна): forecast_periods активирует planning-режим
        # scenario → adstock-хвост train-окна переносится в первый test-период (carry-in).
        # Test-окно идёт сразу за train → перенос математически точен. Без него первые
        # точки окна занижены → MAPE завышен → несправедливый вердикт worse_than_naive.
        scenario_config = {
            'scenario_name': 'backtest_holdout',
            'media_plan': test_media_plan,
            'unit_costs': config.get('unit_costs', {}),
            'forecast_periods': len(test_df),
        }
        from engines.scenario import predict_scenario
        sc = predict_scenario(scenario_config, str(train_project_dir))
        if sc.get('status') != 'ok':
            return {
                'status': 'error',
                'error_code': 'PREDICT_FAILED',
                'message': sc.get('message') or 'Scenario prediction on holdout failed',
            }

    # Compare predicted vs actual on test period
    kpi_col = config['kpi_column']
    actual = test_df[kpi_col].values.astype(float)
    predicted = np.array(sc['predictions'][:len(actual)])

    # Out-of-sample metrics
    residuals = actual - predicted
    ss_res_oos = float(np.sum(residuals ** 2))
    ss_tot_oos = float(np.sum((actual - actual.mean()) ** 2)) if len(actual) > 1 else 1.0
    r2_oos = max(-1.0, 1.0 - ss_res_oos / max(ss_tot_oos, 1e-10))
    mape_oos = float(np.mean(np.abs(residuals / np.maximum(np.abs(actual), 1e-10))) * 100)

    # Prediction interval coverage (if scenario provided CI)
    pi_low_arr = np.full(len(actual), np.nan)
    pi_high_arr = np.full(len(actual), np.nan)
    pi_coverage = None
    # Scenario doesn't return per-period PI (only totals). For per-period coverage,
    # we'd need to re-fit + propagate full posterior - defer to A4 polish.
    # For now: report None, UI shows 'PI coverage недоступна (требует full posterior propagation per period)'.

    # In-sample metrics from re-trained model
    in_diag = train_result.get('diagnostics', {}).get('metrics', {})
    r2_in = float(in_diag.get('r_squared', 0))
    mape_in = float(in_diag.get('mape', 0))

    r2_gap_pp = (r2_in - r2_oos) * 100

    # Verdict
    if r2_gap_pp < 15:
        verdict = 'reliable'
        rec = (
            f'Out-of-sample R² {r2_oos:.3f} близко к in-sample {r2_in:.3f} '
            f'(gap {r2_gap_pp:+.1f}пп). Модель обобщает на новые данные - результаты '
            f'можно использовать для бизнес-решений.'
        )
    elif r2_gap_pp < 25:
        verdict = 'directional'
        rec = (
            f'Out-of-sample R² {r2_oos:.3f} ниже in-sample {r2_in:.3f} на '
            f'{r2_gap_pp:.1f}пп. Модель частично переобучена - используйте результаты '
            f'как направление, не точную оценку. Соберите больше данных или попробуйте '
            f'horseshoe-приоры (Sprint 2 / A3).'
        )
    else:
        verdict = 'overfit'
        rec = (
            f'Out-of-sample R² {r2_oos:.3f} сильно ниже in-sample {r2_in:.3f} '
            f'(gap {r2_gap_pp:.1f}пп) - модель переобучена и не обобщает. '
            f'Не используйте текущие оценки ROI для бизнес-решений. Рекомендации: '
            f'соберите больше данных, упростите медиа-микс, или используйте OLS-режим '
            f'с frequentist CI (стабильнее на small N).'
        )

    return {
        'status': 'ok',
        'holdout_periods': holdout_periods,
        'train_periods': n_obs - holdout_periods,
        'mode': mode,
        'in_sample': {
            'r_squared': round(r2_in, 4),
            'mape': round(mape_in, 2),
        },
        'out_of_sample': {
            'r_squared': round(r2_oos, 4),
            'mape': round(mape_oos, 2),
            'pi_coverage_90': pi_coverage,
        },
        'r_squared_gap_pp': round(r2_gap_pp, 1),
        'verdict': verdict,
        'per_period': [
            {
                'period': i + 1,
                'predicted': round(float(predicted[i]), 2),
                'actual': round(float(actual[i]), 2),
                'residual': round(float(residuals[i]), 2),
                'residual_pct': round(float(residuals[i] / max(abs(actual[i]), 1e-10)) * 100, 2),
            }
            for i in range(len(actual))
        ],
        'recommendation': rec,
    }


# ═══════════════════════════════════════════════════════════════════════════
# E1 Backtest-витрина (ROADMAP v3, 2026-07-03) — rolling-origin «модель vs факт»
# ═══════════════════════════════════════════════════════════════════════════
#
# Отличия от legacy run_backtest выше:
# - k СКОЛЬЗИТ (несколько окон-«кварталов» без нахлёста), не один holdout;
# - главная метрика — coverage 90% PI (попадание факта в интервал), в двух
#   разрезах: per-period (канон) и per-window «квартальный тотал в интервале
#   суммы» (язык клиента: «7 из 8 кварталов»);
# - наивные бенчмарки (naive-last, seasonal-naive) — модель обязана бить
#   лучший из них, иначе вердикт честно говорит worse_than_naive;
# - при N окон < 3 — честный status='insufficient' («истории недостаточно»),
#   никаких оценок на пустоте;
# - результат сохраняется атомарно в models/backtest.json (витрину читают
#   UI/PPTX/narrative; при отсутствии файла слайд НЕ рисуется — без wireframe).

# Квартал в терминах гранулярности данных (detect_granularity из
# utils/forecast_validation.py). Для квартальных данных окно = 2 точки
# (1 точка не даёт осмысленного MAPE/coverage разреза), для годовых — 1.
_H_QUARTER_BY_GRANULARITY: dict[str, int] = {'D': 90, 'W': 13, 'M': 3, 'Q': 2, 'Y': 1}
# Сезон (полный цикл) в точках — для seasonal-naive.
_SEASON_BY_GRANULARITY: dict[str, int] = {'D': 7, 'W': 52, 'M': 12, 'Q': 4, 'Y': 0}

#: Порог per-period coverage для вердикта. Номинал 90%; при 9–15 holdout-точках
#: биномиальный разброс велик, поэтому граница тревоги консервативно 0.70
#: (P(обс. coverage ≤ 0.70 | истинное 0.90, n=12) ≈ 3% — ложная тревога редка).
_COVERAGE_ALERT_THRESHOLD = 0.70

_MIN_WINDOWS = 3          # меньше — «истории недостаточно для проверки»
_MIN_TRAIN_BAYESIAN = 20  # канон recommend_engine: n<20 → Bayesian не рекомендован
_MIN_TRAIN_OLS = 12       # OLS формально живёт с n≥8, но 12 держит запас dof


def _plan_windows(
    n_obs: int, h: int, min_train: int, max_windows: int,
) -> list[tuple[int, int]]:
    """Окна rolling-origin без нахлёста: [(test_start, test_end), ...].

    Идём от свежего края назад с шагом h, пока train-часть ≥ min_train;
    возвращаем в хронологическом порядке. Обучение окна — строки [0..test_start).
    """
    windows: list[tuple[int, int]] = []
    test_end = n_obs
    while len(windows) < max_windows:
        test_start = test_end - h
        if test_start < min_train:
            break
        windows.append((test_start, test_end))
        test_end = test_start
    windows.reverse()
    return windows


def _naive_forecasts(y_train: np.ndarray, h: int, season: int) -> dict[str, list[float]]:
    """Наивные бенчмарки: random-walk (последнее значение) + сезонный (значение
    сезон назад), когда истории хватает. Оба — общепринятая нижняя планка
    полезности прогноза (Hyndman; Robyn ts_validation)."""
    out: dict[str, list[float]] = {
        'naive_last': [float(y_train[-1])] * h,
    }
    if season > 0 and len(y_train) >= season and h <= season:
        base = len(y_train) - season
        out['seasonal_naive'] = [float(y_train[base + i]) for i in range(h)]
    return out


def _mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """MAPE %, защита от нулевых фактов знаменателем ≥ 1e-10."""
    a = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    return float(np.mean(np.abs((a - p) / np.maximum(np.abs(a), 1e-10))) * 100)


def _widen_pi_with_noise(
    predictions: list[float],
    ci_low: list[float],
    ci_high: list[float],
    noise_half_width: float,
) -> tuple[list[float], list[float]]:
    """Расширить интервал СРЕДНЕЙ до ПРЕДИКТИВНОГО квадратурой (гауссово
    приближение): hw_pred = √(hw_mean² + hw_noise²) на каждый период.

    Найдено живым Kagocel-зондом E1-5: HDI сценария — неопределённость
    ПАРАМЕТРОВ (средней прогноза); факт же содержит шум наблюдения ε_t.
    Coverage против интервала средней систематически проваливается даже у
    честной модели (Kagocel: 0/9 при ширине ±5% и сезонных остатках).
    Канон — posterior predictive (Gelman BW): var_pred = var_mean + σ².
    """
    lo, hi = [], []
    for p, l, h in zip(predictions, ci_low, ci_high):
        hw_lo = max(float(p) - float(l), 0.0)
        hw_hi = max(float(h) - float(p), 0.0)
        lo.append(float(p) - float(np.sqrt(hw_lo ** 2 + noise_half_width ** 2)))
        hi.append(float(p) + float(np.sqrt(hw_hi ** 2 + noise_half_width ** 2)))
    return lo, hi


def _rolling_verdict(
    coverage_per_period: float | None,
    mape_model: float,
    mape_naive_best: float | None,
) -> tuple[str, str]:
    """Вердикт витрины + русский текст. Приоритет: проигрыш наивному (бинарная
    планка полезности) → слабое покрытие (интервалы самоуверенны) → validated."""
    if mape_naive_best is not None and mape_model >= mape_naive_best:
        return 'worse_than_naive', (
            f'Модель на удержанной истории точна как наивный прогноз или хуже '
            f'(MAPE модели {mape_model:.1f}% против {mape_naive_best:.1f}% у наивного). '
            f'Полагаться на прогнозы модели пока нельзя: соберите больше данных '
            f'или упростите медиа-микс.'
        )
    if coverage_per_period is not None and coverage_per_period < _COVERAGE_ALERT_THRESHOLD:
        return 'coverage_low', (
            f'Факт попадает в 90%-интервал модели лишь в {coverage_per_period * 100:.0f}% '
            f'периодов (норма ≈ 90%). Интервалы модели самоуверенны — реальная '
            f'неопределённость выше заявленной. Точечная точность: MAPE {mape_model:.1f}%.'
        )
    beat = ''
    if mape_naive_best is not None:
        gain = (1 - mape_model / max(mape_naive_best, 1e-10)) * 100
        beat = f' Модель точнее наивного прогноза на {gain:.0f}%.'
    cov_txt = ''
    if coverage_per_period is not None:
        cov_txt = f' Покрытие 90%-интервала: {coverage_per_period * 100:.0f}% периодов.'
    return 'validated', (
        f'Модель подтверждена на удержанной истории: MAPE {mape_model:.1f}%.'
        f'{beat}{cov_txt}'
    )


def _save_backtest_json(project_dir: Path, result: dict[str, Any]) -> str:
    """Атомарная запись models/backtest.json (tmp → fsync → replace)."""
    import os
    models_dir = project_dir / 'models'
    models_dir.mkdir(parents=True, exist_ok=True)
    target = models_dir / 'backtest.json'
    tmp = models_dir / 'backtest.json.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)
    return str(target)


def load_saved_backtest(project_dir: str) -> dict[str, Any] | None:
    """Прочитать сохранённую витрину (models/backtest.json) или None.

    Битый JSON честно возвращается как None (витрина «не проводилась») с логом —
    лучше пустая карточка, чем краш отчёта. Дописывает model_trained_at_current
    (свежий mtime latest.pkl): UI сравнивает с model_trained_at витрины и честно
    помечает «модель переобучена после проверки — обновите».
    """
    p = Path(project_dir) / 'models' / 'backtest.json'
    if not p.exists():
        return None
    try:
        with open(p, encoding='utf-8') as f:
            saved = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning('backtest.json повреждён (%s) — витрина считается непроведённой', e)
        return None
    model_path = Path(project_dir) / 'models' / 'latest.pkl'
    if model_path.exists():
        from datetime import datetime, timezone
        saved['model_trained_at_current'] = datetime.fromtimestamp(
            model_path.stat().st_mtime, tz=timezone.utc
        ).isoformat(timespec='seconds')
    return saved


def run_rolling_backtest(
    project_dir: str,
    horizon_periods: int | None = None,
    min_train: int | None = None,
    mode: str = 'auto',
    max_windows: int = 8,
    save: bool = True,
) -> dict[str, Any]:
    """E1: rolling-origin проверка модели на истории («модель vs факт»).

    Механика: k скользит от свежего края назад с шагом h (квартал в терминах
    гранулярности данных); для каждого окна модель ПЕРЕОБУЧАЕТСЯ на [0..k) и
    предсказывает [k..k+h) против факта. Никакого in-sample: обучение окна
    не видит будущего (канон Gelman BW §9.4, McElreath §7.5 — см. шапку модуля).

    Args:
        project_dir: проект с models/latest.pkl (config → data_file).
        horizon_periods: длина окна прогноза; None → «квартал» по гранулярности
            (M→3, W→13, D→90, Q→2, Y→1).
        min_train: минимум обучающих точек; None → 20 (bayesian) / 12 (OLS).
        mode: 'auto' — как обучена модель (по наличию posterior), 'bayesian'|'ols'.
        max_windows: потолок числа окон (время: bayesian-окно ≈ время обучения).
        save: писать результат в models/backtest.json (atomic).

    Returns:
        status='ok': granularity, horizon_periods, n_windows, coverage
        per-period/per-window, mape модели и наивных, verdict + verdict_text,
        windows[] (период, факт, прогноз, интервал, попадание, per-period detail),
        method (rolling_origin, pi_method, naive), generated_at, model_trained_at.
        status='insufficient': честное «истории недостаточно» (n_windows_possible).
        status='error': NO_MODEL / NO_DATA / DATE_COLUMN_MISSING / ALL_WINDOWS_FAILED.
    """
    from datetime import datetime, timezone

    project_path = Path(project_dir)
    model_path = project_path / 'models' / 'latest.pkl'
    if not model_path.exists():
        return {
            'status': 'error',
            'error_code': 'NO_MODEL',
            'message': 'Модель не найдена — обучите модель перед проверкой на истории.',
        }

    from engines.persistence import load_model_with_compat
    from utils.posterior_propagation import load_posterior_samples
    model_data = load_model_with_compat(model_path)
    config = model_data['config']

    # Режим окон: как обучена модель (posterior есть → bayesian), либо явный.
    if mode == 'auto':
        has_posterior = False
        try:
            has_posterior = load_posterior_samples(model_data) is not None
        except Exception:  # noqa: BLE001 — legacy pickle без samples = OLS-путь
            has_posterior = False
        mode_resolved = 'bayesian' if has_posterior else 'ols'
    else:
        mode_resolved = mode

    if min_train is None:
        min_train = _MIN_TRAIN_BAYESIAN if mode_resolved == 'bayesian' else _MIN_TRAIN_OLS
    # Нижняя планка по числу параметров: OLS требует n > p+1 (intercept+медиа+контролы).
    n_params = 1 + len(config.get('media_columns', [])) + len(config.get('control_columns', []) or [])
    min_train = max(int(min_train), n_params + 2)

    # Данные: живой путь или фолбэк в каталог проекта (C3-N3 резолвер).
    from utils.data_file_resolver import resolve_data_file
    try:
        data_path = resolve_data_file(config.get('data_file'), project_dir)
    except FileNotFoundError as e:
        return {'status': 'error', 'error_code': 'NO_DATA', 'message': str(e)}

    if str(data_path).endswith('.csv'):
        df = pd.read_csv(data_path)
    else:
        df = pd.read_excel(data_path)
    # Правила слияния колонок применялись при обучении — повторить, чтобы
    # медиа-колонки конфига существовали в df (иначе KeyError на планах окон).
    merge_rules = config.get('merge_rules')
    if merge_rules:
        try:
            from utils.merge_rules import apply_merge_rules
            apply_merge_rules(df, merge_rules)
        except Exception as e:  # noqa: BLE001 — честная ошибка вместо KeyError глубже
            return {
                'status': 'error',
                'error_code': 'MERGE_RULES_FAILED',
                'message': f'Не удалось применить правила слияния колонок: {e}',
            }

    kpi_col = config['kpi_column']
    # NaN-KPI row filter: drop media-plan tail so rolling windows only slice history.
    # Invariant: если хвоста нет — notna() для всех строк → no-op.
    if kpi_col in df.columns:
        df = df[df[kpi_col].notna()].reset_index(drop=True)
    media_cols = config['media_columns']
    date_col = config.get('date_column', 'date')
    if kpi_col not in df.columns:
        return {
            'status': 'error',
            'error_code': 'NO_DATA',
            'message': f'В файле данных нет колонки KPI «{kpi_col}» — файл изменился после обучения.',
        }
    missing_media = [c for c in media_cols if c not in df.columns]
    if missing_media:
        return {
            'status': 'error',
            'error_code': 'NO_DATA',
            'message': (
                f'В файле данных нет медиа-колонок: {", ".join(missing_media)} — '
                f'файл изменился после обучения.'
            ),
        }

    n_obs = len(df)

    # Гранулярность → h (квартал) и сезон. Дефолт при слабой уверенности — M.
    from utils.forecast_validation import detect_granularity
    granularity = 'M'
    granularity_note = None
    if date_col in df.columns:
        g = detect_granularity(df[date_col])
        if g['confidence'] >= 0.6:
            granularity = g['granularity']
        else:
            granularity_note = (
                f'Гранулярность данных определена неуверенно '
                f'(confidence {g["confidence"]:.2f}) — принят месячный шаг.'
            )
    else:
        granularity_note = f'Колонка дат «{date_col}» не найдена — принят месячный шаг.'

    h = int(horizon_periods) if horizon_periods else _H_QUARTER_BY_GRANULARITY[granularity]
    season = _SEASON_BY_GRANULARITY.get(granularity, 0)

    windows = _plan_windows(n_obs, h, min_train, max_windows)
    n_possible = len(windows)
    if n_possible < _MIN_WINDOWS:
        return {
            'status': 'insufficient',
            'message': (
                f'Истории недостаточно для проверки: наблюдений {n_obs}, '
                f'окно прогноза {h}, минимум обучения {min_train} → окон {n_possible} '
                f'(нужно ≥ {_MIN_WINDOWS}). Соберите больше истории — проверка '
                f'станет доступна автоматически.'
            ),
            'n_obs': n_obs,
            'horizon_periods': h,
            'min_train': min_train,
            'n_windows_possible': n_possible,
            'granularity': granularity,
        }

    # Даты для подписей окон (если колонки нет — порядковые номера).
    date_labels: list[str] | None = None
    if date_col in df.columns:
        try:
            dts = pd.to_datetime(df[date_col])
            date_labels = [d.strftime('%Y-%m-%d') for d in dts]
        except Exception:  # noqa: BLE001 — подписи не должны ронять проверку
            date_labels = None

    if mode_resolved == 'ols':
        from engines.ols_modeler import train_ols as _train
    else:
        from engines.modeler import train_model as _train
    from engines.scenario import predict_scenario

    window_results: list[dict[str, Any]] = []
    failed_windows: list[dict[str, Any]] = []
    all_hits: list[bool] = []
    all_actual: list[float] = []
    all_predicted: list[float] = []
    naive_abs_pct_errors: dict[str, list[float]] = {}
    pi_method: str | None = None

    y_full = df[kpi_col].fillna(0).to_numpy(dtype=float)

    for (test_start, test_end) in windows:
        window_label = (
            f'{date_labels[test_start]} — {date_labels[test_end - 1]}'
            if date_labels else f'периоды {test_start + 1}–{test_end}'
        )
        train_df = df.iloc[:test_start].copy()
        test_df = df.iloc[test_start:test_end].copy()
        actual = test_df[kpi_col].fillna(0).to_numpy(dtype=float)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            train_data_file = tmp_path / 'train_subset.xlsx'
            train_df.to_excel(train_data_file, index=False)
            train_project_dir = tmp_path / 'bt_window'
            train_project_dir.mkdir(parents=True, exist_ok=True)

            train_config = dict(config)
            train_config['data_file'] = str(train_data_file)
            train_config['mode'] = mode_resolved
            # merge_rules уже применены к df выше — subset сохранён в слитом
            # виде, повторное применение при обучении окна не нужно.
            train_config['merge_rules'] = {}

            try:
                train_result = _train(train_config, str(train_project_dir))
            except Exception as e:  # noqa: BLE001 — окно умирает, проверка живёт
                failed_windows.append({
                    'window': window_label,
                    'error_code': 'WINDOW_TRAIN_FAILED',
                    'message': f'{type(e).__name__}: {e}',
                })
                continue
            if train_result.get('status') != 'ok':
                failed_windows.append({
                    'window': window_label,
                    'error_code': 'WINDOW_TRAIN_NOT_OK',
                    'message': train_result.get('message') or 'обучение окна вернуло не-ok',
                })
                continue

            test_media_plan = {
                col: test_df[col].fillna(0).tolist() for col in media_cols
            }
            sc = predict_scenario(
                {
                    'scenario_name': f'backtest_{window_label}',
                    'media_plan': test_media_plan,
                    'unit_costs': config.get('unit_costs', {}),
                    # A3: carry-in adstock-хвоста train-окна в test-окно (см. holdout выше).
                    'forecast_periods': len(test_df),
                },
                str(train_project_dir),
            )
            if sc.get('status') != 'ok':
                failed_windows.append({
                    'window': window_label,
                    'error_code': 'WINDOW_PREDICT_FAILED',
                    'message': sc.get('message') or 'прогноз окна вернул не-ok',
                })
                continue

            predictions = [float(v) for v in (sc.get('predictions') or [])]
            if len(predictions) < len(actual):
                # F-E1-3: короткий prediction → не тихий broadcast-краш, а честное окно-ошибка.
                failed_windows.append({
                    'window': window_label,
                    'error_code': 'WINDOW_PREDICT_SHORT',
                    'message': (
                        f'Прогноз вернул {len(predictions)} точек при {len(actual)} фактических.'
                    ),
                })
                continue
            predictions = predictions[:len(actual)]

            # PI per-period: bayesian → 90% HDI веер сценария; OLS → conformal
            # half-width (90%, norm-шкала × y_std) вокруг точки.
            ci_low = sc.get('predictions_ci_low')
            ci_high = sc.get('predictions_ci_high')
            window_pi_method = None
            if ci_low and ci_high and len(ci_low) >= len(actual):
                ci_low = [float(v) for v in ci_low[:len(actual)]]
                ci_high = [float(v) for v in ci_high[:len(actual)]]
                total_pi = (
                    sc.get('totals', {}).get('predicted_kpi_ci_low'),
                    sc.get('totals', {}).get('predicted_kpi_ci_high'),
                )
                # E1-5 fix (живой Kagocel-зонд): HDI сценария — интервал СРЕДНЕЙ;
                # для coverage нужен ПРЕДИКТИВНЫЙ (⊕ шум наблюдения ε_t, канон
                # posterior predictive — Gelman BW). σ ≈ in-sample RMSE окна
                # (native; слегка занижен — честно подписано методом; точный
                # путь — sigma-samples в pickle, кандидат E3).
                _metrics_win = (train_result.get('diagnostics') or {}).get('metrics') or {}
                _rmse_win = _metrics_win.get('rmse')
                if _rmse_win:
                    _noise_hw = 1.645 * float(_rmse_win)
                    ci_low, ci_high = _widen_pi_with_noise(
                        predictions, ci_low, ci_high, _noise_hw,
                    )
                    if total_pi[0] is not None and total_pi[1] is not None:
                        _pt = float(sum(predictions))
                        _hw_lo_t = max(_pt - float(total_pi[0]), 0.0)
                        _hw_hi_t = max(float(total_pi[1]) - _pt, 0.0)
                        _noise_t = _noise_hw * float(np.sqrt(len(actual)))
                        total_pi = (
                            _pt - float(np.sqrt(_hw_lo_t ** 2 + _noise_t ** 2)),
                            _pt + float(np.sqrt(_hw_hi_t ** 2 + _noise_t ** 2)),
                        )
                    window_pi_method = 'posterior_predictive_90'
                else:
                    # RMSE окна недоступен — честно называем интервал средней.
                    window_pi_method = 'posterior_hdi_90_mean_only'
            else:
                half_width_native = None
                conf = (train_result.get('diagnostics') or {}).get('conformal_pi') or {}
                hw_norm = conf.get('half_width')
                if hw_norm is not None:
                    try:
                        win_model = load_model_with_compat(
                            train_project_dir / 'models' / 'latest.pkl'
                        )
                        y_std_win = float(win_model['normalization']['y_std'])
                        half_width_native = float(hw_norm) * y_std_win
                        window_pi_method = 'conformal_90'
                    except Exception:  # noqa: BLE001
                        half_width_native = None
                if half_width_native is None:
                    metrics = (train_result.get('diagnostics') or {}).get('metrics') or {}
                    rs = metrics.get('residual_std')
                    if rs is not None:
                        # Гауссово приближение: z(90%) = 1.645. Честно подписано.
                        half_width_native = 1.645 * float(rs)
                        window_pi_method = 'residual_z90'
                if half_width_native is not None:
                    ci_low = [p - half_width_native for p in predictions]
                    ci_high = [p + half_width_native for p in predictions]
                    # Тотал окна: сумма h независимых ошибок → ширина × √h.
                    total_pi = (
                        sum(predictions) - half_width_native * float(np.sqrt(len(actual))),
                        sum(predictions) + half_width_native * float(np.sqrt(len(actual))),
                    )
                else:
                    ci_low = ci_high = None
                    total_pi = (None, None)
            if pi_method is None and window_pi_method is not None:
                pi_method = window_pi_method

        # ── вне tempdir: только арифметика на уже вынутых значениях ──
        per_period = []
        window_hits: list[bool] = []
        for i in range(len(actual)):
            hit = None
            if ci_low is not None and ci_high is not None:
                hit = bool(ci_low[i] <= actual[i] <= ci_high[i])
                window_hits.append(hit)
                all_hits.append(hit)
            per_period.append({
                'date': date_labels[test_start + i] if date_labels else None,
                'actual': round(float(actual[i]), 2),
                'predicted': round(float(predictions[i]), 2),
                'pi_low': round(float(ci_low[i]), 2) if ci_low is not None else None,
                'pi_high': round(float(ci_high[i]), 2) if ci_high is not None else None,
                'hit': hit,
            })
        all_actual.extend(actual.tolist())
        all_predicted.extend(predictions)

        # Наивные бенчмарки этого окна (по train-части ряда).
        y_train_win = y_full[:test_start]
        for name, forecast in _naive_forecasts(y_train_win, len(actual), season).items():
            errs = (
                np.abs((actual - np.asarray(forecast)) / np.maximum(np.abs(actual), 1e-10)) * 100
            )
            naive_abs_pct_errors.setdefault(name, []).extend([float(e) for e in errs])

        actual_total = float(actual.sum())
        predicted_total = float(sum(predictions))
        total_hit = None
        if total_pi[0] is not None and total_pi[1] is not None:
            total_hit = bool(float(total_pi[0]) <= actual_total <= float(total_pi[1]))
        window_results.append({
            'window': window_label,
            'train_periods': int(test_start),
            'test_periods': int(len(actual)),
            'actual_total': round(actual_total, 2),
            'predicted_total': round(predicted_total, 2),
            'pi_low_total': round(float(total_pi[0]), 2) if total_pi[0] is not None else None,
            'pi_high_total': round(float(total_pi[1]), 2) if total_pi[1] is not None else None,
            'hit_total': total_hit,
            'mape': round(_mape(actual, np.asarray(predictions)), 2),
            'per_period': per_period,
        })

    if not window_results:
        return {
            'status': 'error',
            'error_code': 'ALL_WINDOWS_FAILED',
            'message': (
                'Ни одно окно проверки не удалось обучить/спрогнозировать. '
                'Подробности по окнам — в failed_windows.'
            ),
            'failed_windows': failed_windows,
        }
    if len(window_results) < _MIN_WINDOWS:
        return {
            'status': 'insufficient',
            'message': (
                f'Удалось проверить только {len(window_results)} окна(о) из '
                f'{n_possible} (нужно ≥ {_MIN_WINDOWS}) — часть окон завершилась '
                f'ошибкой. Проверка на истории неубедительна.'
            ),
            'n_windows_possible': n_possible,
            'n_windows_ok': len(window_results),
            'failed_windows': failed_windows,
            'granularity': granularity,
            'horizon_periods': h,
        }

    # ── агрегаты ──
    coverage_per_period = (
        float(np.mean(all_hits)) if all_hits else None
    )
    windows_with_total = [w for w in window_results if w['hit_total'] is not None]
    coverage_per_window = (
        float(np.mean([w['hit_total'] for w in windows_with_total]))
        if windows_with_total else None
    )
    mape_model = _mape(np.asarray(all_actual), np.asarray(all_predicted))
    naive_mape = {
        name: round(float(np.mean(errs)), 2)
        for name, errs in naive_abs_pct_errors.items() if errs
    }
    mape_naive_best = min(naive_mape.values()) if naive_mape else None
    naive_best_name = (
        min(naive_mape, key=naive_mape.get) if naive_mape else None
    )

    verdict, verdict_text = _rolling_verdict(coverage_per_period, mape_model, mape_naive_best)

    result: dict[str, Any] = {
        'status': 'ok',
        'verdict': verdict,
        'verdict_text': verdict_text,
        'granularity': granularity,
        'granularity_note': granularity_note,
        'horizon_periods': h,
        'min_train': min_train,
        'mode': mode_resolved,
        'n_windows': len(window_results),
        'n_windows_possible': n_possible,
        'windows_hit_total': (
            int(sum(1 for w in windows_with_total if w['hit_total']))
            if windows_with_total else None
        ),
        'windows_with_interval': len(windows_with_total),
        'coverage_per_window': (
            round(coverage_per_window, 4) if coverage_per_window is not None else None
        ),
        'coverage_per_period': (
            round(coverage_per_period, 4) if coverage_per_period is not None else None
        ),
        'n_holdout_points': len(all_actual),
        'n_holdout_points_with_interval': len(all_hits),
        'mape_model': round(mape_model, 2),
        'naive_mape': naive_mape,
        'mape_naive_best': mape_naive_best,
        'naive_best_name': naive_best_name,
        'pi_method': pi_method,
        'pi_level': 0.9 if pi_method else None,
        'windows': window_results,
        'failed_windows': failed_windows,
        'method': (
            'rolling_origin: обучение на [1..k), прогноз [k..k+h) против факта, '
            'k скользит без нахлёста; out-of-sample (Gelman BW §9.4, McElreath §7.5, '
            'Robyn 2024)'
        ),
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'model_trained_at': datetime.fromtimestamp(
            model_path.stat().st_mtime, tz=timezone.utc
        ).isoformat(timespec='seconds'),
        'n_obs': n_obs,
    }
    if save:
        try:
            result['saved_to'] = _save_backtest_json(project_path, result)
        except OSError as e:
            result['saved_to'] = None
            result['save_error'] = f'Не удалось сохранить backtest.json: {e}'
    return result
