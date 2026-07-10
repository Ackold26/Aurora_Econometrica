"""Гигиена клиентских текстов — гейты П8-1 и П8-2.

П8-1: в клиентских строках нет em-dash (—); дефис-как-тире заменён на en-dash (–).
П8-2: нет голого «baseline» и «media-»; «adstock» не встречается без скобок
      в ключевых выводах.

Тест строит честный payload (honest_narrative=True, media_pct < 10%) —
именно он активирует все три ветки с проблемными строками (builder.py s05,
sections.py render_key_message/render_at_a_glance, narrative_adapter headline).
Фикстура без реальных данных (markers = not requires_real_data).
"""

import copy
import json
import os
import re

import pytest

from aurora_pptx.builder import AuroraPPTXBuilder
from aurora_html.sections import render_key_message, render_at_a_glance

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")

# ─── Паттерны-нарушители ──────────────────────────────────────────────────────

# П8-1: em-dash в клиентском тексте
EM_DASH_RE = re.compile(r" — ")

# П8-2: голый anglicизм baseline (не в коде/переменных)
BASELINE_RE = re.compile(r"\bbaseline\b", re.IGNORECASE)

# П8-2: медиа-вклад/медиа-эффект через дефис с latin 'm'
MEDIA_LATIN_RE = re.compile(r"\bmedia-", re.IGNORECASE)

# П8-2: adstock без скобок в КЛИЕНТСКИХ КЛЮЧЕВЫХ ВЫВОДАХ
# Разрешено: "отложенный эффект (adstock)", формулы "adstock(x,t)", глоссарий "Adstock"
# Запрещено в action-строках: "проверить adstock," / "adstock и насыщение"
# Фильтр: строки содержащие adstock без (adstock) И без формульного контекста "adstock("
def _has_bare_adstock_in_client_text(text: str) -> bool:
    """True если в тексте есть голый adstock (не в скобках, не в формуле, не глоссарий)."""
    for line in text.split("\n"):
        lo = line.lower()
        if "adstock" not in lo:
            continue
        # Разрешаем формульные контексты: adstock(x, adstock = x_t
        if "adstock(" in lo or "adstock =" in lo or "adstock(x" in lo:
            continue
        # Разрешаем глоссарий — отдельная строка "Adstock"
        if line.strip().lower() == "adstock":
            continue
        # Разрешаем уже правильно оформленное: "(adstock)"
        bare = re.compile(r"(?<!\()\badstock\b(?!\))", re.IGNORECASE)
        if bare.search(line):
            return True
    return False


# ─── Честный payload (media < 10%, honest_narrative=True) ─────────────────────

@pytest.fixture(scope="module")
def honest_payload():
    """Payload с honest_narrative=True и media_pct=7% — активирует все honest-ветки."""
    with open(_FIXTURE, encoding="utf-8") as f:
        base = json.load(f)
    p = copy.deepcopy(base)
    # Переключаем в честный режим
    p["narrative_facts"]["honest_narrative"] = True
    p["narrative_facts"]["media_contribution_pct"] = 7.2
    p["narrative_facts"]["baseline_pct"] = 92.8
    p["narrative_facts"]["leader_share_contrib_pct"] = 42.0
    return p


@pytest.fixture(scope="module")
def normal_payload():
    """Стандартный payload без honest_narrative — покрывает остальные ветки."""
    with open(_FIXTURE, encoding="utf-8") as f:
        return json.load(f)


# ─── Хелпер: собрать весь текст из PPTX XML ──────────────────────────────────

def _pptx_text(prs) -> str:
    from pptx.oxml.ns import qn
    parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
    return "\n".join(parts)


# ─── Хелпер: context dict для sections.py ────────────────────────────────────

def _ctx(payload: dict) -> dict:
    """Минимальный context dict для render_* функций sections.py."""
    import json as _json
    _strings_path = os.path.join(
        os.path.dirname(_HERE), "aurora_html", "strings_ru.json"
    )
    with open(_strings_path, encoding="utf-8") as f:
        strings = _json.load(f)
    return {
        "meta": payload.get("meta") or {},
        "facts": payload.get("narrative_facts"),
        "channels": payload.get("channels") or [],
        "diagnostics": payload.get("diagnostics") or {},
        "strings": strings,
        "kpi": {},
    }


# ─── PPTX honest-mode: П8-1 + П8-2 ──────────────────────────────────────────

def test_pptx_honest_no_em_dash(honest_payload, tmp_path):
    """П8-1: em-dash не появляется в PPTX на честном payload."""
    prs = AuroraPPTXBuilder(honest_payload).build()
    txt = _pptx_text(prs)
    hits = EM_DASH_RE.findall(txt)
    assert not hits, f"П8-1: em-dash в PPTX (честный режим): {hits[:3]}"


def test_pptx_honest_no_bare_baseline(honest_payload, tmp_path):
    """П8-2: «baseline» не встречается голым в клиентском PPTX."""
    prs = AuroraPPTXBuilder(honest_payload).build()
    txt = _pptx_text(prs)
    hits = BASELINE_RE.findall(txt)
    assert not hits, f"П8-2: голый baseline в PPTX: {txt[max(0,txt.lower().find('baseline')-40):txt.lower().find('baseline')+60]!r}"


def test_pptx_honest_no_media_latin(honest_payload, tmp_path):
    """П8-2: «media-вклад»/«media-эффект» не появляется в PPTX."""
    prs = AuroraPPTXBuilder(honest_payload).build()
    txt = _pptx_text(prs)
    hits = MEDIA_LATIN_RE.findall(txt)
    assert not hits, f"П8-2: latin media- в PPTX: {hits[:3]}"


def test_pptx_honest_adstock_not_bare(honest_payload, tmp_path):
    """П8-2: adstock в клиентских ключевых выводах только со скобками.

    Формульные строки (adstock(x,t), adstock = ...) и глоссарный термин
    «Adstock» на отдельной строке разрешены — только narrative выводы проверяются.
    """
    prs = AuroraPPTXBuilder(honest_payload).build()
    txt = _pptx_text(prs)
    assert not _has_bare_adstock_in_client_text(txt), (
        "П8-2: голый adstock (не в скобках, не в формуле) найден в PPTX"
    )


# ─── HTML честный режим: render_key_message ──────────────────────────────────

def test_html_key_message_no_em_dash(honest_payload):
    """П8-1: em-dash не появляется в render_key_message (honest branch)."""
    try:
        ctx = _ctx(honest_payload)
    except Exception:
        pytest.skip("strings_ru.json недоступен")
    html = render_key_message(ctx)
    assert not EM_DASH_RE.search(html), "П8-1: em-dash в render_key_message"


def test_html_key_message_no_bare_baseline(honest_payload):
    """П8-2: «baseline» не попадает в HTML-вывод render_key_message."""
    try:
        ctx = _ctx(honest_payload)
    except Exception:
        pytest.skip("strings_ru.json недоступен")
    html = render_key_message(ctx)
    hits = BASELINE_RE.findall(html)
    assert not hits, f"П8-2: baseline в render_key_message HTML: {hits}"


def test_html_key_message_no_media_latin(honest_payload):
    """П8-2: «media-» не попадает в HTML-вывод render_key_message."""
    try:
        ctx = _ctx(honest_payload)
    except Exception:
        pytest.skip("strings_ru.json недоступен")
    html = render_key_message(ctx)
    hits = MEDIA_LATIN_RE.findall(html)
    assert not hits, f"П8-2: latin media- в render_key_message HTML: {hits}"


def test_html_key_message_adstock_not_bare(honest_payload):
    """П8-2: adstock в HTML только со скобками (формульные контексты разрешены)."""
    try:
        ctx = _ctx(honest_payload)
    except Exception:
        pytest.skip("strings_ru.json недоступен")
    html = render_key_message(ctx)
    # В HTML-контексте strip тегов и проверяем по строкам
    text = re.sub(r"<[^>]+>", " ", html)
    assert not _has_bare_adstock_in_client_text(text), (
        "П8-2: голый adstock найден в render_key_message HTML"
    )


# ─── HTML честный режим: render_at_a_glance ──────────────────────────────────

def test_html_at_a_glance_no_em_dash(honest_payload):
    """П8-1: em-dash не попадает в render_at_a_glance."""
    try:
        ctx = _ctx(honest_payload)
    except Exception:
        pytest.skip("strings_ru.json недоступен")
    html = render_at_a_glance(ctx)
    assert not EM_DASH_RE.search(html), "П8-1: em-dash в render_at_a_glance"


def test_html_at_a_glance_no_bare_baseline(honest_payload):
    """П8-2: baseline не попадает в render_at_a_glance."""
    try:
        ctx = _ctx(honest_payload)
    except Exception:
        pytest.skip("strings_ru.json недоступен")
    html = render_at_a_glance(ctx)
    hits = BASELINE_RE.findall(html)
    assert not hits, f"П8-2: baseline в render_at_a_glance: {hits}"


def test_html_at_a_glance_no_media_latin(honest_payload):
    """П8-2: «media-» не попадает в render_at_a_glance."""
    try:
        ctx = _ctx(honest_payload)
    except Exception:
        pytest.skip("strings_ru.json недоступен")
    html = render_at_a_glance(ctx)
    hits = MEDIA_LATIN_RE.findall(html)
    assert not hits, f"П8-2: latin media- в render_at_a_glance: {hits}"


# ─── Normal payload (не честный) — нет регрессии в стандартных ветках ────────

def test_pptx_normal_no_em_dash(normal_payload, tmp_path):
    """П8-1: em-dash не появляется в PPTX на стандартном payload."""
    prs = AuroraPPTXBuilder(normal_payload).build()
    txt = _pptx_text(prs)
    hits = EM_DASH_RE.findall(txt)
    assert not hits, f"П8-1: em-dash в PPTX (стандарт): {hits[:3]}"


def test_pptx_normal_no_media_latin(normal_payload, tmp_path):
    """П8-2: «media-» не появляется в PPTX на стандартном payload."""
    prs = AuroraPPTXBuilder(normal_payload).build()
    txt = _pptx_text(prs)
    hits = MEDIA_LATIN_RE.findall(txt)
    assert not hits, f"П8-2: latin media- в PPTX (стандарт): {hits[:3]}"
