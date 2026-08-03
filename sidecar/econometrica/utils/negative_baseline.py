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

# 🔴 ГРАНИЦА ПРИМЕНИМОСТИ (замер 2026-08-03, не гипотеза).
#
# Свободный член имеет приор `Normal(0, 0.5)` в НОРМАЛИЗОВАННОЙ шкале, поэтому
# база уходит в минус только при `intercept < −y_mean / y_std`. Сколько это
# сигм приора — целиком определяется разбросом самой целевой метрики:
#
#   разброс 8% от среднего (типовой FMCG в рублях) →  26 сигм — недостижимо;
#   разброс 30%                                    →   6,8 сигм — недостижимо;
#   разброс 100% (равен среднему)                  →   2 сигмы — на грани;
#   разброс 200%                                   →   1 сигма — достижимо.
#
# Живой прогон подтвердил: на трёх наборах, построенных как заведомо больные
# (нулевая база в генераторе, весь спрос в тренде, реклама растёт вместе со
# спросом), вердикт остался «годно» — модель просто забирает уровень продаж
# себе в свободный член.
#
# Отсюда правило: если разброс мал, проверка НЕ МОГЛА провалиться, и подавать
# её результат как «пройдено» — ложное утверждение продукта о себе. В таких
# проектах отдаём `not_applicable`. Это тот же принцип, что и всюду в линии:
# «проверка недоступна» ≠ «проверка пройдена».
#
# Порог 0,5 (разброс не меньше половины среднего ⇒ нужно ≤ 4 сигм) — наша
# инженерная граница, а не канон: в первоисточниках описан класс проверки, но
# не её чувствительность к параметризации.
MIN_CV_FOR_DETECTION = 0.5

# Минимальный размер выборки, при котором вероятность вообще что-то означает
# (внешний аудит блока, Low, 2026-08-03): на одном-двух отсчётах она принимает
# только значения 0 и 1, а «границы» совпадают со средним.
MIN_DRAWS = 10


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
    if mean <= 0:
        # 🔴 Внешний аудит блока (Medium, 2026-08-03). Целевая метрика со средним
        # не выше нуля — это денежный KPI «прибыль» у убыточного проекта. Там
        # отрицательная база НОРМАЛЬНА по смыслу метрики, а проверка объявила бы
        # провал и показала клиенту «без рекламы продаж не было бы вовсе — вклад
        # каналов завышен». Утверждение ложное: вклад тут ни при чём. Молчим.
        return None

    n_draws = int(intercept.size)
    if n_draws < MIN_DRAWS:
        # 🔴 Внешний аудит блока (Low, 2026-08-03). На одном отсчёте вероятность
        # равна ровно 0 или 1, а «границы» совпадают со средним — число выглядит
        # как оценка, ею не являясь. Порог отсекает вырожденные прогоны.
        return None

    # Вклад контролей по выборкам: (T, n_controls) @ (n_controls, draws).
    control_effect = np.zeros((1, n_draws), dtype=float)
    controls_applied = False
    try:
        betas = np.asarray(control_betas_samples, dtype=float)
        x_norm = np.asarray(x_control_norm, dtype=float)
        if betas.size and x_norm.size and betas.ndim == 2 and x_norm.ndim == 2:
            if betas.shape[1] != n_draws and betas.shape[0] == n_draws:
                betas = betas.T  # допускаем (draws, n_controls)
            if x_norm.shape[1] == betas.shape[0]:
                control_effect = x_norm @ betas  # (T, draws)
                controls_applied = True
            else:
                # 🔴 Внешний аудит блока (Medium, 2026-08-03). Раньше несогласованные
                # формы выпадали МОЛЧА: база считалась вообще без контролей, а
                # результат отдавался как полноценный. Читатель диагностики не мог
                # отличить «контроли учтены» от «контроли выброшены».
                logger.warning(
                    'Проверка базы: формы контролей не сошлись (x_norm %s, betas %s) — '
                    'вклад контролей НЕ учтён, результат помечен признаком.',
                    x_norm.shape, betas.shape,
                )
    except (TypeError, ValueError) as err:  # noqa: BLE001
        logger.warning('Контроли не учтены в проверке базы: %s', err)

    # Контроли были на входе, но применить их не удалось — это надо знать читателю.
    controls_expected = bool(np.asarray(control_betas_samples).size) if control_betas_samples is not None else False
    controls_dropped = bool(controls_expected and not controls_applied)

    base_norm = intercept[None, :] + control_effect          # (T, draws)
    base_units = base_norm * std + mean                      # в единицах KPI

    if not np.isfinite(base_units).all():
        # 🔴 Внешний аудит блока (Medium, 2026-08-03). Раньше фильтр резал ПЕРИОДЫ
        # (`all(axis=1)` — свёртка по отсчётам), и один NaN среди тысяч выборок
        # делал непригодной каждую строку: функция возвращала `None`, то есть один
        # испорченный отсчёт гасил всю проверку. Режем непригодные ОТСЧЁТЫ.
        годные = np.isfinite(base_units).all(axis=0)         # (draws,)
        if not годные.any():
            return None
        base_units = base_units[:, годные]
        n_draws = int(base_units.shape[1])
        if n_draws < MIN_DRAWS:
            return None

    # Отображаемый базовый уровень — средний по периодам (именно его видит
    # пользователь в карточке декомпозиции), поэтому вероятность считаем по нему.
    per_draw = base_units.mean(axis=0)
    prob_negative = float((per_draw < 0).mean())

    # Могла ли проверка вообще провалиться на этих данных — см. MIN_CV_FOR_DETECTION.
    cv = std / abs(mean) if mean else float('inf')
    sigmas_needed = abs(mean / std) / 0.5  # приор intercept ~ Normal(0, 0.5)
    detectable = bool(cv >= MIN_CV_FOR_DETECTION)

    # По-периодная доля — справочно: она чувствительна к отдельным провалам и
    # порогами не гейтится, но объясняет, почему средняя база «на грани».
    share_periods_negative = float((base_units < 0).mean())

    # Провал засчитывается всегда: если база УЖЕ ушла в минус, это факт, а не
    # вопрос чувствительности. А вот «годно» на нечувствительных данных —
    # ложное утверждение, и вместо него отдаётся «проверка неприменима».
    verdict = _verdict(prob_negative)
    if not detectable and verdict == 'ok':
        verdict = 'not_applicable'

    return {
        'prob_negative': round(prob_negative, 4),
        'verdict': verdict,
        # Чувствительность проверки на этих данных — чтобы «годно» нельзя было
        # спутать с «проверить не удалось».
        'detectable': detectable,
        'cv': round(cv, 3) if np.isfinite(cv) else None,
        'sigmas_needed': round(sigmas_needed, 1) if np.isfinite(sigmas_needed) else None,
        'baseline_mean': round(float(per_draw.mean()), 2),
        'baseline_p05': round(float(np.percentile(per_draw, 5)), 2),
        'baseline_p95': round(float(np.percentile(per_draw, 95)), 2),
        'share_periods_negative': round(share_periods_negative, 4),
        'n_draws': n_draws,
        # 🔴 Честное имя величины (внешний аудит блока, Low, 2026-08-03). Прежнее
        # `displayed_baseline_mean` утверждало равенство с полосой «Базовый уровень»
        # на экране, а считается величина ДО выноса факторов: декомпозиция вычитает
        # из базы каждый выносимый фактор любого знака (`decomposer.py:517`), поэтому
        # при наличии хотя бы одного фактора числа расходятся всегда.
        'basis': 'baseline_before_factor_breakout_mean',
        # Учтён ли вклад контролей. `False` при несогласованных формах — тогда база
        # посчитана по одному свободному члену, и это не то же самое, что «контролей
        # в модели нет».
        'controls_dropped': controls_dropped,
        'thresholds': {'ok_below': PROB_OK, 'fail_above': PROB_FAIL},
    }
