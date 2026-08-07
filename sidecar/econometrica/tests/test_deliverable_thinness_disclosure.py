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
    """Мост доносит вердикт надёжности модели в diagnostics при verdict != reliable,
    caveat_text VERBATIM (INV-50).

    Правка 2026-08-04 (после уточнения от команды): исходный тест ждал вердикт
    через optimize_data["model_reliability"] - это шов из июньской ветки
    ai-insights-tier2, которого в нашей архитектуре НЕТ. Действующий источник
    честности - model_data["diagnostics"] через
    utils.optimizer_honesty.model_reliability_verdict (тот же вокабуляр
    reliable/uncertain/unreliable/unknown), уже подключённый к
    soften_verdict_display в narrative_adapter.py/aurora_html/aurora_pptx.
    Проверяемое свойство (плашка видна при не-reliable, текст verbatim) не
    меняется - меняется только источник данных в фикстуре теста."""
    from utils.optimizer_honesty import model_reliability_verdict
    expected = model_reliability_verdict(THIN)
    pdiag = _payload(THIN)["diagnostics"]
    assert pdiag.get("honesty_verdict") == "uncertain" == expected["verdict"]
    assert pdiag.get("honesty_reasons")
    assert pdiag.get("honesty_caveat_text") == expected["caveat_text"]  # VERBATIM (INV-50)


def test_seam_drops_model_reliability_when_reliable():
    """При reliable плашки нет — не зашумляем хороший отчёт (решение 1b)."""
    pdiag = _payload_opt({"model_reliability": MR_RELIABLE}).get("diagnostics", {})
    assert "model_reliability" not in pdiag


def test_html_carries_reliability_plaque_when_uncertain():
    """HTML несёт плашку надёжности (verdict != reliable) с текстом verbatim.

    Правка 2026-08-04 (после уточнения от команды): источник - model_data
    diagnostics honesty_verdict (см. правку test_seam_carries_model_reliability_
    when_uncertain выше), не optimize_data. Плашка - действующий баннер
    reliability-disclaimer (F-A1-9, 2026-07-06), не «mqs-reliability» из
    июньской ветки, которого в коде никогда не было."""
    from engines.html_export import build_html
    from utils.optimizer_honesty import model_reliability_verdict
    expected_caveat = model_reliability_verdict(THIN)["caveat_text"]
    out = tempfile.gettempdir() + "/test_mr_uncertain.html"
    build_html(model_data={"diagnostics": THIN}, decompose_data={},
               optimize_data={}, output_path=out, project_id="test")
    html = open(out, encoding="utf-8").read()
    assert "reliability-disclaimer" in html, "HTML обязан нести плашку надёжности при uncertain"
    assert expected_caveat in html  # verbatim из SSOT (INV-50)


def test_html_no_reliability_plaque_when_reliable():
    from engines.html_export import build_html
    out = tempfile.gettempdir() + "/test_mr_reliable.html"
    build_html(model_data={"diagnostics": FAT}, decompose_data={},
               optimize_data={"model_reliability": MR_RELIABLE},
               output_path=out, project_id="test")
    html = open(out, encoding="utf-8").read()
    assert "mqs-reliability" not in html, "при reliable плашку фабриковать нельзя"


def test_pptx_carries_reliability_plaque_when_uncertain():
    """PPTX несёт ОТЛИЧИМЫЙ текст вердикта «uncertain», а не просто корень слова
    «надёжност» — тот совпадает и со статическим ярлыком «Вердикт надёжности:
    модель надёжна» при verdict == reliable. Прежняя версия теста гнала payload
    через мёртвый шов optimize_data["model_reliability"] (см.
    test_seam_drops_model_reliability_when_reliable выше в этом файле) — на
    самом деле получавшийся honesty_verdict был "reliable" (диагностика бралась
    из FAT), и тест был зелёным случайно, поймав слово «надёжности» из чужого
    текста, а не признак uncertain. Переписан на настоящий источник честности —
    model_data["diagnostics"] (THIN → honesty_verdict == "uncertain", тот же
    путь, что в test_seam_carries_model_reliability_when_uncertain)."""
    from aurora_pptx.builder import AuroraPPTXBuilder
    b = AuroraPPTXBuilder(_payload(THIN))
    assert b.honesty_verdict == "uncertain"
    prs = b.build()
    out = tempfile.gettempdir() + "/test_mr_uncertain.pptx"
    prs.save(out)
    import zipfile
    z = zipfile.ZipFile(out)
    txt = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))
    stripped = re.sub(r"<[^>]+>", "", txt)
    assert "Вердикт надёжности: требует осторожности" in stripped, \
        "PPTX обязан нести плашку надёжности при uncertain (текст самого вердикта, не корень слова)"
    assert "Вердикт надёжности: модель надёжна" not in stripped, \
        "плашка не должна показывать текст reliable-вердикта, когда модель uncertain"


# ── Волна 1 пункт 3 (2026-06-20): синхрон вердиктов — honesty-потолок (2a) ─────
# Решение 2a (Антон): глобальная надёжность модели смягчает ДИРЕКТИВНОСТЬ
# канального вердикта по МОДАЛЬНОСТИ, сохраняя НАПРАВЛЕНИЕ. Снимает противоречие
# «Scale в отчёте vs Uncertain в декомпозиции».

def test_soften_verdict_display_preserves_direction():
    from engines.channel_action import soften_verdict_display
    # reliable / нет вердикта → директивный label
    assert soften_verdict_display("Scale", "reliable") == ("Увеличить", "firm")
    assert soften_verdict_display("Scale", None) == ("Увеличить", "firm")
    # uncertain/unknown → направление сохранено + «(предв.)»
    lbl, mod = soften_verdict_display("Scale", "uncertain")
    assert "Увеличить" in lbl and "предв" in lbl and mod == "tentative"
    lbl, _ = soften_verdict_display("Cut", "unknown")
    assert "Остановить" in lbl and "предв" in lbl
    # нейтральные (Watch/Uncertain) — без суффикса, уже неуверенные
    assert soften_verdict_display("Watch", "uncertain") == ("Наблюдать", "tentative")
    # unreliable → нейтрализация: направление НЕ показываем (модель не сошлась)
    assert soften_verdict_display("Scale", "unreliable") == ("Требует переобучения", "refused")


_DEC_DIRECTIVE = {"channels": [
    {"name": "TV", "spend": 100e6, "contribution": 200e6, "roi": 2.0,
     "mroas": 1.5, "optimal_spend": 130e6, "current_spend": 100e6},
    {"name": "Social", "spend": 50e6, "contribution": 120e6, "roi": 2.4, "mroas": 1.6},
]}


def test_seam_channel_verdict_softened_when_uncertain():
    """Мост смягчает verdict_display при не-reliable; machine-key verdict цел (counts).

    Правка 2026-08-04 (после уточнения от команды): источник честности -
    model_data diagnostics (THIN, ratio 2.4:1 < 4:1 → honesty_verdict=uncertain),
    не optimize_data["model_reliability"] (тот шов не существует - см. правки
    выше в этом файле)."""
    payload = _map_pipeline_to_builder_data(
        model_data={"diagnostics": THIN}, decompose_data=_DEC_DIRECTIVE,
        optimize_data={}, scenarios=[], project_id="t")
    for ch in payload["channels"]:
        assert ch.get("verdict_modality") == "tentative"
        assert ch.get("verdict") in ("Scale", "Hold", "Watch", "Reduce", "Cut", "Uncertain")
    # хотя бы один директивный канал смягчён до «(предв.)»
    assert any("предв" in (ch.get("verdict_display") or "") for ch in payload["channels"])


def test_seam_channel_verdict_firm_when_reliable():
    """При reliable вердикты остаются директивными (без «(предв.)»)."""
    payload = _map_pipeline_to_builder_data(
        model_data={}, decompose_data=_DEC_DIRECTIVE,
        optimize_data={"model_reliability": MR_RELIABLE}, scenarios=[], project_id="t")
    for ch in payload["channels"]:
        assert ch.get("verdict_modality") == "firm"
        assert "предв" not in (ch.get("verdict_display") or "")


# ── Волна 3 (2026-06-20): гигиена клиентского текста ──────────────────────────

def test_sanitize_slug_no_service_word_leak():
    """Служебные слова slug НЕ текут в «Подготовлено для»; имя ≤2 токенов."""
    from engines.narrative_adapter import _sanitize_project_slug
    cl, _ = _sanitize_project_slug('кагоцел-рф--данные-для-эконометрики---на-ммх-2006-26--3')
    assert cl == 'Кагоцел Рф'
    assert 'Данные' not in cl and 'Эконометрики' not in cl and '2006' not in cl
    # дата-маркер ммх (2404 = 24 апр) не год → не протекает в имя
    assert _sanitize_project_slug('венарус-ммх-2404-26--2')[0] == 'Венарус'
    # настоящий год-диапазон сохраняется
    assert '2021-2025' in _sanitize_project_slug('mmx-2021-2025-исходник-26--4')[0]


def test_seam_carries_analysis_mode_labels():
    """Волна 3: мост доносит метку режима анализа + типа KPI из decompose."""
    payload = _map_pipeline_to_builder_data(
        model_data={}, decompose_data={
            "derived_mode": "effectiveness", "kpi_kind": "count",
            "channels": [{"name": "A", "mroas": 1.2}, {"name": "B", "mroas": 1.0}]},
        optimize_data={}, scenarios=[], project_id="t")
    d = payload["diagnostics"]
    assert d["analysis_mode_label"] == "Эффективность (доля вклада)"
    assert d["kpi_kind_label"] == "количественный"
    # дефолт (нет полей) → ROI/денежный
    payload2 = _map_pipeline_to_builder_data(
        model_data={}, decompose_data={"channels": [{"name": "A", "mroas": 1.2}, {"name": "B"}]},
        optimize_data={}, scenarios=[], project_id="t")
    assert payload2["diagnostics"]["analysis_mode_label"] == "ROI (деньги)"


def test_channel_reasoning_no_anglicisms():
    """Волна 3: клиентский reasoning без англицизмов (saturation/breakeven/Optimizer)."""
    from engines.channel_action import compute_channel_action
    samples = [
        {"name": "A", "mroas": 0.5, "current_spend": 100, "optimal_spend": 100},   # Cut
        {"name": "B", "mroas": 1.3, "current_spend": 100, "optimal_spend": 70},     # Reduce (saturation)
        {"name": "C", "mroas": 1.4, "current_spend": 100, "optimal_spend": 140},    # Scale
    ]
    for ch in samples:
        r = compute_channel_action(ch).reasoning.lower()
        for bad in ("saturation", "breakeven", "optimizer"):
            assert bad not in r, f"англицизм '{bad}' в reasoning: {r}"


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
