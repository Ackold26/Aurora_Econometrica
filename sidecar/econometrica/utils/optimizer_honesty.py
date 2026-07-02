"""M2 — model-reliability verdict for the optimizer (honesty-gate).

Коммерческий риск (PRD §п2): ядро ценности = ROI-рекомендации по переброске
бюджета; неверный совет хуже отсутствия совета. До M2 `optimize()` выдавал совет,
НЕ консультируясь с диагностикой надёжности модели (доказано
tools/probe_optimizer_honesty_kagocel.py на реальном Кагоцеле: Ratio 2.4:1,
checks.ratio=False, а выход оптимизатора нёс «Scale Social mROAS=27» — артефакт
переобучения — без единого предупреждения).

SSOT диагностики = `results/model-diagnostics.json`
(`utils.diagnostics.generate_diagnostics_summary`, пишется при train/decompose).
pickle.mcmc_diagnostics ПУСТ → rHat/divergences/ratio/checks живут только там.

Политика-гибрид (решение Антона, grill-me 2026-06-13):
  - **unreliable** → ОТКАЗ от переброски: `r_hat_max ≥ 1.05` ИЛИ дивергенций
    > 1% черновиков (несошедшаяся модель). NB: неисправленные смешанные единицы
    (native-канал без unit_cost) УЖЕ жёстко гейтятся выше как error UNIT_SMELL —
    здесь не дублируем.
  - **uncertain** → совет + громкий caveat + бенды: `checks.ratio=False` (Ratio<4,
    тонко) ИЛИ MQS-tier слабый/poor ИЛИ 0<дивергенций≤порог (лёгкая нестабильность).
  - **reliable** → совет как есть.

Чистая функция — тестируется изолированно (tools/test_optimizer_honesty.py).
UI потребляет результат verbatim (INV-50, единый источник), не пере-выводит.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Дивергенции считаются «несошедшейся» при превышении max(абс.пол, 1% черновиков).
# Абс. пол защищает от ложного refuse при малом числе черновиков (пара дивергенций
# на 30 наблюдениях — норма для NUTS, не катастрофа).
DIVERGENCE_REFUSE_FRAC = 0.01
DIVERGENCE_ABS_FLOOR = 20
RHAT_REFUSE_THRESHOLD = 1.05
WEAK_TIERS = ('weak', 'poor')


def load_model_diagnostics(project_path: str | Path) -> dict[str, Any]:
    """Читает SSOT results/model-diagnostics.json. {} если файла нет (не блокируем)."""
    f = Path(project_path) / 'results' / 'model-diagnostics.json'
    if not f.exists():
        return {}
    try:
        with open(f, encoding='utf-8') as fh:
            return json.load(fh) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def _total_draws(metrics: dict) -> int:
    mcmc = metrics.get('mcmc') or {}
    try:
        chains = int(mcmc.get('chains') or 0)
        draws = int(mcmc.get('draws') or 0)
        return chains * draws
    except (TypeError, ValueError):
        return 0


def model_reliability_verdict(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Вердикт надёжности модели для гейта оптимизатора.

    Args:
        diagnostics: содержимое results/model-diagnostics.json
            (или прямой выход generate_diagnostics_summary).

    Returns:
        {
          'verdict': 'reliable'|'uncertain'|'unreliable'|'unknown',
          'refused': bool,                  # True ⟺ unreliable (UI прячет переброску)
          'reasons': [str, ...],            # машинно-сводимые причины
          'caveat_text': str,               # одна фраза для баннера UI
        }
    """
    if not diagnostics:
        return {
            'verdict': 'unknown',
            'refused': False,
            'reasons': ['Диагностика модели недоступна — надёжность не проверена.'],
            'caveat_text': ('Не удалось проверить надёжность модели (нет диагностики). '
                            'Трактуйте рекомендации осторожно.'),
        }

    metrics = diagnostics.get('metrics') or {}
    checks = diagnostics.get('checks') or {}
    mqs = diagnostics.get('mqs') or {}
    engine = (diagnostics.get('engine') or '').lower()

    # OVB-маркер (аудит 2026-06-14): праздники РФ принудительно исключены
    # (use_holidays=False). Если категория сезонна к праздникам — модель смещена
    # (omitted-variable bias), и «надёжной» её называть нельзя (отсутствие эффекта мы
    # подтвердить не можем). Маркер ставит modeler.py/ols_modeler.py при обучении.
    holidays_excluded = bool(diagnostics.get('holidays_excluded'))
    ovb_reason = ('Праздники РФ исключены из модели: если категория сезонна к праздникам, '
                  'вклад медиаканалов может быть смещён (omitted-variable bias). Убедитесь, '
                  'что спрос категории к праздникам нечувствителен.')
    ovb_caveat = ' Праздники исключены — возможен OVB, если категория сезонна.'

    # ── OLS small-data fallback → НИКОГДА не reliable (аудит 2026-06-14) ────
    # OLS-диагностика (ols_modeler) НЕ содержит checks/mqs/ratio: ни одна ветка ниже
    # не сработала бы → молча 'reliable'. Но OLS = режим МАЛЫХ данных (n<30): Hill-
    # параметры ФИКСИРОВАНЫ (не обучаются), нет MCMC. Худший случай не должен получать
    # самый уверенный вердикт → максимум 'uncertain'.
    if engine == 'ols':
        n_obs = diagnostics.get('n_obs') or metrics.get('n_observations')
        n_params = diagnostics.get('n_params') or metrics.get('n_parameters')
        ratio_ols = (n_obs / n_params) if (n_obs and n_params) else None
        rtxt = f', Ratio {ratio_ols:.1f}:1' if ratio_ols else ''
        reasons = [f'Режим малых данных OLS (n={n_obs}{rtxt}): Hill-параметры фиксированы '
                   f'(не обучаются), доверительные интервалы частотные — рекомендации '
                   f'ориентировочные.']
        caveat = ('Режим малых данных (OLS): рекомендации ориентировочные, опирайтесь на '
                  'доверительные интервалы и валидируйте крупные сдвиги лифт-тестом.')
        if holidays_excluded:
            reasons.append(ovb_reason)
            caveat += ovb_caveat
        return {'verdict': 'uncertain', 'refused': False,
                'reasons': reasons, 'caveat_text': caveat}

    r_hat = float(metrics.get('r_hat_max') or 0.0)
    divergences = int(metrics.get('divergences') or 0)
    ratio = metrics.get('ratio')
    tier = (mqs.get('tier') or '').lower()
    tier_label = mqs.get('tier_label') or tier or '—'
    score = mqs.get('score')

    total_draws = _total_draws(metrics)
    div_thresh = max(DIVERGENCE_ABS_FLOOR, int(DIVERGENCE_REFUSE_FRAC * total_draws)) \
        if total_draws else DIVERGENCE_ABS_FLOOR

    reasons: list[str] = []

    # ── unreliable (отказ) ────────────────────────────────────────────────
    bad_rhat = r_hat >= RHAT_REFUSE_THRESHOLD
    bad_div = divergences > div_thresh
    if bad_rhat:
        reasons.append(
            f'Модель не сошлась (R-hat {r_hat:.3f} ≥ {RHAT_REFUSE_THRESHOLD}) — '
            f'переброска не строится на несошедшейся модели.')
    if bad_div:
        reasons.append(
            f'{divergences} дивергенций MCMC (> порога {div_thresh}) — сэмплер не '
            f'исследовал часть пространства параметров; результаты ненадёжны.')
    if bad_rhat or bad_div:
        return {
            'verdict': 'unreliable',
            'refused': True,
            'reasons': reasons,
            'caveat_text': ('Модель не завершила расчёт корректно — рекомендации по '
                            'переброске бюджета отключены. Увеличьте число итераций или '
                            'упростите модель и переобучите.'),
        }

    # ── uncertain (совет + caveat) ────────────────────────────────────────
    thin = checks.get('ratio') is False
    weak_tier = tier in WEAK_TIERS
    mild_div = divergences > 0
    # Мат-аудит 2026-07-02 (F-11/F-12): ESS/E-BFMI-гейты. Ключи в checks
    # присутствуют только когда метрики реально измерены (NUTS-путь) —
    # отсутствие ключа НЕ считается провалом (OLS/legacy).
    low_ess = checks.get('ess') is False
    low_bfmi = checks.get('bfmi') is False
    # Мат-аудит 2026-07-02 (F-13): prior predictive из in-train preflight.
    # fail → priors допускают неправдоподобные продажи ДО данных (McElreath;
    # Gelman, Bayesian Workflow §5.10) — доверие к CI/оптимуму снижено.
    _pp_status = (((diagnostics.get('preflight') or {}).get('prior_predictive')
                   or {}).get('status'))
    prior_pred_fail = _pp_status == 'fail'
    if thin:
        ratio_txt = f' (Ratio {ratio}:1 < 4:1)' if ratio is not None else ''
        reasons.append(
            f'Тонкие данные{ratio_txt} — высокий риск переобучения; ROI-оценки и '
            f'доверительные интервалы ориентировочны (особенно аномально высокие mROAS).')
    if weak_tier:
        score_txt = f' (MQS {score})' if score is not None else ''
        reasons.append(f'Низкое качество модели{score_txt}, «{tier_label}».')
    if mild_div:
        reasons.append(
            f'{divergences} дивергенц(ий) MCMC — лёгкая нестабильность сэмплера, '
            f'трактуйте рекомендации осторожно.')
    if low_ess:
        _eb = metrics.get('ess_bulk_min')
        _et = metrics.get('ess_tail_min')
        _ess_txt = ''
        if _eb is not None or _et is not None:
            _parts = []
            if _eb is not None:
                _parts.append(f'bulk {_eb:.0f}')
            if _et is not None:
                _parts.append(f'tail {_et:.0f}')
            _ess_txt = f' ({", ".join(_parts)} < 400)'
        reasons.append(
            f'Эффективный размер выборки MCMC ниже порога 400{_ess_txt} '
            f'(Vehtari et al. 2021) — цепи перемешаны слабо, при таком ESS сам '
            f'R-hat ненадёжен; доверительные интервалы ориентировочны.')
    if low_bfmi:
        _bf = metrics.get('bfmi_min')
        _bf_txt = f' {_bf:.2f}' if _bf is not None else ''
        reasons.append(
            f'E-BFMI{_bf_txt} < 0.3 (эвристика Stan/PyMC) — сэмплер плохо '
            f'исследует хвосты распределения энергии; результаты менее надёжны '
            f'(обычно лечится non-centered параметризацией).')
    if prior_pred_fail:
        reasons.append(
            'Prior predictive check: fail — априорные допущения модели дают '
            'неправдоподобный диапазон продаж ещё до данных (симуляция из priors); '
            'оценки могут определяться приором, а не данными — трактуйте '
            'рекомендации осторожно.')
    data_uncertain = thin or weak_tier or mild_div or low_ess or low_bfmi or prior_pred_fail
    if data_uncertain or holidays_excluded:
        if holidays_excluded:
            reasons.append(ovb_reason)
        if data_uncertain:
            # Тонкие/слабые данные — caveat про ограниченность данных (+OVB если ещё и
            # праздники исключены).
            caveat = ('Рекомендации ориентировочные: модель на ограниченных данных. '
                      'Опирайтесь на доверительные интервалы, а не точечные цифры; '
                      'крупные сдвиги бюджета валидируйте лифт-тестом.'
                      + (ovb_caveat if holidays_excluded else ''))
        else:
            # Данных достаточно, но праздники исключены — caveat именно про OVB
            # (не про «ограниченные данные», иначе вводит в заблуждение).
            caveat = ('Рекомендации ориентировочные: праздники РФ исключены из модели — '
                      'если категория сезонна к праздникам, вклад медиаканалов может быть '
                      'смещён (OVB). Крупные сдвиги бюджета валидируйте лифт-тестом.')
        return {
            'verdict': 'uncertain',
            'refused': False,
            'reasons': reasons,
            'caveat_text': caveat,
        }

    # ── reliable ──────────────────────────────────────────────────────────
    # Защита (аудит 2026-06-14): подтверждать надёжность можно только при наличии
    # реальных checks. Пустые checks (нестандартная/битая диагностика) → 'unknown',
    # не 'reliable' — иначе нечего подтверждать.
    if not checks:
        return {
            'verdict': 'unknown',
            'refused': False,
            'reasons': ['Диагностика модели неполна — надёжность не подтверждена.'],
            'caveat_text': ('Не удалось подтвердить надёжность модели (неполная '
                            'диагностика). Трактуйте рекомендации осторожно.'),
        }
    return {
        'verdict': 'reliable',
        'refused': False,
        'reasons': [],
        'caveat_text': '',
    }
