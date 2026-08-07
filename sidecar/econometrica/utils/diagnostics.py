"""
Model diagnostics for MMM quality assessment.
MQS (Model Quality Score), convergence checks, fit metrics.
"""
import logging
import numpy as np
from typing import Any

logger = logging.getLogger(__name__)


def compute_r_squared(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Coefficient of determination."""
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0


def compute_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Percentage Error (%)."""
    mask = y_true != 0
    if not mask.any():
        return 0.0
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def compute_rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Root Mean Squared Error."""
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def prior_sds_for_bayesian(gammas_alpha: float = 3.0, gammas_beta: float = 3.0) -> dict:
    """Аналитические prior SD параметров non-hierarchical Bayesian MMM
    (синхронно с modeler.py: intercept~N(0,0.5), media_betas~HalfNormal(0.3),
    control_betas~N(mu,0.3), alphas~Gamma(5,3), gammas~Beta(a,b)).
    SSOT для contraction — используют и modeler (train), и recompute_mqs (миграция)."""
    import math
    hn = lambda s: s * math.sqrt(1 - 2 / math.pi)  # HalfNormal SD
    return {
        'intercept': 0.5,
        'media_betas': hn(0.3),
        'control_betas': 0.3,
        'alphas': math.sqrt(5) / 3,
        'gammas': math.sqrt(gammas_alpha * gammas_beta /
                            ((gammas_alpha + gammas_beta) ** 2 * (gammas_alpha + gammas_beta + 1))),
    }


def effective_params_contraction(posterior_sd: dict, prior_sd: dict) -> float:
    """Эффективное число параметров через posterior contraction.

    Для каждого параметра: contraction = clip(1 − Var_post/Var_prior, 0, 1).
    ≈1 → данные полностью определяют параметр (1 эфф.); ≈0 → posterior=prior,
    данные неинформативны (0 эфф.). Сумма по всем = эффективные степени свободы.

    posterior_sd / prior_sd: dict group_name → SD. posterior_sd[g] может быть
    скаляром или списком/массивом (по элементам параметра-вектора); prior_sd[g]
    — скаляр (общий prior на группу). Возвращает сумму (float) или None если
    ничего не посчиталось.
    """
    import numpy as np
    total = 0.0
    counted = 0
    for g, psd in prior_sd.items():
        if g not in posterior_sd or psd is None or psd <= 0:
            continue
        sd = np.atleast_1d(np.asarray(posterior_sd[g], dtype=float)).ravel()
        sd = sd[np.isfinite(sd)]  # F-PY2 (аудит): NaN/Inf draws не должны давать NaN eff_params
        if sd.size == 0:
            continue
        contraction = np.clip(1.0 - (sd ** 2) / (float(psd) ** 2), 0.0, 1.0)
        total += float(contraction.sum())
        counted += sd.size
    return total if counted > 0 else None


def per_control_contraction(control_betas_post_sd, prior_control_sd, control_cols) -> dict:
    """Per-control posterior contraction {name: clip(1−Var_post/Var_prior, 0, 1)}.

    #6 OVB-guardrail (2026-06-07): contraction<0.1 → контроль неинформативен
    (posterior≈prior, данные его не определили) → можно убрать БЕЗ omitted-variable
    bias и без нечестного роста MQS; ≥0.3 → информативен (удаление = смещение media-ROI
    (OVB) + нечестный рост MQS-cap). SSOT-формула — используют modeler (train) и
    recompute_mqs (миграция). prior_control_sd = prior_sds_for_bayesian()['control_betas'].
    """
    import numpy as np
    out: dict[str, float] = {}
    try:
        psd = float(prior_control_sd or 0.0)
    except (TypeError, ValueError):
        psd = 0.0
    if control_betas_post_sd is None or not control_cols or psd <= 0:
        return out
    sd = np.atleast_1d(np.asarray(control_betas_post_sd, dtype=float)).ravel()
    for i, name in enumerate(control_cols):
        if i < sd.size and np.isfinite(sd[i]):  # F-PY2 (аудит): не эмитить NaN/Inf
            out[name] = round(float(np.clip(1.0 - (sd[i] ** 2) / (psd ** 2), 0.0, 1.0)), 3)
    return out


# SSOT тиры MQS (score, tier, tier_label, color) — единственный источник порогов
# 85/70/55/40. Рассинхрон копии этих чисел в слое представления (aurora_html)
# уже ловили в бою (L16, 2026-04-29: MQS=70 показывал «Хорошее» в одном месте
# и «приемлемо» в другом при разных порогах). Presentation-слой обязан читать
# тир через `mqs_tier_info()`, а не держать свою копию порогов.
_MQS_TIERS = (
    (85, 'excellent', 'Отличное', '#22c55e'),
    (70, 'good', 'Хорошее', '#3b82f6'),
    (55, 'acceptable', 'Приемлемое', '#f59e0b'),
    (40, 'weak', 'Слабое', '#f97316'),
    (0, 'poor', 'Ненадёжное', '#ef4444'),
)


#: Клиентские ярлыки уровней — набор для проверки того, что пришло извне.
#: Заведён 2026-07-26: слой представления доверял полю `mqs_tier_label` как есть,
#: и значение ключа `tier` («excellent» вместо «Отличное») доехало бы до клиента
#: английским, да ещё сбив подбор пояснения на «Приемлемо» при отличной модели.
#: Проверять принадлежность этому набору, а не просто непустоту строки.
MQS_TIER_LABELS = frozenset(label for _threshold, _tier, label, _color in _MQS_TIERS)


def mqs_tier_info(mqs: float) -> dict:
    """SSOT-классификация посчитанного MQS в {tier, tier_label, color}.

    Единственный владелец порогов 85/70/55/40 — presentation-слой (aurora_html/
    aurora_pptx) обязан звать эту функцию вместо локальной копии диапазонов.
    Вызывать только когда mqs реально посчитан (не None) — отсутствие метрики
    обрабатывается на уровне вызывающего кода, не здесь.
    """
    for threshold, tier, label, color in _MQS_TIERS:
        if mqs >= threshold:
            return {'tier': tier, 'tier_label': label, 'color': color}
    return {'tier': 'poor', 'tier_label': 'Ненадёжное', 'color': '#ef4444'}


def resolve_mqs_tier_label(score: float, external_label: str | None) -> str:
    """Ярлык уровня для показа: внешний — только если он ещё и СОВПАДАЕТ с
    тем, что канон даёт для этого балла; иначе — производный от балла.

    Находка внешнего аудита (2026-07-27): `aurora_html/sections.py` (два
    места) проверял(и) только ПРИНАДЛЕЖНОСТЬ пришедшего `mqs_tier_label`
    набору `MQS_TIER_LABELS`, не сверяя с самим баллом — валидный ярлык
    канона, но не для ЭТОГО балла (например из старого/частично обновлённого
    расчёта на диске — `results/model-diagnostics.json` не подписан и уже
    имеет прецедент внешней точечной правки, см. `tools/recompute_mqs.py`),
    проходил как есть. `resolve_mqs_tier_label(42.0, 'Отличное')` раньше
    возвращал `'Отличное'`, хотя канон для 42.0 даёт `'Слабое'`.

    Данные первичны: при расхождении уровень считается ИЗ БАЛЛА. Расхождение
    не проглатывается молча — уходит в лог (диагностика, НЕ клиентский
    текст). Единственная точка этой проверки — оба места в sections.py
    обязаны звать эту функцию, а не дублировать `in MQS_TIER_LABELS` у себя
    (дубль этой самой проверки и был находкой). Симметричный Rust-фикс —
    `src-tauri/src/commands/mqs_tiers.rs::resolve_mqs_label`.
    """
    canon_label = mqs_tier_info(score)['tier_label']
    if external_label in MQS_TIER_LABELS:
        if external_label == canon_label:
            return external_label
        logger.warning(
            'MQS: внешний ярлык %r не соответствует канону для балла %.1f '
            '(канон: %r) - используется ярлык из балла',
            external_label, score, canon_label,
        )
    return canon_label


def model_quality_score(r_squared: float, mape: float, r_hat_max: float,
                        divergences: int = 0, ratio: float | None = None) -> dict:
    """Compute Model Quality Score (MQS) with tier classification.

    Applies a data-thinness cap based on observations-to-parameters ratio:
      ratio < 2  → MQS capped at 50 (weak) - severe overfitting risk
      ratio < 4  → MQS capped at 70 (good, not excellent) - wide CIs likely

    Without the cap, a well-converged overfit model on thin data gets a
    misleadingly high score (R² ~0.99 when model just memorised noise).

    Returns:
        Dict with score, tier, tier_label, color, components, and thinness_cap.
    """
    # Component scores (0-100 each)
    r2_score = min(100, max(0, r_squared * 100))
    mape_score = min(100, max(0, 100 - mape * 2))  # MAPE 0%=100, 50%=0
    convergence_score = 100 if r_hat_max < 1.05 and divergences == 0 else (
        70 if r_hat_max < 1.1 else 30
    )

    # Weighted average
    raw_mqs = r2_score * 0.4 + mape_score * 0.3 + convergence_score * 0.3

    # Data-thinness cap
    thinness_cap = None
    if ratio is not None:
        if ratio < 2:
            thinness_cap = 50
        elif ratio < 4:
            thinness_cap = 70
    mqs = min(raw_mqs, thinness_cap) if thinness_cap is not None else raw_mqs

    # Tier classification (SSOT lookup — см. mqs_tier_info выше).
    _tier_info = mqs_tier_info(mqs)
    tier, label, color = _tier_info['tier'], _tier_info['tier_label'], _tier_info['color']

    return {
        'score': round(mqs, 1),
        'raw_score': round(raw_mqs, 1),
        'tier': tier,
        'tier_label': label,
        'color': color,
        'thinness_cap': thinness_cap,
        'ratio': round(ratio, 2) if ratio is not None else None,
        'components': {
            'r_squared': {'value': round(r_squared, 4), 'score': round(r2_score, 1)},
            'mape': {'value': round(mape, 2), 'score': round(mape_score, 1)},
            'convergence': {'r_hat_max': round(r_hat_max, 4), 'divergences': divergences,
                           'score': round(convergence_score, 1)},
        },
    }


# Отчёт может собраться из ДВУХ РАЗНЫХ моделей и промолчать: переобучение
# чистит только состояние в памяти (src/lib/project-state.js:1394), а
# results/optimization.json остаётся на диске и воскресает при открытии проекта
# (src-tauri/src/commands/project.rs:631 → project-state.js:1260). Тогда рядом
# оказываются живая диагностика новой модели и числа переброски от старой.
#
# 🔴 ЗЕРКАЛО: тот же текст ДОСЛОВНО живёт в src-tauri/src/commands/report.rs —
# Rust не импортирует Python и собирает Markdown и XLSX сам. Сверяет их сторож
# tests/test_reliability_stamp_and_provenance.py. Правя здесь, правь и там.
# Клиентский текст: короткое тире «–», без англицизмов.
PROVENANCE_MISMATCH_NOTE = (
    'Результаты оптимизации получены на другой модели, чем показанная '
    'диагностика – пересчитайте оптимизацию, прежде чем опираться на '
    'переброску бюджета.'
)


def format_thinness_caveat(ratio: float | None, thinness_cap: int | None,
                           *, leading_space: bool = True) -> str:
    """SSOT-формулировка оговорки о тонких данных / переобучении.

    INV-50 F-DELIVERABLE-1 (2026-06-07): эта оговорка должна звучать ОДИНАКОВО
    везде — в вердикте программы, в сопроводительном письме И в клиентских
    отчётах (PPTX/HTML/XLSX). Прежде текст жил inline в `generate_diagnostics_
    summary` и доходил только до программы; отчёты его роняли на report-шве.
    Теперь и вердикт, и билдеры зовут эту функцию → формулировка едина, новый
    N+1-й слой расхождения физически невозможен (Rust XLSX зеркалит дословно,
    см. report.rs — пометка SSOT там же).

    Возвращает '' когда cap не применён (данных достаточно).
    """
    if thinness_cap is None or ratio is None:
        return ""
    if ratio < 2:
        # Тон McElreath (Волна 1, 2026-06-20): не «артефакт переобучения» /
        # алармизм, а честно про механизм — модель на таких данных сильно
        # опирается на априорные допущения, точечная надёжность ограничена.
        body = (f"⚠ Данных мало (Ratio {ratio:.1f}:1) – модель сильно опирается "
                f"на априорные предположения, правдоподобный диапазон широкий, "
                f"точечная надёжность ограничена.")
    else:
        body = (f"⚠ Данных мало (Ratio {ratio:.1f}:1 < 4:1) – модель сдержана, "
                f"опирается на априорные предположения; правдоподобный диапазон "
                f"будет широким.")
    return (" " + body) if leading_space else body


def generate_diagnostics_summary(r_squared: float, mape: float, rmse: float,
                                  r_hat_max: float, divergences: int,
                                  n_obs: int, n_params: int,
                                  effective_params: float | None = None,
                                  ess_bulk_min: float | None = None,
                                  ess_tail_min: float | None = None,
                                  bfmi_min: float | None = None) -> dict:
    """Full diagnostics summary for UI display.

    effective_params (2026-06-07): эффективное число параметров (posterior
    contraction, 1−Var_post/Var_prior). Для байес-моделей << номинального
    n_params (приоры «сжимают» слабо-идентифицируемые параметры — adstock/
    saturation/редкие праздники). Data-thinness cap МQS считается по
    ЭФФЕКТИВНОМУ ratio (честные степени свободы), а не по номинальному —
    иначе байес-модель штрафуется как OLS. Если None (OLS / иерарх. путь) —
    fallback на номинальный ratio (прежнее поведение).
    Номинальные значения сохраняются в metrics для прозрачности.

    ess_bulk_min / ess_tail_min / bfmi_min (мат-аудит 2026-07-02, F-11/F-12):
    минимальные bulk/tail-ESS по параметрам модели и минимальный E-BFMI по
    цепям. Пороги: ESS ≥ 400 (Vehtari et al. 2021 — recommended threshold;
    при ESS < 400 сам R-hat ненадёжен), E-BFMI ≥ 0.3 (эвристика Stan/PyMC —
    НЕ приписывать Betancourt). None (OLS-путь / недоступно) → соответствующий
    check НЕ добавляется (unknown ≠ pass); MQS-формула этими полями НЕ меняется
    — честность доносится через optimizer_honesty (uncertain-гейт).
    """
    from utils.model_spec import bayesian_mmm_spec
    nominal_ratio = n_obs / max(n_params, 1)
    eff_p = effective_params if (effective_params is not None and effective_params > 0) else n_params
    ratio = n_obs / max(eff_p, 1)  # ЭФФЕКТИВНЫЙ ratio → cap (степени свободы)
    mqs = model_quality_score(r_squared, mape, r_hat_max, divergences, ratio=ratio)

    # Human-readable verdict.
    # ВАЖНО: MQS-бейдж (слева от текста) - агрегированный score 0-100 из R²+MAPE+convergence.
    # R² - отдельная метрика (fit), явно маркируем её в тексте чтобы не путать с MQS.
    r2_pct = round(r_squared * 100)
    # INV-50 F-DELIVERABLE-1: единая формулировка (та же, что в отчётах).
    thin_note = format_thinness_caveat(ratio, mqs.get('thinness_cap'))

    if mqs['tier'] in ('excellent', 'good') and not thin_note:
        verdict = f"Модель объясняет {r2_pct}% вариации продаж (R²). Надёжный результат для принятия бюджетных решений."
    elif mqs['tier'] in ('excellent', 'good'):
        # honesty-аудит 2026-06-13 (sub-finding b): tier хороший, но данных мало
        # (ratio<4 → thin_note непустой) → НЕ заявляем «надёжно для бюджетных решений»
        # (противоречило бы предупреждению о переобучении). Лид смягчён, согласовано
        # с M2 (optimizer_honesty): тонкая «хорошая» модель = uncertain, не reliable.
        verdict = f"Модель объясняет {r2_pct}% вариации продаж (R²) и формально качественна, но на ограниченных данных результаты ориентировочные.{thin_note}"
    elif mqs['tier'] == 'acceptable':
        verdict = f"Модель объясняет {r2_pct}% вариации продаж (R²). Приемлемо для ориентировочных решений, рекомендуем дополнительную валидацию.{thin_note}"
    elif mqs.get('thinness_cap') is not None and r_squared >= 0.7:
        # MQS-1 (2026-06-02): tier weak/poor достигается двумя путями — реально низкий
        # fit ИЛИ высокий R², зажатый data-thinness cap (короткий ряд → переобучение).
        # «объясняет только 98%» вводит в заблуждение: 98% — высокий fit, реальная
        # проблема в переобучении (её раскрывает thin_note). INV-50: честно про корень.
        verdict = (
            f"Модель объясняет {r2_pct}% вариации продаж (R²) — высокий fit. "
            f"На коротких данных это вероятный признак переобучения, а не надёжности.{thin_note}"
        )
    else:
        verdict = f"Модель объясняет только {r2_pct}% вариации продаж (R²). Результаты ненадёжны - нужно больше данных или другая спецификация.{thin_note}"

    return {
        'mqs': mqs,
        'verdict': verdict,
        'metrics': {
            'r_squared': round(r_squared, 4),
            'mape_pct': round(mape, 2),
            'rmse': round(rmse, 2),
            'r_hat_max': round(r_hat_max, 4),
            'divergences': divergences,
            'n_observations': n_obs,
            'n_parameters': n_params,
            'effective_parameters': round(eff_p, 1),
            'ratio': round(ratio, 1),            # эффективный (степени свободы) — драйвит cap
            'ratio_nominal': round(nominal_ratio, 1),
            # F-11/F-12 (2026-07-02): None → null в JSON (прозрачно «не измерено»).
            'ess_bulk_min': round(ess_bulk_min, 1) if ess_bulk_min is not None else None,
            'ess_tail_min': round(ess_tail_min, 1) if ess_tail_min is not None else None,
            'bfmi_min': round(bfmi_min, 3) if bfmi_min is not None else None,
        },
        'checks': {
            'convergence': r_hat_max < 1.05 and divergences == 0,
            'fit': r_squared > 0.5,
            'ratio': ratio >= 4,                 # по эффективному ratio
            # F-11/F-12: ключи добавляются ТОЛЬКО при измеренных значениях
            # (unknown ≠ pass; back-compat: старые вызовы без kwargs — без ключей).
            **({'ess': (ess_bulk_min is None or ess_bulk_min >= 400)
                       and (ess_tail_min is None or ess_tail_min >= 400)}
               if (ess_bulk_min is not None or ess_tail_min is not None) else {}),
            **({'bfmi': bfmi_min >= 0.3} if bfmi_min is not None else {}),
        },
        'model_spec': bayesian_mmm_spec(),
    }
