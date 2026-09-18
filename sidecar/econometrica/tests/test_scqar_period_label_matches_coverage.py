"""Подпись периода рядом с суммой бюджета в SCQAR — правда об охвате данных,
не жёстко зашитая единица времени (s49, находка ведущей сессии 18.09.2026).

`aurora_html/sections.py` (обе ветки — JSON-шаблон `strings_ru.json`
scqar/situation/template для kpi.is_legacy И Python f-string для KPI-aware
режима) печатали «{budget} млн ₽ в квартал» для ЛЮБОГО прогона. `budget` —
это `facts['total_budget_mln']` = `total_spend / 1_000_000`
(`engines/narrative_adapter.py:821`), сумма ЗА ВЕСЬ проанализированный период,
а не за квартал. На клиентском образце период — 104 недели (два года): текст
говорил «878 млн ₽ в квартал» вместо правды. `aurora_pptx/builder.py` этот
же узел уже честно чинил (B1-fix R-02, 2026-07-03) через
`meta['data_window_label']` (`engines.narrative_adapter._derive_data_coverage`,
реальные даты `time_series.dates`) — починка HTML переиспользует тот же
источник, не изобретает второй.

Тест поведенческий, не текстовый по одному слову: не «в тексте нет "квартал"»
(это ловит только СТРОКУ, а не класс), а «фраза рядом с суммой называет РОВНО
тот охват, что фактически посчитан из дат прогона». Даты — 104 еженедельные
точки на два года, через настоящую `_derive_data_coverage` (не рукописный
лейбл) — тот же приём, что у находки. Проверены ОБЕ ветки (`kpi.is_legacy`
True и False): обе врали одинаково, но разными путями (JSON `.format()` и
f-string), значит и красное-зелёное нужно на обеих.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora_html.sections import render_executive_summary  # noqa: E402
from engines.narrative_adapter import _derive_data_coverage  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_STRINGS_PATH = os.path.join(os.path.dirname(_HERE), "aurora_html", "strings_ru.json")

CLIENT = "Демо-клиент"
BUDGET_MLN = 878.0  # тот же порядок величины, что в находке (878 млн ₽)


def _two_year_weekly_dates() -> list[str]:
    """104 еженедельные точки, 2024-09-15 → ~2026-09 — профиль дат находки
    (104 недели = два года), но настоящие ISO-даты, не выдуманный лейбл."""
    start = datetime(2024, 9, 15)
    return [(start + timedelta(weeks=i)).strftime("%Y-%m-%d") for i in range(104)]


def _real_window_label() -> str:
    """Честный охват, посчитанный ТЕМ ЖЕ узлом, что и в бою — не литерал теста."""
    coverage = _derive_data_coverage({"time_series": {"dates": _two_year_weekly_dates()}})
    assert coverage is not None and coverage["frequency_label"] == "Еженедельно"
    return coverage["window_label"]


def _channels():
    return [
        {"name": "Онлайн-видео", "spend": 400_000_000, "contribution": 3_000_000_000,
         "mroas": 2.1, "roi": 2.1, "action": "Scale", "verdict": "Scale"},
        {"name": "Performance", "spend": 200_000_000, "contribution": 1_400_000_000,
         "mroas": 1.9, "roi": 1.9, "action": "Hold", "verdict": "Hold"},
        {"name": "ТВ", "spend": 278_000_000, "contribution": 500_000_000,
         "mroas": 0.6, "roi": 0.6, "action": "Cut", "verdict": "Cut"},
    ]


def _facts(**overrides):
    f = {
        "leader_channel": "Онлайн-видео",
        "hero_channel": "Онлайн-видео",
        "cut_source_channel": "ТВ",
        "scale_destination_channel": "Performance",
        "total_budget_mln": BUDGET_MLN,
        "n_active_channels": 3,
        "weighted_roi": 1.6,
        "leader_share_spend_pct": 46.0,
        "leader_share_contrib_pct": 61.0,
        "budget_dominator_channel": "Онлайн-видео",
        "budget_dominator_spend_pct": 46.0,
        "budget_dominator_contrib_pct": 61.0,
        "reallocation_mln": 30.0,
        "expected_lift_pct": 2.0,
        "underperformer_names": ["ТВ"],
        "action_counts": {"Scale": 1, "Hold": 1, "Cut": 1},
        "binding_constraints": False,
        "optimization_converged": True,
        "converged_at_current": False,
        "honest_narrative": False,
        "model_refused": False,
    }
    f.update(overrides)
    return f


def _ctx(kpi: dict | None = None):
    with open(_STRINGS_PATH, encoding="utf-8") as fh:
        strings = json.load(fh)
    meta = {
        "client": CLIENT,
        "project_id": "DEMO",
        "data_window_label": _real_window_label(),
    }
    ctx = {
        "meta": meta,
        "facts": _facts(),
        "channels": _channels(),
        "diagnostics": {"mqs_score": 72},
        "strings": strings,
        "report_id": "DEMO",
        "model_version": "1.0",
        "period_unit": "неделям",
    }
    if kpi is not None:
        ctx["kpi"] = kpi
    return ctx


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _situation_sentence(text: str) -> str:
    """Первое предложение блока СИТУАЦИЯ — то, где стоит сумма бюджета."""
    m = re.search(re.escape(CLIENT) + r"[^.]*\.", text)
    assert m, f"не нашла предложение с бюджетом в тексте: {text!r}"
    return m.group(0)


def _assert_period_is_honest(sentence: str, real_window_label: str) -> None:
    # Класс дефекта: рядом с суммой стоит ЖЁСТКО зашитая единица времени,
    # которая не совпадает с фактическим охватом дат прогона. Два года
    # еженедельных данных не являются кварталом ни при каком реальном охвате -
    # значит правильный текст обязан называть настоящий охват, а не «квартал»,
    # «в месяц», «в год» и т.п.
    assert "квартал" not in sentence.lower(), (
        f"текст называет период кварталом при фактическом охвате "
        f"{real_window_label!r} (104 недели, два года): {sentence!r}"
    )
    assert real_window_label in sentence, (
        f"текст не называет фактический охват {real_window_label!r} рядом с "
        f"суммой бюджета: {sentence!r}"
    )


def test_situation_legacy_kpi_names_real_period_not_quarter():
    """kpi.is_legacy=True — ветка через JSON-шаблон scqar/situation/template."""
    ctx = _ctx(kpi=None)  # без ctx['kpi'] → kpi_kind='monetary', mode='roi' → is_legacy
    real_window_label = ctx["meta"]["data_window_label"]
    text = _plain(render_executive_summary(ctx))
    sentence = _situation_sentence(text)
    _assert_period_is_honest(sentence, real_window_label)


def test_situation_kpi_aware_names_real_period_not_quarter():
    """kpi.is_legacy=False — ветка через Python f-string (KPI-aware режим)."""
    ctx = _ctx(kpi={"kpi_kind": "count", "derived_mode": "roi"})
    real_window_label = ctx["meta"]["data_window_label"]
    text = _plain(render_executive_summary(ctx))
    sentence = _situation_sentence(text)
    _assert_period_is_honest(sentence, real_window_label)


def test_missing_data_window_label_falls_back_honestly():
    """Нет meta['data_window_label'] (старые прогоны / данные без парсибельных
    дат) — фраза обязана остаться честной («за анализируемый период»), не
    молчать и не откатываться на «в квартал»."""
    ctx = _ctx(kpi=None)
    ctx["meta"].pop("data_window_label", None)
    text = _plain(render_executive_summary(ctx))
    sentence = _situation_sentence(text)
    assert "квартал" not in sentence.lower()
    assert "за анализируемый период" in sentence
