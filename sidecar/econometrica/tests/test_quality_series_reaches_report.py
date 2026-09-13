"""Ряд «факт против прогноза» доезжает до графиков качества с ОБОИХ движков (s47).

Дефект у клиента: в OLS-режиме (малые данные) раздел «Качество модели и
источники данных» рисовал заголовок и три пустых места вместо трёх графиков —
молча, без единого объяснения, почему их нет.

Корень. Все три графика раздела читают один ключ `CHART_DATA.quality` (см.
aurora_html/interactive.py: chart-quality-avp / -residuals / -scatter) — общая
точка отказа, потому и пропадали разом. Ключ наполняется переносом в
engines/narrative_adapter.py, а перенос требует списки `actual`, `predicted` И
`dates` РАВНОЙ длины. Байесовский движок (engines/modeler.py) даты кладёт,
OLS-движок (engines/ols_modeler.py) не клал ВОВСЕ — условие не проходило, ключ
тихо не попадал в диагностику, и раздел оставался пустым.

Тест сторожит контракт формы, одинаковый для обоих движков, и сквозной путь до
самих графиков — а не отдельную строку, которую легко починить в одном движке и
снова разойтись в другом.
"""
from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from engines.narrative_adapter import _map_pipeline_to_builder_data  # noqa: E402

# Ключи, без которых перенос ряда в отчёт не состоится.
_REQUIRED_KEYS = ("actual", "predicted", "dates")
# Три графика раздела «Качество модели» и то, что каждому нужно из ряда.
_QUALITY_CHARTS = {
    "chart-quality-avp": ("dates", "actual", "predicted"),
    "chart-quality-residuals": ("dates", "residuals"),
    "chart-quality-scatter": ("actual", "predicted"),
}

N = 12


def _mcmc_shape():
    """Как ряд кладёт байесовский движок (engines/modeler.py)."""
    return {
        "actual": [100.0 + i for i in range(N)],
        "predicted": [101.0 + i for i in range(N)],
        "dates": [f"2026-01-{i + 1:02d}" for i in range(N)],
    }


def _ols_shape():
    """Как ряд кладёт OLS-движок (engines/ols_modeler.py) — форма из живого прогона."""
    return {
        "actual": [100.0 + i for i in range(N)],
        "predicted": [101.0 + i for i in range(N)],
        "residuals": [-1.0] * N,
        "dates": [f"2026-01-{i + 1:02d}" for i in range(N)],
    }


def _channels():
    return [
        {"name": "ТВ", "spend": 1_000_000, "contribution": 1_500_000,
         "mroas": 1.5, "roi": 1.5, "action": "Scale", "verdict": "Scale"},
        {"name": "Performance", "spend": 500_000, "contribution": 300_000,
         "mroas": 0.6, "roi": 0.6, "action": "Cut", "verdict": "Cut"},
    ]


def _builder_data(avp):
    """Прогоняет диагностику движка через тот самый перенос, что живёт в бою."""
    model_data = {"diagnostics": {"actual_vs_predicted": avp, "mqs_score": 70}}
    decompose_data = {"channels": _channels()}
    optimize_data = {"expected_lift_pct": 5.0}
    return _map_pipeline_to_builder_data(model_data, decompose_data, optimize_data, None)


def _carried(data):
    return (data.get("diagnostics") or {}).get("actual_vs_predicted") or {}


# ─── Контракт формы: оба движка кладут ряд одинаково ─────────────────────────

@pytest.mark.parametrize("shape, движок", [(_mcmc_shape(), "байесовский"), (_ols_shape(), "OLS")])
def test_engine_shape_has_keys_the_transfer_requires(shape, движок):
    missing = [k for k in _REQUIRED_KEYS if not isinstance(shape.get(k), list) or not shape[k]]
    assert not missing, (
        f"Движок {движок} кладёт ряд качества без {missing} — перенос в отчёт его "
        "молча отбросит, и раздел «Качество модели» останется без всех трёх графиков"
    )


def test_both_engines_name_residuals_the_same_way():
    """Остатки у OLS звались `residual`, у соседа `residuals` — форма разошлась.

    Потребителя у ключа на момент правки не было, поэтому расхождение никто не
    ловил; оно просто ждало первого, кто прочитает ряд по имени.
    """
    assert "residual" not in _ols_shape(), (
        "Вернулось имя `residual` — форма снова разошлась с байесовским движком"
    )
    assert isinstance(_ols_shape().get("residuals"), list)


# ─── Сквозной путь: перенос довозит ряд до графиков ──────────────────────────

@pytest.mark.parametrize("shape, движок", [(_mcmc_shape(), "байесовский"), (_ols_shape(), "OLS")])
def test_quality_series_survives_transfer_to_report(shape, движок):
    avp = _carried(_builder_data(shape))
    assert avp, (
        f"Ряд качества с движка {движок} не доехал до отчёта — раздел «Качество "
        "модели» покажет заголовок и пустоту вместо трёх графиков"
    )
    for key in ("dates", "actual", "predicted", "residuals"):
        assert isinstance(avp.get(key), list) and len(avp[key]) == N, (
            f"[{движок}] после переноса ключ {key!r} пуст или другой длины: "
            f"{avp.get(key)!r}"
        )


@pytest.mark.parametrize("shape, движок", [(_mcmc_shape(), "байесовский"), (_ols_shape(), "OLS")])
@pytest.mark.parametrize("chart_id", sorted(_QUALITY_CHARTS))
def test_every_quality_chart_gets_its_data(shape, движок, chart_id):
    """Каждому из трёх графиков хватает того, что доехало."""
    avp = _carried(_builder_data(shape))
    for key in _QUALITY_CHARTS[chart_id]:
        ряд = avp.get(key)
        assert isinstance(ряд, list) and len(ряд) == N, (
            f"[{движок}] графику {chart_id} не хватает ряда {key!r} — он не "
            f"отрисуется: {ряд!r}"
        )


def test_transfer_drops_series_without_dates():
    """Обратная сторона: без дат перенос обязан отбросить ряд, а не выдумать ось.

    Проверка держит сам механизм честным — чтобы «починка» не свелась к тому,
    что отчёт начал рисовать графики по выдуманным датам.
    """
    без_дат = {k: v for k, v in _ols_shape().items() if k != "dates"}
    assert not _carried(_builder_data(без_дат)), (
        "Ряд без дат доехал до отчёта — графики построятся по несуществующей оси"
    )


# ─── Живой прогон движка: форма не разъедется с реальностью ──────────────────

def test_live_ols_run_produces_transferable_quality_series(tmp_path):
    """Самый дорогой, но решающий: гоняем настоящий OLS-движок на своих данных.

    Проверки выше сторожат форму, записанную в тесте; эта — что движок такую
    форму и правда отдаёт. Без неё тест мог бы остаться зелёным на выдуманной
    фикстуре при снова сломанном движке.
    """
    np = pytest.importorskip("numpy")
    pd = pytest.importorskip("pandas")
    from engines.ols_modeler import train_ols

    rng = np.random.default_rng(7)
    n = 26
    tv = rng.uniform(1e6, 5e6, n)
    perf = rng.uniform(5e5, 3e6, n)
    frame = pd.DataFrame({
        "date": pd.date_range("2026-01-05", periods=n, freq="W-MON").strftime("%Y-%m-%d"),
        "sales": 1e7 + 2.0 * tv + 3.5 * perf + rng.normal(0, 3e5, n),
        "ТВ": tv,
        "Performance": perf,
    })
    csv = tmp_path / "data.csv"
    frame.to_csv(csv, index=False, encoding="utf-8")

    res = train_ols({
        "data_file": str(csv),
        "kpi_column": "sales",
        "media_columns": ["ТВ", "Performance"],
        "control_columns": [],
        "date_column": "date",
        "adstock_config": {},
    }, str(tmp_path))

    assert res.get("status") == "ok", res.get("message")
    avp = (res.get("diagnostics") or {}).get("actual_vs_predicted") or {}
    for key in ("dates", "actual", "predicted", "residuals"):
        assert isinstance(avp.get(key), list) and len(avp[key]) == n, (
            f"Живой прогон OLS: ключ {key!r} пуст или другой длины — "
            f"раздел «Качество модели» снова останется без графиков: {avp.get(key)!r}"
        )
    assert avp["dates"][0] == "2026-01-05"
