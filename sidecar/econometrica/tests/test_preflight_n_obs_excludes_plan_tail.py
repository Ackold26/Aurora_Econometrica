"""L-08 (2026-09-01): предполётная проверка не должна считать наблюдениями
строки медиаплана вперёд, где целевой величины нет и быть не может.

`engines/validator.py::validate_data` (эндпоинт `/compute/validate`) при
обнаружении хвоста медиаплана обрезает `df` до истории ПЕРЕД любой
статистикой (`validator.py:450-451`, комментарий «Статистику считаем только
по истории»). `server.py::preflight` (эндпоинт `/compute/preflight`) читает
тот же файл заново и берёт `n_obs = len(df)` БЕЗ этой обрезки — хвост плана
(KPI пуст, инвестиции заполнены) раздувает число наблюдений, и вердикт
надёжности (`overall_tier`, `recommended_mode`) считается по завышенному n.

Найдено пробоем на живом движке (team lead, 2026-09-01): файл 15 недель
истории + 20 недель плана — `/compute/validate` честно даёт warning «с
оговорками» (n=15 < 20 → тон 'bad'), а `/compute/preflight` даёт
overall_tier='reliable' по n_obs=35.

Тот же класс дефекта, что несчитанная метрика, показанная нулём: число,
подставленное в порог, не то же самое, что число, которое порог должен
проверять. Здесь фиксируется, что preflight использует ТУ ЖЕ обрезку
истории, что и validate — тем же вызовом (`engines.planning.detect_media_plan_tail`),
не своей копией логики.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from server import preflight, PreflightRequest


def _make_xlsx(tmp_path: Path, n_history: int, n_future: int, *, seed: int = 42) -> Path:
    """Записывает xlsx с history+tail. Тот же фабричный паттерн, что
    test_planning_history_split.py::_make_xlsx — переиспользую форму, не
    дублирую с нуля."""
    total = n_history + n_future
    dates = pd.date_range("2022-01-03", periods=total, freq="W-MON")
    rng = np.random.RandomState(seed)
    kpi = list(rng.uniform(100_000, 1_000_000, n_history)) + [np.nan] * n_future
    tv = rng.uniform(10_000, 100_000, total).tolist()
    digital = rng.uniform(5_000, 50_000, total).tolist()
    df = pd.DataFrame({
        "date": dates,
        "sales": kpi,
        "tv_spend": tv,
        "digital_spend": digital,
    })
    p = tmp_path / "data.xlsx"
    df.to_excel(p, index=False)
    return p


def _preflight_result(tmp_path: Path, n_history: int, n_future: int) -> dict:
    p = _make_xlsx(tmp_path, n_history, n_future)
    req = PreflightRequest(
        project_dir=str(tmp_path / "project"),
        file_path=str(p),
        media_columns=["tv_spend", "digital_spend"],
        kpi_column="sales",
        date_column="date",
        skip_prior_predictive=True,  # ускоряем тест — прежде не нужен здесь
    )
    resp = preflight(req)
    return resp.body and __import__("json").loads(resp.body)


def test_preflight_n_obs_matches_validate_history_count_with_plan_tail(tmp_path: Path):
    """Сквозной случай team lead: 15 история + 20 план.

    До правки: n_obs=35 (15+20, хвост посчитан). После правки: n_obs=15
    (только история) — то же число, что дал бы /compute/validate.
    """
    result = _preflight_result(tmp_path, n_history=15, n_future=20)
    assert result['n_obs'] == 15, (
        f"n_obs должен быть 15 (только история), получено {result['n_obs']} — "
        f"хвост медиаплана (20 строк без KPI) не должен считаться наблюдениями."
    )


def test_preflight_tier_is_honest_on_thin_history_with_long_plan_tail(tmp_path: Path):
    """Сквозной случай team lead: 15 история (< 20 → честный тон 'bad' по
    engines/ols_modeler.py::_honest_n_obs_tone) + 20 план.

    До правки: n_obs=35 (≥30) → overall_tier='reliable' — неверно, вердикт
    молчит там, где должен честно отказать.
    После правки: n_obs=15 (<20) → overall_tier='insufficient'.
    """
    result = _preflight_result(tmp_path, n_history=15, n_future=20)
    assert result['overall_tier'] == 'insufficient', (
        f"На 15 реальных наблюдениях (порог n<20 → 'bad') overall_tier должен "
        f"быть 'insufficient', получено {result['overall_tier']!r} — похоже, "
        f"n_obs всё ещё считает строки хвоста медиаплана."
    )


def test_preflight_n_obs_unaffected_when_no_plan_tail(tmp_path: Path):
    """No-op инвариант: без хвоста плана n_obs не меняется (полный файл = история)."""
    result = _preflight_result(tmp_path, n_history=24, n_future=0)
    assert result['n_obs'] == 24


def test_preflight_reliable_verdict_unchanged_on_demo_shaped_file(tmp_path: Path):
    """Приёмочный сценарий team lead №1 (форма демо-файла): 104 история + 26
    план. 104 ≥ 30 — вердикт обязан остаться 'reliable' и до, и после правки.
    Страхует, что починка основания не сломала здоровый случай.
    """
    result = _preflight_result(tmp_path, n_history=104, n_future=26)
    assert result['n_obs'] == 104
    assert result['overall_tier'] == 'reliable'
