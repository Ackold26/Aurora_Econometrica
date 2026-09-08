"""Застрявший решатель обязан объясняться честно (аудит 2026-09-08, Critical).

Правка 2026-09-07 объясняла нулевой прирост тем, что «будущих периодов нет —
перераспределять пока нечего». Зонд на базовом образце `static/sample-data/
synth_fmcg_brand.xlsx` (без хвоста плана) это опроверг: в аналитическом режиме
задача перераспределения поставлена корректно — money_target = 1 077 835 510 ₽,
четыре канала, коридор 20/200 непустой, бюджет строго внутри, — и прямым счётом
целевой функции по 4 056 допустимым распределениям нашлось лучшее текущего
(f: -95,5610429019 → -96,5801986629). Значит перераспределять ЕСТЬ что, а
нулевой прирост означает ровно одно: решатель улучшения не нашёл.

Сторожим слой, где живёт истина, — текст, который отдаёт сам оптимизатор:
  (а) плана нет,  решатель встал  → «не нашёл распределения лучше текущего»;
  (б) план есть,  решатель встал  → тот же текст (наличие плана роли не играет);
  (в) план есть,  решатель дал прирост → обычный текст перераспределения;
  (г) плана нет И запрошен горизонт планирования → и только тут добавляется
      просьба дописать строки будущих периодов.
Ни в одном случае не воскресает совет «расширьте границы 10/300 %»: он
опровергнут замером (0,0 % и на 20/200, и на 10/300, и на 0/500).

Прогон:
    cd sidecar/econometrica && pytest ../../tools/test_optimizer_stalled_insight.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / 'sidecar'
for _p in (str(REPO / 'tools'), str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _optimizer_fixtures import build_synthetic_pickle  # noqa: E402

# Узкий коридор 99/101 % оставляет решателя на текущем распределении, но НЕ
# упирает все каналы в границы: `converged_at_current=True`, `binding=False` —
# ровно та ветка, где жила ложная причина. Проверено прогоном на двух семенах.
_STALL_BOUNDS = {'min_pct': 99, 'max_pct': 101}
_WIDE_BOUNDS = {'min_pct': 20, 'max_pct': 200}

_STALLED_PHRASE = 'не нашёл распределения лучше текущего'
_FUTURE_PHRASE = 'будущих периодов'


def _project(tmp_path: Path, name: str, n_future_periods: int | None) -> str:
    """Проект с синтетической моделью и заданным состоянием медиаплана.

    `n_future_periods`: 0 — данные проверены, хвоста нет; >0 — план есть;
    None — файла нет вовсе («определить не удалось»).
    """
    proj = tmp_path / name
    build_synthetic_pickle(proj, seed=7, n_channels=3, n_periods=31)
    results = proj / 'results'
    results.mkdir(parents=True, exist_ok=True)
    if n_future_periods is not None:
        payload = {
            'n_future_periods': n_future_periods,
            'channels': [],
            'confirmed': False,
        }
        (results / 'media_plan.json').write_text(
            json.dumps(payload, ensure_ascii=False), encoding='utf-8'
        )
    return str(proj)


def _optimize(project_dir: str, **cfg) -> dict:
    from engines.optimizer import optimize
    base = {'total_budget': None}
    base.update(cfg)
    return optimize(base, project_dir)


def test_stalled_without_media_plan_blames_the_solver(tmp_path: Path):
    """(а) Плана нет, решатель встал — причина названа честно."""
    proj = _project(tmp_path, 'no_plan', 0)
    res = _optimize(proj, **_STALL_BOUNDS)

    assert res['status'] == 'ok', res
    assert res['converged_at_current'] is True, 'ветка застрявшего решателя не сработала'
    assert res['media_plan_absent'] is True
    insight = res['insight']
    assert _STALLED_PHRASE in insight, insight
    assert _FUTURE_PHRASE not in insight, (
        'вернулась опровергнутая причина «перераспределять нечего»: ' + insight
    )
    assert '10/300' not in insight and 'расширить границы' not in insight.lower(), insight


def test_stalled_with_media_plan_says_the_same(tmp_path: Path):
    """(б) План есть, решатель встал — текст не зависит от наличия плана."""
    proj = _project(tmp_path, 'with_plan', 8)
    res = _optimize(proj, **_STALL_BOUNDS)

    assert res['converged_at_current'] is True
    assert res['media_plan_absent'] is False
    insight = res['insight']
    assert _STALLED_PHRASE in insight, insight
    assert _FUTURE_PHRASE not in insight, insight


def test_lift_found_keeps_normal_narrative(tmp_path: Path):
    """(в) План есть, решатель дал прирост — ветка застрявшего не перехватывает."""
    proj = _project(tmp_path, 'lift', 8)
    res = _optimize(proj, **_WIDE_BOUNDS)

    assert res['converged_at_current'] is False, res.get('expected_lift_pct')
    assert res['expected_lift_pct'] > 0
    insight = res['insight']
    assert _STALLED_PHRASE not in insight, insight
    assert _FUTURE_PHRASE not in insight, insight
    assert 'прирост' in insight


def test_future_periods_hint_only_when_planning_requested(tmp_path: Path):
    """(г) Плана нет И запрошен горизонт планирования — подсказка уместна."""
    proj = _project(tmp_path, 'planning_no_plan', 0)
    res = _optimize(proj, forecast_periods=31, **_STALL_BOUNDS)

    assert res['status'] == 'ok', res
    assert res['planning_mode'] is True
    assert res['media_plan_absent'] is True
    assert res['converged_at_current'] is True, res.get('expected_lift_pct')
    insight = res['insight']
    assert _STALLED_PHRASE in insight, 'честная причина вытеснена подсказкой: ' + insight
    assert _FUTURE_PHRASE in insight, insight


def test_media_plan_state_is_three_valued(tmp_path: Path):
    """Признак различает три состояния: план есть / плана нет / не знаю.

    Третье состояние — не украшение: до правки отсутствие файла при наличии
    validation.json трактовалось как «плана нет», и проглоченный сбой записи
    превращался в уверенное «будущих периодов нет» на данных, где план есть.
    """
    from engines.optimizer import media_plan_absent

    assert media_plan_absent(_project(tmp_path, 'st_absent', 0)) is True
    assert media_plan_absent(_project(tmp_path, 'st_present', 5)) is False
    assert media_plan_absent(_project(tmp_path, 'st_unknown', None)) is None

    # Файл есть, но проверка данных не смогла определить хвост — тоже «не знаю».
    proj = Path(_project(tmp_path, 'st_undetected', 0))
    (proj / 'results' / 'media_plan.json').write_text(
        json.dumps({'n_future_periods': None, 'detection': 'unavailable'}, ensure_ascii=False),
        encoding='utf-8',
    )
    assert media_plan_absent(str(proj)) is None


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v', '-p', 'no:cacheprovider']))
