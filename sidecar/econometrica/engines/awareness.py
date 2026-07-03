"""
Awareness forecasting engine.
Models media → awareness relationship + S-curve awareness → sales.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Any
from scipy.optimize import curve_fit


def s_curve(x: np.ndarray, L: float, k: float, x0: float) -> np.ndarray:
    """Logistic S-curve: models awareness → sales relationship.

    Args:
        x: Awareness level (0-100%)
        L: Maximum effect (saturation ceiling)
        k: Steepness (how fast effect grows)
        x0: Midpoint (awareness level at 50% of max effect)
    """
    return L / (1 + np.exp(-k * (x - x0)))


# A5/OPP-07 (2026-07-03): наклон ESOV→рост SOM. Binet & Field («The Long and
# the Short of It», Fig. 31–32): кампании digital-эры дают ≈0.05 пп годового
# роста доли рынка на 1 пп избыточной доли голоса (до 2002 — ≈0.03); в
# методичке кабинета — диапазон 0.05–0.07. Отдаём точку 0.05 + диапазон.
ESOV_SLOPE_POINT = 0.05
ESOV_SLOPE_RANGE = (0.05, 0.07)


def _find_col(df: 'pd.DataFrame', needle: str) -> str | None:
    """Колонка, чьё имя содержит needle (без регистра); None если нет."""
    for c in df.columns:
        if needle.lower() in str(c).lower():
            return c
    return None


def _esov_module(df: 'pd.DataFrame', config: dict) -> dict[str, Any] | None:
    """ESOV-анализ (Binet & Field) — только при живых SOV/SOM колонках.

    Возвращает None, когда данных нет или они не похожи на доли (канон
    кабинета: «иначе пропустить ESOV-модуль» — модуль не выдумывает).
    """
    sov_col = config.get('sov_column') or _find_col(df, 'sov')
    som_col = config.get('som_column') or _find_col(df, 'som')
    if not sov_col or not som_col:
        return None
    sov = pd.to_numeric(df[sov_col], errors='coerce').dropna().astype(float)
    som = pd.to_numeric(df[som_col], errors='coerce').dropna().astype(float)
    if len(sov) < 4 or len(som) < 4:
        return None

    def _to_pct(s: 'pd.Series') -> 'pd.Series | None':
        mx = float(s.max())
        if mx <= 1.5:          # доли 0..1
            return s * 100.0
        if mx <= 100.0:        # уже проценты
            return s
        return None            # рубли/штуки — долей не являются, не гадаем

    sov_pct = _to_pct(sov)
    som_pct = _to_pct(som)
    if sov_pct is None or som_pct is None:
        return {
            'available': False,
            'reason': (f'Колонки «{sov_col}»/«{som_col}» не похожи на доли '
                       f'(значения вне 0–100) — ESOV-анализ пропущен.'),
        }

    m = min(len(sov_pct), len(som_pct))
    sov_a = sov_pct.values[:m]
    som_a = som_pct.values[:m]
    esov_series = sov_a - som_a
    esov_mean = float(np.mean(esov_series))
    expected_growth = ESOV_SLOPE_POINT * esov_mean
    expected_lo = ESOV_SLOPE_RANGE[0] * esov_mean
    expected_hi = ESOV_SLOPE_RANGE[1] * esov_mean
    if esov_mean < 0:
        expected_lo, expected_hi = expected_hi, expected_lo

    out: dict[str, Any] = {
        'available': True,
        'sov_column': sov_col,
        'som_column': som_col,
        'esov_mean_pp': round(esov_mean, 2),
        'expected_som_growth_pp_per_year': round(expected_growth, 2),
        'expected_som_growth_range_pp': [round(expected_lo, 2), round(expected_hi, 2)],
        'slope_source': ('Binet & Field, The Long and the Short of It: '
                         '≈0.05 пп роста SOM в год на 1 пп ESOV (диапазон 0.05–0.07, digital-эра)'),
    }
    # Факт-сверка: фактический ΔSOM за период наблюдений (честность:
    # ожидание из канона против того, что реально произошло).
    if m >= 6:
        actual_delta = float(som_a[-1] - som_a[0])
        out['actual_som_delta_pp'] = round(actual_delta, 2)
        out['note'] = ('Ожидание — отраслевая закономерность (усреднение сотен '
                       'кампаний), не гарантия для конкретного бренда: сверяйте '
                       'с фактическим изменением доли.')
    return out


def forecast_awareness(config: dict, project_dir: str) -> dict[str, Any]:
    """Forecast awareness based on media spend.

    Args:
        config: {
            'data_file': str,             # xlsx with date, awareness_%, spend columns
            'awareness_column': str,      # Column name for awareness
            'media_columns': list[str],   # Spend columns
            'forecast_periods': int,      # Default 12
        }
    """
    project_path = Path(project_dir)
    data_file = config['data_file']
    df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
    # Материализация виртуальных каналов (merge_rules могут быть и здесь)
    from utils.merge_rules import apply_merge_rules
    apply_merge_rules(df, config.get('merge_rules'))

    awareness_col = config.get('awareness_column', 'awareness_%')
    media_cols = config.get('media_columns', [])
    forecast_periods = config.get('forecast_periods', 12)

    if awareness_col not in df.columns:
        return {'status': 'error', 'message': f'Столбец {awareness_col} не найден в данных'}

    awareness = df[awareness_col].ffill().values.astype(float)
    n = len(awareness)

    # Simple linear regression: total media spend → awareness change
    if media_cols:
        total_spend = df[media_cols].fillna(0).sum(axis=1).values.astype(float)
    else:
        total_spend = np.ones(n)

    # A5/OPP-07 (2026-07-03, канон кабинета §/awareness-forecast): знание
    # строится МЕДЛЕННО и затухает медленно — вместо сырых трат в регрессию
    # идёт adstock с длинным Weibull-хвостом (kernel из utils/adstock, SSOT).
    # config['awareness_adstock'] = {'type': 'weibull'|'geometric'|'none', ...};
    # дефолт — weibull с мягким пиком (shape 2, scale 4 периода).
    _ad_cfg = config.get('awareness_adstock') or {'type': 'weibull', 'shape': 2.0, 'scale': 4.0}
    _ad_type = str(_ad_cfg.get('type', 'weibull')).lower()
    if _ad_type != 'none' and media_cols:
        from utils.adstock import apply_adstock
        total_spend = apply_adstock(
            total_spend, _ad_type,
            {k: v for k, v in _ad_cfg.items() if k != 'type'},
        )
    media_transform = _ad_type if media_cols else 'none'

    # Fit decay + impact model
    # awareness[t] = decay * awareness[t-1] + impact * spend[t] + noise
    if n >= 10:
        from sklearn.linear_model import LinearRegression
        X = np.column_stack([awareness[:-1], total_spend[1:]])
        y = awareness[1:]
        reg = LinearRegression().fit(X, y)
        decay = float(reg.coef_[0])
        impact = float(reg.coef_[1])
        intercept = float(reg.intercept_)
        r2 = float(reg.score(X, y))
    else:
        decay = 0.95
        impact = 0.001
        intercept = awareness.mean() * 0.05
        r2 = 0.0

    # Forecast
    forecast = list(awareness)
    avg_spend = total_spend.mean()
    for t in range(forecast_periods):
        next_val = decay * forecast[-1] + impact * avg_spend + intercept
        next_val = max(0, min(100, next_val))
        forecast.append(next_val)

    forecast_values = [round(v, 1) for v in forecast[n:]]

    # Мат-аудит 2026-07-02 (F-26): прежний «CI» = std(awareness)×0.5 — константа
    # без статистического смысла (прогноз на 12 периодов «уверен» как на 1).
    # Честный прогнозный интервал AR(1): дисперсия h-шагового прогноза
    # var[h] = σ²_resid · Σ_{i=0..h-1} decay^(2i) (стандартная формула
    # прогнозной дисперсии авторегрессии; при |decay|<1 сходится к
    # σ²/(1−decay²)). 90% интервал (z=1.645) — согласован с DEFAULT_HDI_PROB=0.9
    # остального пайплайна. Fallback на прежний прокси при n<10 (нет регрессии).
    if n >= 10:
        resid = y - reg.predict(X)
        sigma_resid = float(np.std(resid, ddof=min(2, max(0, len(resid) - 1))))
        d2 = min(decay * decay, 0.9999)  # защита от decay≥1 (взрыв дисперсии)
        ci_widths = [
            1.645 * sigma_resid * float(np.sqrt((1 - d2 ** h) / (1 - d2)))
            if d2 < 1.0 else 1.645 * sigma_resid * float(np.sqrt(h))
            for h in range(1, forecast_periods + 1)
        ]
        ci_method = 'ar1_forecast_variance_90'
    else:
        flat = float(np.std(awareness) * 0.5)
        ci_widths = [flat] * forecast_periods
        ci_method = 'std_proxy_smalln'

    # A5/OPP-07: ESOV-модуль (Binet & Field, «The Long and the Short of It»,
    # Fig. 31–32: рост SOM пропорционален избыточной доле голоса; в digital-эру
    # ≈0.05 пп годового роста SOM на 1 пп ESOV, диапазон 0.05–0.07).
    # Используем ТОЛЬКО при наличии колонок SOV/SOM в данных (канон кабинета:
    # «иначе пропустить ESOV-модуль» — не выдумываем).
    esov = _esov_module(df, config)

    result = {
        'status': 'ok',
        'model': {
            'decay_rate': round(decay, 4),
            'media_impact': round(impact, 6),
            'r_squared': round(r2, 3),
            'media_transform': media_transform,
        },
        'esov': esov,
        'ci_method': ci_method,
        'historical': [round(v, 1) for v in awareness.tolist()],
        'forecast': forecast_values,
        'ci_lower': [round(max(0, v - w), 1) for v, w in zip(forecast_values, ci_widths)],
        'ci_upper': [round(min(100, v + w), 1) for v, w in zip(forecast_values, ci_widths)],
        'current_awareness': round(float(awareness[-1]), 1),
        'forecast_end': round(forecast_values[-1], 1) if forecast_values else 0,
        'trend': 'рост' if forecast_values and forecast_values[-1] > awareness[-1] else 'снижение',
    }

    # Save
    results_dir = project_path / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / 'awareness-forecast.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def awareness_to_sales(config: dict, project_dir: str) -> dict[str, Any]:
    """Model the S-curve relationship between awareness and sales.

    Args:
        config: {
            'data_file': str,
            'awareness_column': str,
            'sales_column': str,
        }
    """
    project_path = Path(project_dir)
    data_file = config['data_file']
    df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)

    awareness_col = config.get('awareness_column', 'awareness_%')
    sales_col = config.get('sales_column', 'sales')

    if awareness_col not in df.columns or sales_col not in df.columns:
        return {'status': 'error', 'message': f'Нужны столбцы {awareness_col} и {sales_col}'}

    x = df[awareness_col].fillna(0).values.astype(float)
    y = df[sales_col].fillna(0).values.astype(float)

    # Fit S-curve
    try:
        popt, pcov = curve_fit(
            s_curve, x, y,
            p0=[y.max(), 0.1, x.mean()],
            maxfev=5000,
        )
        L, k, x0 = popt
        y_pred = s_curve(x, *popt)
        r2 = 1 - np.sum((y - y_pred) ** 2) / np.sum((y - np.mean(y)) ** 2)

        # Elasticity at current awareness
        current_awareness = float(x[-1])
        dx = 1.0  # +1% awareness
        dy = s_curve(np.array([current_awareness + dx]), *popt)[0] - s_curve(np.array([current_awareness]), *popt)[0]
        elasticity = (dy / s_curve(np.array([current_awareness]), *popt)[0]) / (dx / current_awareness) if current_awareness > 0 else 0

        # A5/OPP-07 (2026-07-03): 90% CI эластичности delta-методом из pcov
        # curve_fit (ковариация параметров у нас УЖЕ была — но не доставлялась,
        # эластичность выглядела точным числом). Градиент эластичности по
        # (L, k, x0) — численно; var = gᵀ·pcov·g; z=1.645 согласован с 90%
        # HDI остального пайплайна.
        elasticity_ci = None
        elasticity_ci_method = None
        try:
            if pcov is not None and np.all(np.isfinite(pcov)) and current_awareness > 0:
                def _elast(params):
                    base = s_curve(np.array([current_awareness]), *params)[0]
                    if base <= 0:
                        return 0.0
                    d = (s_curve(np.array([current_awareness + dx]), *params)[0] - base)
                    return (d / base) / (dx / current_awareness)

                g = np.zeros(3)
                for i in range(3):
                    step = max(abs(popt[i]) * 1e-4, 1e-8)
                    up = np.array(popt, dtype=float); up[i] += step
                    dn = np.array(popt, dtype=float); dn[i] -= step
                    g[i] = (_elast(up) - _elast(dn)) / (2 * step)
                var = float(g @ pcov @ g)
                if var >= 0 and np.isfinite(var):
                    half = 1.645 * float(np.sqrt(var))
                    elasticity_ci = [round(float(elasticity) - half, 3),
                                     round(float(elasticity) + half, 3)]
                    elasticity_ci_method = 'delta_pcov_90'
        except Exception:  # noqa: BLE001 - honesty-контур не роняет расчёт
            elasticity_ci = None

    except Exception:
        L, k, x0 = float(y.max()), 0.1, float(x.mean())
        r2 = 0.0
        elasticity = 0.0
        elasticity_ci = None
        elasticity_ci_method = None

    # Generate curve data for plotting
    x_range = np.linspace(0, min(100, x.max() * 1.5), 100)
    y_range = s_curve(x_range, L, k, x0)

    result = {
        'status': 'ok',
        's_curve': {
            'L': round(float(L), 2),
            'k': round(float(k), 4),
            'x0': round(float(x0), 2),
            'r_squared': round(float(r2), 3),
        },
        'elasticity': round(float(elasticity), 3),
        # A5/OPP-07: интервал эластичности (90%, delta-метод из pcov);
        # None — когда подгонка не сошлась (честно, не константа).
        'elasticity_ci': elasticity_ci,
        'elasticity_ci_method': elasticity_ci_method,
        'threshold': round(float(x0 - 2 / k) if k > 0 else 0, 1),  # Point where curve starts rising
        'saturation': round(float(x0 + 2 / k) if k > 0 else 100, 1),  # Point of diminishing returns
        'current_awareness': round(float(x[-1]), 1),
        'curve_data': {
            'x': x_range.tolist(),
            'y': y_range.tolist(),
            'actual_x': x.tolist(),
            'actual_y': y.tolist(),
        },
        'insight': f"Эластичность awareness→sales = {elasticity:.2f}. "
                   f"{'Awareness выше порога насыщения - наращивание даст убывающий эффект.' if current_awareness > x0 else 'Потенциал роста через awareness ещё не исчерпан.'}",
    }

    # Save
    results_dir = project_path / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / 'awareness-to-sales.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result
