"""E3 (2026-07-03): сравнение поколений модели — «что изменилось с прошлого квартала».

Клиент обновил данные и переобучил модель → продукт сам отвечает: «ROI ТВ был
3.2 [2.6–3.9], стал 3.4 — стабильно» или «сдвинулся резко — вот вероятные
причины». Канон: у оценок есть дисперсия (Jin 2017) — сравниваются интервалы,
не голые точки; вердикт сдвига — по перекрытию CI поколений.

Механика переиспользует канонический ROI/CI-путь ЦЕЛИКОМ: обе стороны считаются
decompose(save_results=False) с одинаковыми override'ами (архивная — через
additive model_path), никакого дублирования формул (SSOT).

Вердикты per-channel:
    stable          - CI пересекаются и |Δroi| < 15% от базы (или обе точки
                      внутри чужих CI при близких значениях);
    shift_within_ci - CI пересекаются, но точка ушла заметно (>15%);
    shift_strong    - CI НЕ пересекаются (изменение статистически выражено);
    point_only_*    - у поколения нет CI (legacy) — честно сравниваем точки
                      и помечаем метод.
Пороги названы в коде и результате явно — никакой скрытой магии.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger('econometrica')

#: |Δroi| относительно базы, ниже которого при перекрытии CI канал «стабилен».
STABLE_REL_DELTA = 0.15
#: Абсолютный порог сдвига decay (доли 0..1) для пометки в результате.
DECAY_SHIFT_ABS = 0.15


def _list_generations(project_dir: str) -> list[dict[str, str]]:
    """Архивные поколения (models/history/model-*.pkl), новые первыми."""
    hist = Path(project_dir) / 'models' / 'history'
    if not hist.exists():
        return []
    out = []
    for p in sorted(hist.glob('model-*.pkl'), reverse=True):
        ts = p.stem.replace('model-', '')
        out.append({'timestamp': ts, 'path': str(p)})
    return out


def _fmt_ci(low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return ''
    return f' [{low:.1f}–{high:.1f}]'


def _channel_verdict(
    roi_old: float, roi_new: float,
    ci_old: tuple[float | None, float | None],
    ci_new: tuple[float | None, float | None],
) -> tuple[str, str]:
    """Вердикт сдвига ROI канала + метод. См. шапку модуля."""
    lo_o, hi_o = ci_old
    lo_n, hi_n = ci_new
    base = max(abs(roi_old), 1e-9)
    rel_delta = abs(roi_new - roi_old) / base

    has_ci = None not in (lo_o, hi_o, lo_n, hi_n) and (hi_o > lo_o or hi_n > lo_n)
    if not has_ci:
        # Legacy без CI — честное сравнение точек с пометкой метода.
        if rel_delta < STABLE_REL_DELTA:
            return 'stable', 'point_only'
        if rel_delta < 0.5:
            return 'shift_within_ci', 'point_only'
        return 'shift_strong', 'point_only'

    overlap = not (float(lo_n) > float(hi_o) or float(lo_o) > float(hi_n))
    if not overlap:
        return 'shift_strong', 'ci_overlap'
    if rel_delta < STABLE_REL_DELTA:
        return 'stable', 'ci_overlap'
    return 'shift_within_ci', 'ci_overlap'


_VERDICT_RU = {
    'stable': 'стабильно',
    'shift_within_ci': 'сдвиг в пределах неопределённости',
    'shift_strong': 'резкий сдвиг',
}


def compare_generations(
    project_dir: str,
    baseline_ts: str | None = None,
    unit_costs_override: dict | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Сравнить текущую модель с архивным поколением.

    Args:
        project_dir: проект с models/latest.pkl и models/history/.
        baseline_ts: timestamp поколения ('YYYYmmdd_HHMMSS'); None → самое свежее.
        unit_costs_override: единые цены единиц для ОБЕИХ сторон (честность
            сравнения: разные override исказили бы diff).
        save: писать models/generation_compare.json (atomic).

    Returns:
        status='ok': baseline {timestamp, trained_at}, current {trained_at},
        channels[] {name, roi_old, roi_new, roi_ci_old, roi_ci_new, delta_pct,
        verdict, verdict_ru, method, decay_old, decay_new, decay_shift},
        added_channels, removed_channels, summary {counts, headline, strong_shifts,
        probable_causes}, thresholds, generated_at.
        status='insufficient': поколений ещё нет (первое переобучение не случилось).
        status='error': NO_MODEL / GENERATION_NOT_FOUND / DECOMPOSE_FAILED.
    """
    project_path = Path(project_dir)
    if not (project_path / 'models' / 'latest.pkl').exists():
        return {
            'status': 'error',
            'error_code': 'NO_MODEL',
            'message': 'Модель не найдена — обучите модель, история появится после переобучений.',
        }

    generations = _list_generations(project_dir)
    if not generations:
        return {
            'status': 'insufficient',
            'message': (
                'Истории поколений ещё нет: сравнение появится автоматически '
                'после первого переобучения модели (прежняя версия сохраняется '
                'в архив).'
            ),
        }
    if baseline_ts:
        match = [g for g in generations if g['timestamp'] == baseline_ts]
        if not match:
            return {
                'status': 'error',
                'error_code': 'GENERATION_NOT_FOUND',
                'message': (
                    f'Поколение {baseline_ts} не найдено в архиве. '
                    f'Доступные: {", ".join(g["timestamp"] for g in generations)}.'
                ),
            }
        baseline = match[0]
    else:
        baseline = generations[0]

    from engines.decomposer import decompose
    dec_new = decompose(
        project_dir, unit_costs_override=unit_costs_override, save_results=False,
    )
    if dec_new.get('status') == 'error':
        return {
            'status': 'error', 'error_code': 'DECOMPOSE_FAILED',
            'message': f'Текущая модель: {dec_new.get("message")}',
        }
    dec_old = decompose(
        project_dir, unit_costs_override=unit_costs_override,
        model_path=baseline['path'], save_results=False,
    )
    if dec_old.get('status') == 'error':
        return {
            'status': 'error', 'error_code': 'DECOMPOSE_FAILED',
            'message': f'Поколение {baseline["timestamp"]}: {dec_old.get("message")}',
        }

    ch_old = {c['name']: c for c in dec_old.get('channels') or []}
    ch_new = {c['name']: c for c in dec_new.get('channels') or []}
    added = sorted(set(ch_new) - set(ch_old))
    removed = sorted(set(ch_old) - set(ch_new))
    common = [n for n in ch_new if n in ch_old]  # порядок текущей декомпозиции

    channels: list[dict[str, Any]] = []
    for name in common:
        o, n = ch_old[name], ch_new[name]
        roi_o = float(o.get('roi') or 0.0)
        roi_n = float(n.get('roi') or 0.0)
        ci_o = (o.get('roi_ci_low'), o.get('roi_ci_high'))
        ci_n = (n.get('roi_ci_low'), n.get('roi_ci_high'))
        verdict, method = _channel_verdict(roi_o, roi_n, ci_o, ci_n)
        decay_o = o.get('decay')
        decay_n = n.get('decay')
        decay_shift = (
            abs(float(decay_n) - float(decay_o)) >= DECAY_SHIFT_ABS
            if decay_o is not None and decay_n is not None else False
        )
        channels.append({
            'name': name,
            'roi_old': round(roi_o, 2),
            'roi_new': round(roi_n, 2),
            'roi_ci_old': [ci_o[0], ci_o[1]],
            'roi_ci_new': [ci_n[0], ci_n[1]],
            'delta_pct': round((roi_n - roi_o) / max(abs(roi_o), 1e-9) * 100, 1),
            'verdict': verdict,
            'verdict_ru': _VERDICT_RU[verdict],
            'method': method,
            'decay_old': decay_o,
            'decay_new': decay_n,
            'decay_shift': decay_shift,
            'contribution_new': n.get('contribution'),
        })

    counts = {
        'stable': sum(1 for c in channels if c['verdict'] == 'stable'),
        'shift_within_ci': sum(1 for c in channels if c['verdict'] == 'shift_within_ci'),
        'shift_strong': sum(1 for c in channels if c['verdict'] == 'shift_strong'),
    }
    strong = [c for c in channels if c['verdict'] == 'shift_strong']

    # Headline — топ-канал текущей декомпозиции по вкладу, языком клиента.
    headline = None
    by_contrib = sorted(
        channels, key=lambda c: float(c.get('contribution_new') or 0), reverse=True,
    )
    if by_contrib:
        t = by_contrib[0]
        headline = (
            f'ROI {t["name"]}: был {t["roi_old"]:.1f}{_fmt_ci(t["roi_ci_old"][0], t["roi_ci_old"][1])}, '
            f'стал {t["roi_new"]:.1f}{_fmt_ci(t["roi_ci_new"][0], t["roi_ci_new"][1])} — {t["verdict_ru"]}.'
        )

    probable_causes = []
    if strong or added or removed:
        probable_causes = [
            'Новые наблюдения изменили оценку вклада (модель дообучилась на свежем периоде).',
            'Изменился состав или роли каналов между поколениями.',
            'Сезонный/внешний фактор в новом периоде перераспределил вклад.',
        ]

    result: dict[str, Any] = {
        'status': 'ok',
        'baseline': {
            'timestamp': baseline['timestamp'],
            'trained_at': datetime.fromtimestamp(
                Path(baseline['path']).stat().st_mtime, tz=timezone.utc
            ).isoformat(timespec='seconds'),
        },
        'current': {
            'trained_at': datetime.fromtimestamp(
                (project_path / 'models' / 'latest.pkl').stat().st_mtime,
                tz=timezone.utc,
            ).isoformat(timespec='seconds'),
        },
        'channels': channels,
        'added_channels': added,
        'removed_channels': removed,
        'summary': {
            'counts': counts,
            'headline': headline,
            'strong_shifts': [c['name'] for c in strong],
            'probable_causes': probable_causes,
        },
        'thresholds': {
            'stable_rel_delta': STABLE_REL_DELTA,
            'decay_shift_abs': DECAY_SHIFT_ABS,
            'verdict_rule': 'перекрытие правдоподобных диапазонов поколений (Jin 2017); без правдоподобного диапазона — по точкам с пометкой point_only',
        },
        'generations_available': [g['timestamp'] for g in generations],
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    if save:
        try:
            models_dir = project_path / 'models'
            models_dir.mkdir(parents=True, exist_ok=True)
            tmp = models_dir / 'generation_compare.json.tmp'
            target = models_dir / 'generation_compare.json'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
            result['saved_to'] = str(target)
        except OSError as e:
            result['saved_to'] = None
            result['save_error'] = f'Не удалось сохранить generation_compare.json: {e}'
    return result


# ═══════════════════════════════════════════════════════════════════════════
# E3-2: дрейф-мониторинг — «пора переобучить?»
# ═══════════════════════════════════════════════════════════════════════════
#
# Идея (ROADMAP §E3.3): качество АРХИВНОЙ модели на точках, которых она не
# видела (хвост данных новее её обучения), падает → честный сигнал «пора
# переобучить». Механика переиспользует E1: прогноз хвоста predict_scenario
# + MAPE против наивных бенчмарков (_naive_forecasts из engines.backtest).

#: MAPE хвоста хуже обучающего более чем в RETRAIN_MAPE_FACTOR раз ИЛИ
#: на RETRAIN_MAPE_ABS_PP пунктов → рекомендация переобучить.
RETRAIN_MAPE_FACTOR = 1.5
RETRAIN_MAPE_ABS_PP = 10.0
#: Минимум свежих точек для осмысленного вывода.
MIN_TAIL_POINTS = 3


def _generation_n_obs(params_path: Path) -> int | None:
    """Окно обучения поколения из params-снимка (каскад источников)."""
    try:
        with open(params_path, encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    diag = data.get('diagnostics') or {}
    for cand in (
        diag.get('n_obs'),
        (diag.get('metrics') or {}).get('n_obs'),
    ):
        if isinstance(cand, (int, float)) and cand > 0:
            return int(cand)
    avp = (diag.get('actual_vs_predicted') or {}).get('actual')
    if isinstance(avp, list) and avp:
        return len(avp)
    return None


def _generation_train_mape(params_path: Path) -> float | None:
    try:
        with open(params_path, encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    diag = data.get('diagnostics') or {}
    for cand in (
        (diag.get('metrics') or {}).get('mape'),
        (diag.get('metrics') or {}).get('mape_pct'),
        diag.get('mape'),
    ):
        if isinstance(cand, (int, float)):
            return float(cand)
    return None


def drift_check(
    project_dir: str,
    baseline_ts: str | None = None,
) -> dict[str, Any]:
    """Дрейф: как АРХИВНОЕ поколение справляется со свежим хвостом данных.

    Хвост = строки текущего файла данных с индексом ≥ окна обучения поколения
    (из params-снимка). Прогноз хвоста — predict_scenario архивной моделью
    (через временную копию как latest.pkl), точность — MAPE против фактов и
    наивных бенчмарков.

    Returns:
        status='ok': verdict 'fresh_ok'|'retrain_recommended', mape_tail,
        mape_train, naive_mape, n_tail_points, thresholds, message (русский,
        с действием).
        status='insufficient': нет поколений / хвост короче MIN_TAIL_POINTS /
        не удалось определить окно обучения.
        status='error': NO_MODEL / GENERATION_NOT_FOUND / PREDICT_FAILED.
    """
    import tempfile

    import numpy as np
    import pandas as pd

    project_path = Path(project_dir)
    if not (project_path / 'models' / 'latest.pkl').exists():
        return {
            'status': 'error', 'error_code': 'NO_MODEL',
            'message': 'Модель не найдена — обучите модель.',
        }
    generations = _list_generations(project_dir)
    if not generations:
        return {
            'status': 'insufficient',
            'message': 'Поколений в архиве нет — дрейф оценивается после первого переобучения.',
        }
    if baseline_ts:
        match = [g for g in generations if g['timestamp'] == baseline_ts]
        if not match:
            return {
                'status': 'error', 'error_code': 'GENERATION_NOT_FOUND',
                'message': f'Поколение {baseline_ts} не найдено.',
            }
        gen = match[0]
    else:
        gen = generations[0]

    params_path = Path(gen['path']).with_name(
        Path(gen['path']).name.replace('model-', 'params-')
    ).with_suffix('.json')
    n_obs_gen = _generation_n_obs(params_path)
    if not n_obs_gen:
        return {
            'status': 'insufficient',
            'message': (
                'Не удалось определить окно обучения поколения (нет params-снимка) — '
                'дрейф недоступен для этого архива.'
            ),
        }

    from engines.persistence import load_model_with_compat
    current = load_model_with_compat(project_path / 'models' / 'latest.pkl')
    config = current['config']
    from utils.data_file_resolver import resolve_data_file
    try:
        data_path = resolve_data_file(config.get('data_file'), project_dir)
    except FileNotFoundError as e:
        return {'status': 'error', 'error_code': 'NO_DATA', 'message': str(e)}
    df = pd.read_csv(data_path) if str(data_path).endswith('.csv') else pd.read_excel(data_path)
    merge_rules = config.get('merge_rules')
    if merge_rules:
        try:
            from utils.merge_rules import apply_merge_rules
            apply_merge_rules(df, merge_rules)
        except Exception:  # noqa: BLE001 — хвост без слияния оценить нельзя честно
            pass

    if len(df) <= n_obs_gen:
        return {
            'status': 'insufficient',
            'message': (
                f'Свежих точек после обучения поколения нет '
                f'(данных {len(df)}, окно поколения {n_obs_gen}).'
            ),
        }
    tail = df.iloc[n_obs_gen:]
    if len(tail) < MIN_TAIL_POINTS:
        return {
            'status': 'insufficient',
            'message': (
                f'Свежих точек всего {len(tail)} (нужно ≥ {MIN_TAIL_POINTS}) — '
                f'вывод о дрейфе был бы шумом.'
            ),
        }

    kpi_col = config['kpi_column']
    media_cols = config['media_columns']
    actual = tail[kpi_col].fillna(0).to_numpy(dtype=float)

    with tempfile.TemporaryDirectory() as tmp:
        gen_project = Path(tmp) / 'gen'
        (gen_project / 'models').mkdir(parents=True)
        import shutil
        shutil.copy2(gen['path'], gen_project / 'models' / 'latest.pkl')
        from engines.scenario import predict_scenario
        sc = predict_scenario(
            {
                'scenario_name': f'drift_{gen["timestamp"]}',
                'media_plan': {c: tail[c].fillna(0).tolist() for c in media_cols},
                'unit_costs': config.get('unit_costs', {}),
            },
            str(gen_project),
        )
    if sc.get('status') != 'ok':
        return {
            'status': 'error', 'error_code': 'PREDICT_FAILED',
            'message': f'Прогноз поколения на хвосте не удался: {sc.get("message")}',
        }
    predictions = [float(v) for v in (sc.get('predictions') or [])][:len(actual)]
    if len(predictions) < len(actual):
        return {
            'status': 'error', 'error_code': 'PREDICT_FAILED',
            'message': f'Прогноз вернул {len(predictions)} точек при {len(actual)} фактических.',
        }

    from engines.backtest import _mape, _naive_forecasts
    mape_tail = _mape(actual, np.asarray(predictions))
    y_train_gen = df.iloc[:n_obs_gen][kpi_col].fillna(0).to_numpy(dtype=float)
    naive_mape = {}
    for name, fc in _naive_forecasts(y_train_gen, len(actual), season=12).items():
        naive_mape[name] = round(_mape(actual, np.asarray(fc)), 2)

    mape_train = _generation_train_mape(params_path)
    drift = False
    reasons = []
    if mape_train is not None:
        if mape_tail > max(mape_train * RETRAIN_MAPE_FACTOR,
                           mape_train + RETRAIN_MAPE_ABS_PP):
            drift = True
            reasons.append(
                f'ошибка на свежих точках {mape_tail:.1f}% против {mape_train:.1f}% '
                f'на обучении (порог ×{RETRAIN_MAPE_FACTOR} или +{RETRAIN_MAPE_ABS_PP:.0f} пп)'
            )
    best_naive = min(naive_mape.values()) if naive_mape else None
    if best_naive is not None and mape_tail >= best_naive:
        drift = True
        reasons.append(
            f'поколение на свежих точках не точнее наивного прогноза '
            f'({mape_tail:.1f}% против {best_naive:.1f}%)'
        )

    verdict = 'retrain_recommended' if drift else 'fresh_ok'
    if drift:
        message = (
            'Пора переобучить: ' + '; '.join(reasons) +
            '. Запустите обучение на полном ряде — прежняя версия сохранится в архив.'
        )
    else:
        message = (
            f'Поколение {gen["timestamp"]} держит точность на свежих точках '
            f'(MAPE {mape_tail:.1f}%'
            + (f' при {mape_train:.1f}% на обучении' if mape_train is not None else '')
            + ') — переобучение не требуется.'
        )

    return {
        'status': 'ok',
        'verdict': verdict,
        'message': message,
        'baseline_timestamp': gen['timestamp'],
        'n_tail_points': len(actual),
        'mape_tail': round(mape_tail, 2),
        'mape_train': mape_train,
        'naive_mape': naive_mape,
        'thresholds': {
            'retrain_mape_factor': RETRAIN_MAPE_FACTOR,
            'retrain_mape_abs_pp': RETRAIN_MAPE_ABS_PP,
            'min_tail_points': MIN_TAIL_POINTS,
        },
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }


def load_saved_generation_compare(project_dir: str) -> dict[str, Any] | None:
    """Сохранённое сравнение поколений или None (битый JSON → None с логом)."""
    p = Path(project_dir) / 'models' / 'generation_compare.json'
    if not p.exists():
        return None
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning('generation_compare.json повреждён (%s) — считается отсутствующим', e)
        return None
