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


def test_unreliable_channel_roi_blanked_in_payload():
    """Волна 1 Шаг 2 (data-level заглушка): битый ROI-канал в payload обнулён
    (mroas/roi=None, action_reasoning без сырого числа) → ни один билдер
    (HTML/PPTX/XLSX) не покажет абсурдные 15525×. INV-50."""
    dec = {"channels": [
        {"name": "TRPs бренд", "spend": 22100, "contribution": 409e6, "roi": 18500,
         "mroi_current": 15525, "unit_smell": True, "verdict": "ROI завышен (не рубли?)"},
        {"name": "Social", "spend": 100e6, "contribution": 1345e6, "roi": 13.4,
         "mroi_current": 1.5, "verdict": "Высокоэффективен"},
    ]}
    payload = _map_pipeline_to_builder_data(
        model_data={}, decompose_data=dec, optimize_data={}, scenarios=[], project_id="t")
    trp = next(c for c in payload["channels"] if "TRP" in (c.get("name") or ""))
    assert trp["roi_unreliable"] is True
    assert trp["mroas"] is None and trp["roi"] is None
    reasoning = trp.get("action_reasoning") or ""
    assert "15525" not in reasoning and "18500" not in reasoning
    # надёжный канал не тронут
    social = next(c for c in payload["channels"] if "Social" in (c.get("name") or ""))
    assert social.get("roi_unreliable") is False


# ── Волна 1 пункт 2 (2026-06-20): плашка надёжности модели в отчётах ──────────
# Решение 1b (Антон): плашка ТОЛЬКО при verdict != reliable; caveat_text идёт
# VERBATIM из SSOT (optimizer_honesty, тот же текст в UI — INV-50, без рассинхрона).

MR_UNCERTAIN = {
    "verdict": "uncertain", "refused": False,
    "caveat_text": "Рекомендации ориентировочные: опирайтесь на доверительные интервалы.",
    "reasons": ["Ограниченные данные (Ratio 2.4:1 < 4:1): модель сдержана, опирается на priors."],
}
MR_RELIABLE = {"verdict": "reliable", "refused": False, "caveat_text": "", "reasons": []}


def _payload_opt(opt):
    return _map_pipeline_to_builder_data(
        model_data={"diagnostics": FAT}, decompose_data={}, optimize_data=opt,
        scenarios=[], project_id="test",
    )


def test_seam_carries_model_reliability_when_uncertain():
    """Мост доносит model_reliability в diagnostics при verdict != reliable, текст verbatim."""
    pdiag = _payload_opt({"model_reliability": MR_UNCERTAIN})["diagnostics"]
    mr = pdiag.get("model_reliability")
    assert mr is not None, "мост обязан донести model_reliability при uncertain"
    assert mr["verdict"] == "uncertain"
    assert mr["caveat_text"] == MR_UNCERTAIN["caveat_text"]  # VERBATIM (INV-50)
    assert mr["reasons"]


def test_seam_drops_model_reliability_when_reliable():
    """При reliable плашки нет — не зашумляем хороший отчёт (решение 1b)."""
    pdiag = _payload_opt({"model_reliability": MR_RELIABLE}).get("diagnostics", {})
    assert "model_reliability" not in pdiag


def test_html_carries_reliability_plaque_when_uncertain():
    """HTML несёт плашку надёжности (verdict != reliable) с текстом verbatim."""
    from engines.html_export import build_html
    out = tempfile.gettempdir() + "/test_mr_uncertain.html"
    build_html(model_data={"diagnostics": FAT}, decompose_data={},
               optimize_data={"model_reliability": MR_UNCERTAIN},
               output_path=out, project_id="test")
    html = open(out, encoding="utf-8").read()
    assert "mqs-reliability" in html, "HTML обязан нести плашку надёжности при uncertain"
    assert "Ограниченная надёжность модели" in html
    assert MR_UNCERTAIN["caveat_text"] in html  # verbatim из SSOT


def test_html_no_reliability_plaque_when_reliable():
    from engines.html_export import build_html
    out = tempfile.gettempdir() + "/test_mr_reliable.html"
    build_html(model_data={"diagnostics": FAT}, decompose_data={},
               optimize_data={"model_reliability": MR_RELIABLE},
               output_path=out, project_id="test")
    html = open(out, encoding="utf-8").read()
    assert "mqs-reliability" not in html, "при reliable плашку фабриковать нельзя"


def test_pptx_carries_reliability_plaque_when_uncertain():
    from aurora_pptx.builder import AuroraPPTXBuilder
    b = AuroraPPTXBuilder(_payload_opt({"model_reliability": MR_UNCERTAIN}))
    prs = b.build()
    out = tempfile.gettempdir() + "/test_mr_uncertain.pptx"
    prs.save(out)
    import zipfile
    z = zipfile.ZipFile(out)
    txt = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))
    stripped = re.sub(r"<[^>]+>", "", txt)
    assert re.search(r"надёжност|ориентировочн", stripped, re.I), \
        "PPTX обязан нести плашку надёжности при uncertain"


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
