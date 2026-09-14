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
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger('econometrica')

# Дивергенции считаются «несошедшейся» при превышении max(абс.пол, 1% черновиков).
# Абс. пол защищает от ложного refuse при малом числе черновиков (пара дивергенций
# на 30 наблюдениях — норма для NUTS, не катастрофа).
DIVERGENCE_REFUSE_FRAC = 0.01
DIVERGENCE_ABS_FLOOR = 20
RHAT_REFUSE_THRESHOLD = 1.05
WEAK_TIERS = ('weak', 'poor')

#: Вердикт, означающий отказ от рекомендаций по переброске. Строку сопоставления
#: держим здесь, а не россыпью по слоям представления: `refused` и `verdict`
#: обязаны совпадать по смыслу в любом читателе.
REFUSING_VERDICT = 'unreliable'


def verdict_refuses(verdict: str | None) -> bool:
    """True ⟺ вердикт означает отказ от рекомендаций.

    Слои представления (PPTX/HTML) видят не полный дикт `model_reliability`, а
    только поле-штамп `honesty_verdict` — сопоставление «unreliable ⟺ отказ»
    им приходилось делать самим. Одна точка сопоставления вместо трёх.
    """
    return (verdict or '').strip().lower() == REFUSING_VERDICT


def divergence_refuse_threshold(total_draws: int | None = None) -> int:
    """Порог дивергенций для отказа: max(абсолютный пол, 1% черновиков).

    Абс. пол защищает от ложного отказа при малом числе черновиков (пара
    дивергенций на 30 наблюдениях — норма для NUTS, не катастрофа). Без
    известного числа черновиков остаётся только пол.
    """
    try:
        draws = int(total_draws or 0)
    except (TypeError, ValueError):
        draws = 0
    if draws <= 0:
        return DIVERGENCE_ABS_FLOOR
    return max(DIVERGENCE_ABS_FLOOR, int(DIVERGENCE_REFUSE_FRAC * draws))


def model_did_not_converge(r_hat_max: float | None, divergences: int | None,
                           total_draws: int | None = None) -> bool:
    """Единый предикат отказа: расчёт не сошёлся (ветка `unreliable` ниже).

    🔴 Заведён 2026-08-09. Ветка отказа `model_reliability_verdict` и текст
    вердикта модели в `utils/diagnostics.generate_diagnostics_summary` жили на
    двух РАЗНЫХ основаниях: первая смотрела на сходимость, вторая — только на
    ступень MQS и тонкость данных. При `r_hat=1.06` и нуле расхождений клиент
    получал в одном документе «рекомендации по переброске бюджета отключены» и
    «Надёжный результат для принятия бюджетных решений». Теперь основание одно
    и физически общее — и вердикт, и текст зовут эту функцию.

    Порог по дивергенциям зависит от числа черновиков, поэтому `total_draws`
    передавать обязательно всюду, где оно известно: без него порог падает до
    абсолютного пола (20) и на длинных цепях получится ЛОЖНЫЙ отказ.
    """
    try:
        r_hat = float(r_hat_max or 0.0)
    except (TypeError, ValueError):
        r_hat = 0.0
    try:
        div = int(divergences or 0)
    except (TypeError, ValueError):
        div = 0
    return r_hat >= RHAT_REFUSE_THRESHOLD or div > divergence_refuse_threshold(total_draws)


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
            'reasons': ['Диагностика модели недоступна – надёжность не проверена.'],
            'caveat_text': ('Не удалось проверить надёжность модели (нет диагностики). '
                            'Трактуйте рекомендации осторожно.'),
        }

    metrics = diagnostics.get('metrics') or {}
    checks = diagnostics.get('checks') or {}
    mqs = diagnostics.get('mqs') or {}
    engine = (diagnostics.get('engine') or '').lower()

    # Мат-аудит 2026-07-02 (F-20): сбой реконструкции y_pred → R²/MAPE считались
    # от константы (нулевой прогноз) — метрики НЕ отражают модель. Честный
    # вердикт — unknown («качество не измерено»), не «модель плохая/хорошая».
    if diagnostics.get('y_pred_reconstruction_failed'):
        return {
            'verdict': 'unknown',
            'refused': False,
            'reasons': ['Сбой реконструкции прогноза при обучении – метрики '
                        'качества (R², MAPE) вычислены от вырожденного прогноза '
                        'и не отражают модель.'],
            'caveat_text': ('Диагностика модели деградировала (сбой реконструкции '
                            'прогноза) – качество не измерено. Переобучите модель; '
                            'если повторяется – сообщите в поддержку.'),
        }

    # OVB-маркер (аудит 2026-06-14): праздники РФ принудительно исключены
    # (use_holidays=False). Если категория сезонна к праздникам — модель смещена
    # (omitted-variable bias), и «надёжной» её называть нельзя (отсутствие эффекта мы
    # подтвердить не можем). Маркер ставит modeler.py/ols_modeler.py при обучении.
    holidays_excluded = bool(diagnostics.get('holidays_excluded'))
    ovb_reason = ('Праздники РФ исключены из модели: если категория сезонна к праздникам, '
                  'вклад медиаканалов может быть смещён (omitted-variable bias). Убедитесь, '
                  'что спрос категории к праздникам нечувствителен.')
    ovb_caveat = ' Праздники исключены – возможен OVB, если категория сезонна.'

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
                   f'(не обучаются), правдоподобные диапазоны частотные – рекомендации '
                   f'ориентировочные.']
        caveat = ('Режим малых данных (OLS): рекомендации ориентировочные, опирайтесь на '
                  'правдоподобные диапазоны и валидируйте крупные сдвиги лифт-тестом.')
        if holidays_excluded:
            reasons.append(ovb_reason)
            caveat += ovb_caveat
        return {'verdict': 'uncertain', 'refused': False,
                'reasons': reasons, 'caveat_text': caveat}

    r_hat = float(metrics.get('r_hat_max') or 0.0)
    divergences = int(metrics.get('divergences') or 0)
    ratio = metrics.get('ratio')
    tier = (mqs.get('tier') or '').lower()
    tier_label = mqs.get('tier_label') or tier or '–'
    score = mqs.get('score')

    total_draws = _total_draws(metrics)
    # Порог и сам предикат отказа — из общих функций выше: тем же основанием
    # пользуется текст вердикта модели (utils/diagnostics), поэтому расхождение
    # двух шкал (отказ против «надёжный результат») стало невозможным.
    div_thresh = divergence_refuse_threshold(total_draws)

    reasons: list[str] = []

    # ── unreliable (отказ) ────────────────────────────────────────────────
    bad_rhat = r_hat >= RHAT_REFUSE_THRESHOLD
    bad_div = divergences > div_thresh
    if bad_rhat:
        reasons.append(
            f'Модель не сошлась (R-hat {r_hat:.3f} ≥ {RHAT_REFUSE_THRESHOLD}) – '
            f'переброска не строится на несошедшейся модели.')
    if bad_div:
        reasons.append(
            f'{divergences} дивергенций MCMC (> порога {div_thresh}) – сэмплер не '
            f'исследовал часть пространства параметров; результаты ненадёжны.')
    if bad_rhat or bad_div:
        return {
            'verdict': 'unreliable',
            'refused': True,
            'reasons': reasons,
            'caveat_text': ('Модель не завершила расчёт корректно – рекомендации по '
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
        # Тон по McElreath (гл. 9, regularizing priors): при малой выборке
        # байес НЕ «ломается» — информативные priors регуляризуют, стягивая
        # оценки к разумному диапазону, а широкие диапазоны честно отражают
        # неопределённость. Формулируем сдержанность, а не «переобучение/поломку».
        ratio_txt = f' (Ratio {ratio}:1 < 4:1)' if ratio is not None else ''
        reasons.append(
            f'Ограниченные данные{ratio_txt}: модель намеренно сдержана – опирается '
            f'на априорные отраслевые знания (priors), поэтому точечные оценки '
            f'стянуты к разумному диапазону, а правдоподобные диапазоны широкие. Это '
            f'честное отражение неопределённости, а не ошибка; с ростом массива '
            f'диапазоны сузятся. Особенно осторожно с аномально высокими mROAS.')
    if weak_tier:
        score_txt = f' (MQS {score})' if score is not None else ''
        reasons.append(f'Низкое качество модели{score_txt}, «{tier_label}».')
    if mild_div:
        reasons.append(
            f'{divergences} дивергенц(ий) MCMC – лёгкая нестабильность сэмплера, '
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
            f'(Vehtari et al. 2021) – цепи перемешаны слабо, при таком ESS сам '
            f'R-hat ненадёжен; правдоподобные диапазоны ориентировочны.')
    if low_bfmi:
        _bf = metrics.get('bfmi_min')
        _bf_txt = f' {_bf:.2f}' if _bf is not None else ''
        reasons.append(
            f'E-BFMI{_bf_txt} < 0.3 (эвристика Stan/PyMC) – сэмплер плохо '
            f'исследует хвосты распределения энергии; результаты менее надёжны '
            f'(обычно лечится non-centered параметризацией).')
    if prior_pred_fail:
        reasons.append(
            'Prior predictive check: fail – априорные допущения модели дают '
            'неправдоподобный диапазон продаж ещё до данных (симуляция из priors); '
            'оценки могут определяться приором, а не данными – трактуйте '
            'рекомендации осторожно.')
    data_uncertain = thin or weak_tier or mild_div or low_ess or low_bfmi or prior_pred_fail
    if data_uncertain or holidays_excluded:
        if holidays_excluded:
            reasons.append(ovb_reason)
        if data_uncertain:
            # Тонкие/слабые данные — caveat про ограниченность данных (+OVB если ещё и
            # праздники исключены). При тонких данных тон по McElreath: модель не
            # «сломана», а сдержана и опирается на priors (диапазоны честно широкие).
            prior_note = (' На ограниченных данных модель опирается на априорные '
                          'отраслевые знания и сдержана – это снижает риск '
                          'переобучения.') if thin else ''
            caveat = ('Рекомендации ориентировочные: модель на ограниченных данных. '
                      'Опирайтесь на правдоподобные диапазоны, а не точечные цифры; '
                      'крупные сдвиги бюджета валидируйте лифт-тестом.' + prior_note
                      + (ovb_caveat if holidays_excluded else ''))
        else:
            # Данных достаточно, но праздники исключены — caveat именно про OVB
            # (не про «ограниченные данные», иначе вводит в заблуждение).
            caveat = ('Рекомендации ориентировочные: праздники РФ исключены из модели – '
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
            'reasons': ['Диагностика модели неполна – надёжность не подтверждена.'],
            'caveat_text': ('Не удалось подтвердить надёжность модели (неполная '
                            'диагностика). Трактуйте рекомендации осторожно.'),
        }
    return {
        'verdict': 'reliable',
        'refused': False,
        'reasons': [],
        'caveat_text': '',
    }


def stamp_reliability(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Проставить вердикт надёжности в диагностику — ПОСЛЕДНИМ действием перед записью.

    🔴 Вызывать ТОЛЬКО на границе записи `results/model-diagnostics.json`, когда
    словарь диагностики собран целиком. Причина — проверенный дефект 2026-08-07:
    `modeler.py` штамповал вердикт на 413 строк РАНЬШЕ, чем клал в ту же
    диагностику признак `holidays_excluded` (modeler.py:1851). В файл уезжали оба
    поля сразу: верный признак и вердикт, посчитанный так, будто праздники не
    исключали. Кто пересчитывал от файла (оптимизатор, мост отчётов) — получал
    честный 'uncertain' с причиной про смещение; кто читал штамп (экраны
    «Декомпозиция» и «Оптимизация» до запуска) — получал 'reliable', то есть
    плашку не рисовал вовсе. Ошибка была направлена в НЕДОпредупреждение, против
    чего честностный гейт INV-50 и существует.

    Второй путь устаревания того же штампа: `tools/recompute_mqs.py` пересчитывал
    `mqs`/`checks`, но `honesty_verdict` не трогал — файл становился внутренне
    противоречивым.

    Отсюда правило: штамп — не шаг обучения, а свойство записи. Любой писатель
    диагностики обязан пройти через эту функцию последним действием.

    Идемпотентна на непустом словаре: `model_reliability_verdict` читает только
    `metrics`, `checks`, `mqs`, `engine`, `preflight`, `holidays_excluded`,
    `y_pred_reconstruction_failed`, `n_obs`/`n_params` — собственные поля штампа
    на её ветки не влияют, повторный вызов даёт тот же результат.

    🔴 ПУСТОЙ словарь не штампуем вовсе, и это не мелочь: сам факт простановки
    полей сделал бы его непустым, и повторный вызов ушёл бы в другую ветку —
    «диагностика неполна» вместо «диагностики нет». Хранимое значение перестало
    бы совпадать с вычисляемым, то есть ровно то, ради чего единый источник и
    заводится. Описывать нечего — пусть читатели вычислят «неизвестно» сами
    (мост это умеет, `narrative_adapter` и `sections.py`). У писателей движка
    диагностика пустой не бывает, так что в бою это ничего не меняет.

    Args:
        diagnostics: полностью собранный словарь диагностики. Изменяется на месте.

    Returns:
        Тот же словарь (для сцепления вызовов).
    """
    if not diagnostics:
        return diagnostics
    try:
        verdict = model_reliability_verdict(diagnostics)
    except Exception as err:  # noqa: BLE001
        # Сохраняем прежнее поведение обоих движков: сбой честностного контура НЕ
        # роняет обучение — модель уже сохранена на диск. Вердикт при этом честно
        # объявляется непроверенным, а не выдуманным.
        logger.warning('stamp_reliability: вердикт не посчитан (%s)', err)
        verdict = {
            'verdict': 'unknown',
            'refused': False,
            'reasons': ['Сбой при вычислении вердикта надёжности – надёжность не проверена.'],
            'caveat_text': ('Не удалось проверить надёжность модели. '
                            'Трактуйте рекомендации осторожно.'),
        }
    # Полный дикт — то, что читают Rust-отчёты и мост: вердикт, отказ, причины,
    # текст оговорки. Раньше на диск попадали только два поля из четырёх, и
    # `caveat_text` приходилось пере-выводить на каждой стороне заново.
    diagnostics['model_reliability'] = verdict
    # Совместимость: эти два поля читают экраны продукта и запасной путь HTML —
    # `DecomposeStep.svelte:250`, `OptimizeStep.svelte:387`, `sections.py:437`.
    diagnostics['honesty_verdict'] = verdict.get('verdict', 'unknown')
    # Присваиваем ВСЕГДА, в том числе пустым списком: штамп теперь ставится
    # повторно (после пересчёта MQS), и уцелевшие причины прошлого вердикта
    # рассказывали бы клиенту о проблеме, которой уже нет.
    diagnostics['honesty_reasons'] = [str(r) for r in (verdict.get('reasons') or [])][:3]
    return diagnostics


# ─── Порог значимости переброски: единственная величина на всю программу ──────
# Дефект s48 (14.09.2026, Projects/THRESHOLDS_s48.md): у HTML-отчёта и колоды
# был РАЗНЫЙ порог, ниже которого переброска бюджета считается незначимой —
# 0,5 млн ₽ в отчёте (и на части слайдов колоды), 1,0 млн ₽ на остальных слайдах
# той же колоды (`aurora_pptx/builder.py` дважды явным `min_mln=1.0` плюс четыре
# литерала `>= 1`, `engines/narrative_adapter.py` — ещё раз явным `min_mln=1.0`).
# На сумме между порогами (проверено сценарием на 0,7 млн) ОДНА И ТА ЖЕ колода
# на соседних слайдах говорила разное: слайд «Главное» — «перераспределить
# 0,7 млн из X в Y», слайд SCQAR — «сохранить текущую аллокацию, насыщение
# каналов». Расхождение унаследовано от двух независимых правил, существовавших
# до `reallocation_subjects` (заведена в s47 для другого дефекта — выбора СТОРОН
# переброски, — но исторический порог каждой стороны перенесла как есть).
# Выбор порога — 0,5, а не 1,0: это порог отчёта, единственного документа,
# который клиент открывает всегда; поднять его до 1 млн значит замолчать
# переброски 0,5–1 млн, которые отчёт сегодня честно называет.
#
# `reallocation_subjects` параметра `min_mln` больше не принимает (убран s48):
# пока он существовал со значением по умолчанию, любой новый вызов физически
# мог передать своё число — ровно так недосмотром и завёлся этот дефект.
# Единственный источник порога — константа ниже; звать функцию без аргументов
# кроме `facts`.
SIGNIFICANT_REALLOCATION_MLN = 0.5


# ─── Формат суммы переброски: единственная функция на всю программу ───────────
# Дефект s48 (14.09.2026, Projects/AUDIT_s48_external.md): порог значимости
# свели к 0,5 млн, а все места печати суммы остались с округлением `:.0f` —
# зона 0,5-1,0 млн, которую раньше отсекал старый порог 1,0 и туда попросту
# не доходило, теперь печатается абсурдом: 0,5 -> «0 млн» (совет переложить
# ноль), 0,6 и 0,7 -> «1 млн» (завышение расчёта на 67 %). Один источник
# формата рядом с порогом значимости — чтобы оба менялись согласованно и
# новое место печати не смогло завести свой `:.0f`.
def format_realloc_mln(amount_mln: float) -> str:
    """Сумма переброски для клиентского текста — без слова «млн» и валюты.

    Правило: до 10 млн — один знак после запятой, но только если он после
    округления не нулевой (0.5 -> «0,5», 1.4 -> «1,4», но 1.0 -> «1», а не
    «1,0» — целая сумма переброски встречается чаще дробной, и «1,0» на
    клиентском экране читается как след округления машины, а не как
    рекомендация; правка 2026-09-14 по замечанию владельца). От 10 и выше —
    целое (десятые не читаемы на фоне крупной суммы). Разделитель — запятая
    (текст русский), не точка.
    """
    try:
        amount = float(amount_mln)
    except (TypeError, ValueError):
        amount = 0.0
    if amount < 10:
        rounded = round(amount, 1)
        if rounded == int(rounded):
            return f"{int(rounded)}"
        return f"{rounded:.1f}".replace('.', ',')
    return f"{amount:.0f}"


# ─── Стороны переброски бюджета: единственное правило на всю программу ────────
# Дефект s47 (14.09.2026): одна и та же сумма 878 млн ₽ уезжала клиенту трижды с
# РАЗНЫМИ источниками — сводка первой страницы говорила «из Онлайн-видео» (лидер
# по вкладу), а «РЕКОМЕНДАЦИЯ» и резюме — «из Наружной рекламы» (кого режет
# оптимизатор). Читатель начинает с первой страницы, то есть первым он читал
# неверный канал, да ещё и противоречащий выводу строкой ниже: Онлайн-видео даёт
# 45 % вклада при 34 % бюджета, забирать из него — совет наоборот.
# Корень: два места судили по разным правилам. Лечится не подгонкой одного места,
# а одним правилом выбора для ВСЕХ документов — эта функция и есть правило.
def reallocation_subjects(facts: dict | None) -> dict:
    """Кто отдаёт бюджет и кто получает — единый ответ для HTML, презентации и экрана.

    Правило:
      - источник = `cut_source_channel` (канал, который оптимизатор РЕЖЕТ);
      - получатель = `scale_destination_channel` (канал, который он НАРАЩИВАЕТ);
      - `leader_channel` (лидер по вкладу) источником не является НИКОГДА — это
        ответ на другой вопрос («кто больше всех дал»), и он свободно попадает в
        число получателей;
      - если источник не назван — про переброску «из» не говорим вовсе, называем
        только получателя («нарастить N»). Промолчать честнее, чем назвать канал,
        который оптимизатор не трогал.

    Args:
        facts: `narrative_facts` из narrative_adapter (может быть None/пустым).

    Returns:
        dict:
          kind — 'rebalance' (есть обе стороны) | 'scale_only' | 'cut_only' | 'none';
          cut_source — имя канала-источника или None;
          scale_destination — имя канала-получателя или None;
          amount_mln — сумма переброски, млн ₽ (0.0 если её нет).
    """
    f = facts or {}
    try:
        amount = float(f.get('reallocation_mln') or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if not (amount >= SIGNIFICANT_REALLOCATION_MLN):  # NaN тоже сюда — сторон нет
        return {'kind': 'none', 'cut_source': None,
                'scale_destination': None, 'amount_mln': 0.0}

    cut_source = f.get('cut_source_channel') or None
    scale_destination = f.get('scale_destination_channel') or None
    if cut_source and scale_destination:
        kind = 'rebalance'
    elif scale_destination:
        kind = 'scale_only'
    elif cut_source:
        kind = 'cut_only'
    else:
        kind = 'none'
        amount = 0.0
    return {'kind': kind, 'cut_source': cut_source,
            'scale_destination': scale_destination, 'amount_mln': amount}
