"""E4 (2026-07-03): рекомендации-обещания — замыкание петли доверия.

Каждая рекомендация продукта («сдвиньте бюджет → ожидаем +Z [интервал]»)
фиксируется как ПРОВЕРЯЕМОЕ ОБЕЩАНИЕ: дата, действие, ожидание с CI, срок
проверки. Когда клиент приносит свежие данные, продукт САМ сверяет факт
с ожиданием и честно отвечает «сбылось / не сбылось / данных ещё мало».

Честность:
- ожидание с широким CI и пометкой экстраполяции остаётся с этими пометками
  в обещании (не обещаем за пределами данных);
- сверка «факт внутри интервала ожидания» — это проверка ПРОГНОЗА, не
  каузальный вывод: внешние факторы могли двигать KPI — текст вердикта
  оговаривает это явно.
Хранение: results/promises.json (atomic, fsync).
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger('econometrica')

_STATUS_RU = {
    'pending': 'ожидает данных',
    'kept': 'сбылось',
    'missed': 'не сбылось',
    'inconclusive': 'неубедительно',
}


def _promises_path(project_dir: str) -> Path:
    return Path(project_dir) / 'results' / 'promises.json'


def _load(project_dir: str) -> list[dict[str, Any]]:
    p = _promises_path(project_dir)
    if not p.exists():
        return []
    try:
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        logger.warning('promises.json повреждён (%s) — считается пустым', e)
        return []


def _save(project_dir: str, promises: list[dict[str, Any]]) -> str:
    results_dir = Path(project_dir) / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)
    tmp = results_dir / 'promises.json.tmp'
    target = results_dir / 'promises.json'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(promises, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)
    return str(target)


def _current_n_obs(project_dir: str) -> int | None:
    """Число наблюдений в ТЕКУЩЕМ файле данных проекта (через резолвер C3-N3)."""
    try:
        import pandas as pd
        from engines.persistence import load_model_with_compat
        from utils.data_file_resolver import resolve_data_file
        model = load_model_with_compat(Path(project_dir) / 'models' / 'latest.pkl')
        data_path = resolve_data_file(model['config'].get('data_file'), project_dir)
        df = (pd.read_csv(data_path) if str(data_path).endswith('.csv')
              else pd.read_excel(data_path))
        return len(df)
    except Exception as e:  # noqa: BLE001 — обещания не должны падать из-за данных
        logger.warning('promises: не удалось определить n_obs данных: %s', e)
        return None


def create_promise(
    project_dir: str,
    *,
    action_text: str,
    expected_kpi_total: float,
    ci_low: float | None,
    ci_high: float | None,
    horizon_periods: int,
    channel_changes: dict[str, float] | None = None,
    extrapolation_flag: bool = False,
    source: str = 'optimize',
) -> dict[str, Any]:
    """Зафиксировать рекомендацию как проверяемое обещание.

    check_after_index = длина данных НА МОМЕНТ обещания: сверка пойдёт по
    строкам, пришедшим ПОСЛЕ (свежий факт, который модель не видела).
    """
    if horizon_periods < 1:
        return {
            'status': 'error', 'error_code': 'BAD_HORIZON',
            'message': 'Срок проверки должен быть ≥ 1 периода.',
        }
    if not action_text or not str(action_text).strip():
        return {
            'status': 'error', 'error_code': 'EMPTY_ACTION',
            'message': 'Обещание без действия не имеет смысла — опишите рекомендацию.',
        }
    n_obs = _current_n_obs(project_dir)
    if n_obs is None:
        return {
            'status': 'error', 'error_code': 'NO_DATA',
            'message': (
                'Не удалось прочитать данные проекта — обещание нельзя привязать '
                'к точке отсчёта. Проверьте файл данных.'
            ),
        }
    promise = {
        'id': uuid.uuid4().hex[:12],
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source': source,
        'action_text': str(action_text).strip(),
        'channel_changes': channel_changes or {},
        'expected': {
            'kpi_total': float(expected_kpi_total),
            'ci_low': float(ci_low) if ci_low is not None else None,
            'ci_high': float(ci_high) if ci_high is not None else None,
            'horizon_periods': int(horizon_periods),
        },
        'extrapolation_flag': bool(extrapolation_flag),
        'check_after_index': int(n_obs),
        'status': 'pending',
        'status_ru': _STATUS_RU['pending'],
        'checked_at': None,
        'actual_kpi_total': None,
        'verdict_note': None,
    }
    promises = _load(project_dir)
    promises.append(promise)
    _save(project_dir, promises)
    return {'status': 'ok', 'promise': promise, 'total': len(promises)}


def list_promises(project_dir: str) -> dict[str, Any]:
    promises = _load(project_dir)
    return {'status': 'ok', 'promises': promises, 'total': len(promises)}


def check_promises(project_dir: str) -> dict[str, Any]:
    """Сверить все обещания со свежим фактом (строки данных после точки отсчёта).

    kept   — факт внутри интервала ожидания;
    missed — вне интервала (текст оговаривает: прогноз, не каузальный вывод);
    inconclusive — интервала у ожидания не было (сверка точки бессмысленна);
    pending — свежих периодов ещё меньше срока проверки.
    """
    import pandas as pd
    from engines.persistence import load_model_with_compat
    from utils.data_file_resolver import resolve_data_file

    promises = _load(project_dir)
    if not promises:
        return {'status': 'ok', 'promises': [], 'total': 0, 'checked': 0}

    model_path = Path(project_dir) / 'models' / 'latest.pkl'
    if not model_path.exists():
        return {
            'status': 'error', 'error_code': 'NO_MODEL',
            'message': 'Модель не найдена — сверка обещаний требует проект с данными.',
        }
    model = load_model_with_compat(model_path)
    config = model['config']
    try:
        data_path = resolve_data_file(config.get('data_file'), project_dir)
    except FileNotFoundError as e:
        return {'status': 'error', 'error_code': 'NO_DATA', 'message': str(e)}
    df = (pd.read_csv(data_path) if str(data_path).endswith('.csv')
          else pd.read_excel(data_path))
    merge_rules = config.get('merge_rules')
    if merge_rules:
        try:
            from utils.merge_rules import apply_merge_rules
            apply_merge_rules(df, merge_rules)
        except Exception:  # noqa: BLE001
            pass
    kpi_col = config['kpi_column']
    if kpi_col not in df.columns:
        return {
            'status': 'error', 'error_code': 'NO_DATA',
            'message': f'В данных нет колонки KPI «{kpi_col}» — сверка невозможна.',
        }
    y = df[kpi_col].fillna(0).to_numpy(dtype=float)

    checked = 0
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    for p in promises:
        if p.get('status') in ('kept', 'missed'):
            continue  # окончательные вердикты не пересматриваем
        start = int(p.get('check_after_index') or 0)
        horizon = int((p.get('expected') or {}).get('horizon_periods') or 0)
        fresh = y[start:start + horizon]
        if len(fresh) < horizon:
            p['status'] = 'pending'
            p['status_ru'] = _STATUS_RU['pending']
            p['verdict_note'] = (
                f'Свежих периодов {len(fresh)} из {horizon} — обновите данные, '
                f'и продукт сверит обещание сам.'
            )
            continue
        actual = float(fresh.sum())
        p['actual_kpi_total'] = round(actual, 2)
        p['checked_at'] = now
        checked += 1
        exp = p.get('expected') or {}
        lo, hi = exp.get('ci_low'), exp.get('ci_high')
        if lo is None or hi is None:
            p['status'] = 'inconclusive'
            p['status_ru'] = _STATUS_RU['inconclusive']
            p['verdict_note'] = (
                'У ожидания не было интервала — точечная сверка неубедительна.'
            )
            continue
        if float(lo) <= actual <= float(hi):
            p['status'] = 'kept'
            p['status_ru'] = _STATUS_RU['kept']
            p['verdict_note'] = (
                f'Факт {actual:,.0f} попал в обещанный интервал '
                f'[{float(lo):,.0f} – {float(hi):,.0f}].'
            ).replace(',', ' ')
        else:
            p['status'] = 'missed'
            p['status_ru'] = _STATUS_RU['missed']
            p['verdict_note'] = (
                f'Факт {actual:,.0f} вне обещанного интервала '
                f'[{float(lo):,.0f} – {float(hi):,.0f}]. Это сверка прогноза, '
                f'не каузальный вывод: на KPI могли влиять внешние факторы — '
                f'разберите период с аналитиком.'
            ).replace(',', ' ')
    _save(project_dir, promises)
    return {'status': 'ok', 'promises': promises, 'total': len(promises), 'checked': checked}
