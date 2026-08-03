"""P0.6: проверка канона — отрицательный базовый уровень.

ЗАЧЕМ. Это единственная проверка канона, за которой стоят деньги: она ловит
завышенный ROI. Если модель утверждает, что без рекламы продажи были бы
отрицательными, значит вклад медиаканалов приписан с избытком — и все
рекомендации по бюджету, построенные на этих вкладах, завышены.

ОБОСНОВАНИЕ (первоисточники, не наше мнение):
  - Wang & Jin, «Hierarchical Bayesian… Improve Media Mix Models with Category
    Data» (Google): «Sometimes models with unconstrained priors output negative
    media effect estimates due to omitted variables» — неограниченные приоры
    дают содержательно НЕВОЗМОЖНЫЕ оценки, и причина обычно в пропущенных
    переменных. Отрицательная база — тот же класс с другой стороны: избыток
    приписан медиа, недостаток вытеснен в базу.
  - McElreath, «Statistical Rethinking»: апостериорные проверки нужны не чтобы
    подтвердить истинность модели, а чтобы «prospecting for ways in which your
    models are inadequate» — искать, чем именно модель неадекватна.
  - Gelman, «Bayesian Workflow»: «it can be safe to discard models which show
    clear discrepancies between predictions and data».

⚠️ ПОРОГИ — ПРОДУКТОВОЕ СОГЛАШЕНИЕ, НЕ КАНОН. Значения 0,2 и 0,8 взяты из плана
P0 и первоисточником не подкреплены: в литературе описан сам класс проверки, а
не числовые границы. Менять их — решение владельца, не «уточнение по науке».

КАК СЧИТАЕТСЯ. Модель обучается в нормализованной шкале
(`y_norm = (y − y_mean) / y_std`), поэтому `intercept` живёт НЕ в единицах KPI:
на здоровом проекте он около −0,5 при продажах в тысячах. База в исходных
единицах восстанавливается так же, как это делает прогноз:

    base(t)_d = (intercept_d + Σ_i control_betas_d,i · x_norm_i(t)) · y_std + y_mean

Считаем по УЖЕ сохранённым апостериорным выборкам, переобучение не требуется.
Замер на реальной модели: средняя база по выборкам 6528,5 против показанной в
декомпозиции 6536,2 — расхождение 0,12%, то есть величина совпадает с той, что
видит пользователь (остаток подгонки, который декомпозиция досыпает в базу ради
тождества разложения, на этом уровне пренебрежим).

ТОЛЬКО БАЙЕС. В режиме OLS апостериорных выборок нет вовсе (`ols_modeler` их не
пишет), поэтому проверка возвращает `None` — как торнадо чувствительности.
Обещать её для всех проектов в клиентском тексте нельзя.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Продуктовое соглашение (план P0), не первоисточник — см. шапку модуля.
PROB_OK = 0.2
PROB_FAIL = 0.8


def _verdict(prob: float) -> str:
    """Ярлык по вероятности. Границы включаются в более мягкую сторону."""
    if prob < PROB_OK:
        return 'ok'
    if prob <= PROB_FAIL:
        return 'watch'
    return 'fail'


def compute_negative_baseline(
    intercept_samples: Any,
    control_betas_samples: Any,
    x_control_norm: Any,
    y_mean: float,
    y_std: float,
) -> dict[str, Any] | None:
    """Вероятность того, что базовый уровень продаж отрицателен.

    @param intercept_samples: выборки свободного члена, форма (draws,).
    @param control_betas_samples: выборки коэффициентов контролей,
        форма (n_controls, draws). Пустой массив — контролей нет.
    @param x_control_norm: нормализованная матрица контролей, форма
        (T, n_controls). Пустая — контролей нет.
    @param y_mean: среднее целевой метрики (масштаб нормализации).
    @param y_std: стандартное отклонение целевой метрики.
    @returns: словарь с вероятностью, вердиктом и границами базы в единицах
        KPI; `None`, если посчитать не из чего (нет выборок / вырожденный
        масштаб) — молчание честнее выдуманного числа.
    """
    try:
        intercept = np.asarray(intercept_samples, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return None
    if intercept.size == 0:
        return None

    std = float(y_std)
    mean = float(y_mean)
    if not np.isfinite(std) or std <= 0 or not np.isfinite(mean):
        # Вырожденный масштаб: KPI-константа или битая нормализация. Считать
        # «вероятность» на таком входе значило бы выдать число из ниоткуда.
        return None

    n_draws = int(intercept.size)

    # Вклад контролей по выборкам: (T, n_controls) @ (n_controls, draws).
    control_effect = np.zeros((1, n_draws), dtype=float)
    try:
        betas = np.asarray(control_betas_samples, dtype=float)
        x_norm = np.asarray(x_control_norm, dtype=float)
        if betas.size and x_norm.size and betas.ndim == 2 and x_norm.ndim == 2:
            if betas.shape[1] != n_draws and betas.shape[0] == n_draws:
                betas = betas.T  # допускаем (draws, n_controls)
            if x_norm.shape[1] == betas.shape[0]:
                control_effect = x_norm @ betas  # (T, draws)
    except (TypeError, ValueError) as err:  # noqa: BLE001
        logger.warning('Контроли не учтены в проверке базы: %s', err)

    base_norm = intercept[None, :] + control_effect          # (T, draws)
    base_units = base_norm * std + mean                      # в единицах KPI

    if not np.isfinite(base_units).all():
        base_units = base_units[np.isfinite(base_units).all(axis=1)]
        if base_units.size == 0:
            return None

    # Отображаемый базовый уровень — средний по периодам (именно его видит
    # пользователь в карточке декомпозиции), поэтому вероятность считаем по нему.
    per_draw = base_units.mean(axis=0)
    prob_negative = float((per_draw < 0).mean())

    # По-периодная доля — справочно: она чувствительна к отдельным провалам и
    # порогами не гейтится, но объясняет, почему средняя база «на грани».
    share_periods_negative = float((base_units < 0).mean())

    return {
        'prob_negative': round(prob_negative, 4),
        'verdict': _verdict(prob_negative),
        'baseline_mean': round(float(per_draw.mean()), 2),
        'baseline_p05': round(float(np.percentile(per_draw, 5)), 2),
        'baseline_p95': round(float(np.percentile(per_draw, 95)), 2),
        'share_periods_negative': round(share_periods_negative, 4),
        'n_draws': n_draws,
        # На чём считалось — чтобы читатель не гадал, та ли это база, что на экране.
        'basis': 'displayed_baseline_mean',
        'thresholds': {'ok_below': PROB_OK, 'fail_above': PROB_FAIL},
    }
