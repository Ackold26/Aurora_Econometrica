"""Перенос трёх находок из origin/feat/ai-insights-tier2, потерянных при
развитии ветки feat/econ-canon-p0 (2026-08-04). Наша архитектура (unit_smell /
ROI_ARTIFACT / _derive_data_coverage / honesty_verdict SSOT) новее и надёжнее
их версии — переносим ТОЛЬКО недостающее поверх неё, не откатывая.

1. Метка режима анализа (analysis_mode_label) + типа KPI (kpi_kind_label) —
   без неё клиент может принять долю вклада за ROI (narrative_adapter →
   diagnostics → sections.py / builder.py).
2. `_clean_name` в decomposer.py — грязное имя канала (Excel `\\n`/двойные
   пробелы) не должно утекать в клиентский insight-текст.
3. `soften_verdict_display` в channel_action.py — honesty-потолок: смягчает
   директивность канального вердикта по глобальной надёжности модели
   (SSOT — diagnostics["honesty_verdict"] / self.honesty_verdict), сохраняя
   направление.
"""
import re
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.channel_action import soften_verdict_display  # noqa: E402
from engines.decomposer import _build_channel_insight, _clean_name  # noqa: E402
from engines.narrative_adapter import _map_pipeline_to_builder_data  # noqa: E402


def _pptx_text(prs) -> str:
    """PPTX дробит текст по run'ам → извлекаем весь текст из XML частей архива.
    Уникальное имя файла на вызов — тесты идут параллельно (pytest-xdist,
    -n 4 в pytest.ini), общий путь ловил гонку записи/чтения (BadZipFile)."""
    fd, out = tempfile.mkstemp(suffix=".pptx", prefix="test_ported_tier2_")
    import os
    os.close(fd)
    prs.save(out)
    z = zipfile.ZipFile(out)
    txt = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))
    return re.sub(r"<[^>]+>", "", txt)


# ─── Задача 1: метка режима анализа + типа KPI ────────────────────────────────

DEC_TWO_CH = {
    "derived_mode": "effectiveness",
    "kpi_kind": "count",
    "channels": [
        {"name": "TV", "spend": 100e6, "contribution": 200e6, "roi": 2.0,
         "mroas": 1.5, "optimal_spend": 130e6, "current_spend": 100e6,
         "contribution_pct": 60.0},
        {"name": "Social", "spend": 50e6, "contribution": 120e6, "roi": 2.4,
         "mroas": 1.6, "contribution_pct": 40.0},
    ],
}


def test_seam_carries_analysis_mode_and_kpi_kind_labels():
    """Шов диагностики несёт analysis_mode_label/kpi_kind_label (прежде ронял)."""
    diag = _map_pipeline_to_builder_data(
        model_data={}, decompose_data=DEC_TWO_CH, optimize_data={},
        scenarios=[], project_id="t",
    )["diagnostics"]
    assert diag["analysis_mode"] == "effectiveness"
    assert diag["analysis_mode_label"] == "Эффективность (доля вклада)"
    assert diag["kpi_kind"] == "count"
    assert diag["kpi_kind_label"] == "количественный"


def test_seam_analysis_mode_defaults_to_roi_monetary():
    """derived_mode/kpi_kind отсутствуют в payload → честный дефолт roi/monetary."""
    diag = _map_pipeline_to_builder_data(
        model_data={}, decompose_data={"channels": DEC_TWO_CH["channels"]},
        optimize_data={}, scenarios=[], project_id="t",
    )["diagnostics"]
    assert diag["analysis_mode_label"] == "ROI (деньги)"
    assert diag["kpi_kind_label"] == "денежный"


def test_html_deliverable_shows_analysis_mode_label():
    from engines.html_export import build_html
    out = tempfile.gettempdir() + "/test_ported_tier2_mode.html"
    res = build_html(model_data={}, decompose_data=DEC_TWO_CH, optimize_data={},
                     output_path=out, project_id="test")
    assert res.get("status") == "ok"
    html = open(out, encoding="utf-8").read()
    assert "Режим анализа: Эффективность (доля вклада)" in html
    assert "KPI: количественный" in html


def test_pptx_deliverable_shows_analysis_mode_label():
    from aurora_pptx.builder import AuroraPPTXBuilder
    payload = _map_pipeline_to_builder_data(
        model_data={}, decompose_data=DEC_TWO_CH, optimize_data={},
        scenarios=[], project_id="t",
    )
    b = AuroraPPTXBuilder(payload)
    assert b.analysis_mode_label == "Эффективность (доля вклада)"
    assert b.kpi_kind_label == "количественный"
    stripped = _pptx_text(b.build())
    assert "Режим анализа" in stripped


# ─── Задача 2: _clean_name — грязное имя канала не утекает в insight ─────────

def test_clean_name_strips_newlines_and_double_spaces():
    assert _clean_name("TV\nБюджет  до  НДС") == "TV Бюджет до НДС"
    assert _clean_name("  Social   ") == "Social"


def test_build_channel_insight_uses_clean_name_monetary():
    """Excel-заголовок с переносом строки не должен утечь в клиентский insight."""
    channels = [
        {"name": "TV\nБренд", "roi": 2.0, "efficiency_gap": 8.0, "unit_smell": False},
        {"name": "Radio\n \nБренд", "roi": 0.3, "efficiency_gap": -8.0, "unit_smell": False},
    ]
    insight = _build_channel_insight(channels)
    assert "\n" not in insight
    assert "TV Бренд" in insight
    assert "Radio Бренд" in insight


def test_build_channel_insight_uses_clean_name_count_mode():
    channels = [
        {"name": "Digital\nVideo", "roi": 0.02, "efficiency_gap": 8.0, "unit_smell": False},
        {"name": "Print\n\nAds", "roi": 0.005, "efficiency_gap": -8.0, "unit_smell": False},
    ]
    insight = _build_channel_insight(channels, kpi_kind="count")
    assert "\n" not in insight
    assert "Digital Video" in insight
    assert "Print Ads" in insight


# ─── Задача 3: soften_verdict_display — honesty-потолок канального вердикта ──

def test_soften_verdict_display_preserves_direction():
    # reliable → директивный label
    assert soften_verdict_display("Scale", "reliable") == ("Увеличить", "firm")
    # 2026-08-10: нет вердикта (None/''/пробелы) — это НЕ «модель надёжна», а
    # «надёжность не проверена» → тот же результат, что явный 'unknown'.
    # Прежде None давал директиву наравне с reliable — отчёт противоречил сам
    # себе (баннер «не подтверждена» сверху, твёрдое «Увеличить» в таблице
    # рядом). См. дубль этого теста и полный разбор в
    # test_deliverable_thinness_disclosure.py.
    for пустое in (None, "", "   "):
        lbl_none, mod_none = soften_verdict_display("Scale", пустое)
        assert "Увеличить" in lbl_none and "предв" in lbl_none and mod_none == "tentative", (
            f"soften_verdict_display('Scale', {пустое!r}) не смягчился до unknown: "
            f"{(lbl_none, mod_none)!r}"
        )
    # uncertain/unknown → направление сохранено + «(предв.)»
    lbl, mod = soften_verdict_display("Scale", "uncertain")
    assert "Увеличить" in lbl and "предв" in lbl and mod == "tentative"
    lbl, _ = soften_verdict_display("Cut", "unknown")
    assert "Остановить" in lbl and "предв" in lbl
    # нейтральные (Watch/Uncertain) — без суффикса, уже неуверенные
    assert soften_verdict_display("Watch", "uncertain") == ("Наблюдать", "tentative")
    # unreliable → нейтрализация: направление НЕ показываем (модель не сошлась)
    assert soften_verdict_display("Scale", "unreliable") == ("Требует переобучения", "refused")


# Диагностика, которая ведёт model_reliability_verdict (utils/optimizer_honesty.py)
# к вердикту 'reliable': checks непустые и без False, r_hat в норме, mqs не weak/poor.
DIAG_RELIABLE = {
    "metrics": {"r_hat_max": 1.0, "divergences": 0},
    "checks": {"ratio": True, "ess": True, "bfmi": True},
    "mqs": {"tier": "good", "tier_label": "Хорошее", "score": 80},
}
# r_hat_max >= RHAT_REFUSE_THRESHOLD (1.05) → 'unreliable' (модель не сошлась).
DIAG_UNRELIABLE = {
    "metrics": {"r_hat_max": 1.20},
}


def test_seam_channel_verdict_display_firm_when_reliable():
    payload = _map_pipeline_to_builder_data(
        model_data={"diagnostics": DIAG_RELIABLE}, decompose_data=DEC_TWO_CH,
        optimize_data={}, scenarios=[], project_id="t",
    )
    assert payload["diagnostics"]["honesty_verdict"] == "reliable"
    for ch in payload["channels"]:
        assert ch.get("verdict_modality") == "firm"
        assert "предв" not in (ch.get("verdict_display") or "")


def test_seam_channel_verdict_display_refused_when_unreliable():
    """Модель не сошлась → ни один канал не показывает директивное направление."""
    payload = _map_pipeline_to_builder_data(
        model_data={"diagnostics": DIAG_UNRELIABLE}, decompose_data=DEC_TWO_CH,
        optimize_data={}, scenarios=[], project_id="t",
    )
    assert payload["diagnostics"]["honesty_verdict"] == "unreliable"
    for ch in payload["channels"]:
        assert ch.get("verdict_modality") == "refused"
        assert ch.get("verdict_display") == "Требует переобучения"


def test_html_deliverable_softens_verdict_when_unreliable():
    from engines.html_export import build_html
    out = tempfile.gettempdir() + "/test_ported_tier2_verdict.html"
    build_html(model_data={"diagnostics": DIAG_UNRELIABLE}, decompose_data=DEC_TWO_CH,
              optimize_data={}, output_path=out, project_id="test")
    html = open(out, encoding="utf-8").read()
    assert "Требует переобучения" in html


def test_pptx_deliverable_softens_verdict_when_unreliable():
    from aurora_pptx.builder import AuroraPPTXBuilder
    payload = _map_pipeline_to_builder_data(
        model_data={"diagnostics": DIAG_UNRELIABLE}, decompose_data=DEC_TWO_CH,
        optimize_data={}, scenarios=[], project_id="t",
    )
    b = AuroraPPTXBuilder(payload)
    assert b.honesty_verdict == "unreliable"
    stripped = _pptx_text(b.build())
    assert "Требует переобучения" in stripped
