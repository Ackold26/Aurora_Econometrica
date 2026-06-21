"""INV-50 F-DELIVERABLE-1 (2026-06-07): честная оговорка о тонких данных /
переобучении должна доходить до КЛИЕНТСКИХ отчётов (PPTX/HTML/XLSX), а не
только до программы и письма.

Корень бага: `_map_pipeline_to_builder_data` ронял `verdict`/`thinness_cap`/
`ratio` на report-шве → клиентский файл показывал «MQS 70 Хорошее» без
предупреждения о переобучении, противореча программе. Доказано probe'ом на
реальном проекте Кагоцела (HTML/PPTX/XLSX: MQS есть, оговорка = 0).

Гейт: (1) payload несёт thinness-поля когда cap применён; (2) формулировка
едина (format_thinness_caveat — SSOT, та же в вердикте); (3) HTML/PPTX
содержат оговорку при cap и НЕ фабрикуют её без cap.
"""
import re
import tempfile

from utils.diagnostics import generate_diagnostics_summary, format_thinness_caveat
from engines.narrative_adapter import _map_pipeline_to_builder_data


# Кагоцел-подобная диагностика: 31 набл / 13.1 эфф.параметров → ratio 2.4 < 4 → cap 70.
THIN = generate_diagnostics_summary(
    r_squared=0.98, mape=8.0, rmse=1.0, r_hat_max=1.01, divergences=0,
    n_obs=31, n_params=20, effective_params=13.1,
)
# Толстые данные: ratio >> 4 → cap None → оговорки быть НЕ должно.
FAT = generate_diagnostics_summary(
    r_squared=0.9, mape=8.0, rmse=1.0, r_hat_max=1.01, divergences=0,
    n_obs=200, n_params=20, effective_params=18.0,
)

# Тон McElreath (2026-06-20): оговорка про «модель сдержана / опирается на
# priors / ориентировочные», а не про «артефакт переобучения». Обе ветки
# format_thinness_caveat начинаются с «Данных мало».
CAVEAT_RE = re.compile(r"данных мало|сдержан|априорн|ориентировочн", re.I)


def _payload(diag):
    return _map_pipeline_to_builder_data(
        model_data={"diagnostics": diag}, decompose_data={}, optimize_data={},
        scenarios=[], project_id="test",
    )


def test_seam_carries_thinness_fields_when_capped():
    """Шов больше не роняет thinness-поля (корень F-DELIVERABLE-1)."""
    pdiag = _payload(THIN)["diagnostics"]
    assert pdiag["thinness_cap"] == 70
    assert pdiag["ratio"] == 2.4
    assert "ratio_nominal" in pdiag
    assert "effective_parameters" in pdiag


def test_seam_thinness_cap_none_when_fat():
    pdiag = _payload(FAT)["diagnostics"]
    # cap присутствует ключом, но None — билдер отличает «нет cap» от «не знаем».
    assert pdiag.get("thinness_cap") is None


def test_caveat_wording_is_single_source():
    """Формулировка в отчёте == формулировка в вердикте программы (анти-дивергенция)."""
    cav = format_thinness_caveat(THIN["metrics"]["ratio"], THIN["mqs"]["thinness_cap"],
                                 leading_space=False)
    assert cav and cav in THIN["verdict"]
    # без cap — пусто, не фабрикуем
    assert format_thinness_caveat(FAT["metrics"]["ratio"], FAT["mqs"]["thinness_cap"]) == ""


def test_html_deliverable_carries_caveat_when_capped():
    from engines.html_export import build_html
    out = tempfile.gettempdir() + "/test_fd_thin.html"
    res = build_html(model_data={"diagnostics": THIN}, decompose_data={},
                     optimize_data={}, output_path=out, project_id="test")
    assert res.get("status") == "ok"
    html = open(out, encoding="utf-8").read()
    assert '<div class="mqs-caveat">' in html  # сам элемент, не только CSS-правило
    assert CAVEAT_RE.search(html), "HTML отчёт обязан нести оговорку при data-thinness cap"


def test_html_deliverable_no_caveat_when_fat():
    from engines.html_export import build_html
    out = tempfile.gettempdir() + "/test_fd_fat.html"
    build_html(model_data={"diagnostics": FAT}, decompose_data={},
               optimize_data={}, output_path=out, project_id="test")
    html = open(out, encoding="utf-8").read()
    # CSS-правило .mqs-caveat присутствует всегда — проверяем отсутствие ЭЛЕМЕНТА.
    assert '<div class="mqs-caveat">' not in html, "На толстых данных оговорку фабриковать нельзя"


def test_pptx_deliverable_carries_caveat_when_capped():
    from aurora_pptx.builder import AuroraPPTXBuilder
    b = AuroraPPTXBuilder(_payload(THIN))
    assert b.thinness_cap == 70 and b.ratio_eff == 2.4
    prs = b.build()
    out = tempfile.gettempdir() + "/test_fd_thin.pptx"
    prs.save(out)
    import zipfile
    z = zipfile.ZipFile(out)
    txt = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))
    # PPTX дробит текст по run'ам → ищем по стрипнутому тексту.
    stripped = re.sub(r"<[^>]+>", "", txt)
    assert CAVEAT_RE.search(stripped), "PPTX отчёт обязан нести оговорку при data-thinness cap"


def test_no_overfitting_artefact_wording_in_caveat():
    """Анти-регрессия тона (Волна 1, McElreath): старый алармизм «артефакт
    переобучения / высокий риск переобучения» в клиентской оговорке недопустим."""
    for r in (1.5, 2.4, 3.5):
        cav = format_thinness_caveat(r, 70, leading_space=False).lower()
        assert "артефакт" not in cav
        assert "высокий риск переобуч" not in cav
        assert "ненадёжны" not in cav


def test_merge_channels_preserves_unit_smell():
    """Волна 1: honesty-поля (unit_smell/smell_flags) доходят через мост до
    hero-гарда; иначе битый ROI-канал (TRP, не рубли) коронуется «лучшим»."""
    from engines.narrative_adapter import _merge_channels
    decomp = [
        {"name": "TRPs бренд", "spend": 22100, "contribution": 409e6, "roi": 18500,
         "unit_smell": True, "smell_flags": [{"type": "roi_max"}], "category": "brand"},
        {"name": "Social", "spend": 100e6, "contribution": 1345e6, "roi": 13.4},
    ]
    merged = _merge_channels(decomp, [])
    trp = next(c for c in merged if "TRP" in (c.get("name") or ""))
    assert trp.get("unit_smell") is True
    assert trp.get("smell_flags")
