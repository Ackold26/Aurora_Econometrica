"""Доля канала в медиа-вкладе — одно число из одного источника на всех
поверхностях отчёта (s50, 27.09.2026, INV-50: число на экране равно расчёту).

Дефект (аудит s50, H-1 и M-1): после перевода столбца «Доля» таблицы каналов
на одну десятую (af8c2015) на ОДНОМ слайде стояли заголовок «Один канал даёт
88% продаж» и строка таблицы «87.5». Доля лидера в тексте отчёта тоже шла
целым («88% медиа-вклада»). Знаменатели разъехались: веб-таблица делила на
видимые 10 каналов, презентация — на все, факты адаптера — на сумму после
слияния; на 12 каналах веб показывал 30.3, презентация 30.0. В браузере
счётчик крупного числа вдобавок переписывал «87.5%» в «88%».

Правило-источник: utils.kpi_display.channel_share_pcts — готовое
`contribution_pct` канала из движка (decomposer.py, знаменатель — весь
медиа-вклад), фолбэк для результата без поля — по ВСЕМ каналам. Заголовок
«топ-N дают X%» — сумма УЖЕ ОКРУГЛЁННЫХ долей строк.

Сторож читает ВИДИМОЕ число: текст ячейки веб-таблицы (не `data-sort`),
текст слайдов собранной презентации, счётчик крупного числа — исполнением
отгружаемого JS в Node.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from engines.narrative_adapter import _map_pipeline_to_builder_data  # noqa: E402
from utils.kpi_display import channel_share_pcts  # noqa: E402

LEADER = "Канал A"


def _dec_875():
    """87.5 / 7.5 / 5.0 — целое округление даёт 88+8+5 = 101."""
    return {"channels": [
        {"name": LEADER, "spend": 1_000_000.0, "contribution": 875.0,
         "contribution_pct": 87.5, "roi": 1.5},
        {"name": "Канал B", "spend": 200_000.0, "contribution": 75.0,
         "contribution_pct": 7.5, "roi": 1.2},
        {"name": "Канал C", "spend": 100_000.0, "contribution": 50.0,
         "contribution_pct": 5.0, "roi": 0.8},
    ]}


def _dec_12(with_pct: bool):
    """12 каналов, видимых в таблице 10: лидер 300 из 1000 = 30.0%.
    Делитель по видимым (970) дал бы 30.9 — расхождение M-1."""
    contribs = [300, 150, 100, 90, 80, 70, 60, 50, 40, 30, 20, 10]
    chs = []
    for i, v in enumerate(contribs):
        ch = {"name": f"Канал {i + 1:02d}", "spend": 100_000.0 * (12 - i),
              "contribution": float(v), "roi": 1.0 + i / 10}
        if with_pct:
            ch["contribution_pct"] = round(v / 1000 * 100, 1)
        chs.append(ch)
    return {"channels": chs}


def _dec_rounding_edge():
    """50.14 + 35.34 = 85.48: округление накопления дало бы 85.5 (прежде —
    целое 85), а сумма видимых строк 50.1 + 35.3 = 85.4. Поля contribution_pct
    нет — заодно проверяется фолбэк сохранённых результатов без поля."""
    return {"channels": [
        {"name": "Канал X", "spend": 500_000.0, "contribution": 5014.0, "roi": 1.4},
        {"name": "Канал Y", "spend": 400_000.0, "contribution": 3534.0, "roi": 1.1},
        {"name": "Канал Z", "spend": 300_000.0, "contribution": 1452.0, "roi": 0.9},
    ]}


def _payload(dec):
    return _map_pipeline_to_builder_data(
        model_data={}, decompose_data=dec, optimize_data={}, scenarios=[], project_id="t",
    )


def _html(dec) -> str:
    from engines.html_export import build_html
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "report.html")
        res = build_html(model_data={}, decompose_data=dec, optimize_data={},
                         output_path=out, project_id="t")
        assert res.get("status") == "ok", res
        with open(out, encoding="utf-8") as fh:
            return fh.read()


def _plain(html: str) -> str:
    """Видимый текст: без тегов и без тел <script>/<style>."""
    html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _html_visible_shares(html: str) -> dict[str, str]:
    """Видимый текст ячейки «Доля» каждой строки таблицы каналов — НЕ атрибут
    data-sort (аудит s50, M-3: тест по data-sort не видел, что читает клиент).
    Строка: канал, бюджет, вклад, метрика, доля, вердикт — доля = 4-я num-ячейка."""
    out = {}
    for name, row in re.findall(r'<tr data-channel="([^"]*)">(.*?)</tr>', html, re.S):
        nums = re.findall(r'<td class="num"[^>]*>(.*?)</td>', row, re.S)
        assert len(nums) == 4, f"строка {name!r}: ожидали 4 числовые ячейки, нашли {len(nums)}"
        out[name] = re.sub(r"<[^>]+>", "", nums[3]).strip()
    return out


def _pptx(payload):
    try:
        from aurora_pptx.builder import AuroraPPTXBuilder
    except ImportError as e:  # pragma: no cover
        pytest.skip(f"AuroraPPTXBuilder недоступен: {e}")
    b = AuroraPPTXBuilder(payload)
    prs = b.build()
    texts = []
    for slide in prs.slides:
        for sh in slide.shapes:
            if sh.has_text_frame:
                texts.append(sh.text_frame.text.replace("\n", " "))
    rows = {r[0]: r[4] for r in b._build_action_table_rows(b.channels)}
    return " | ".join(texts), rows


# Фразы, где число — доля канала в эффекте: «87.5% медиа-вклада»,
# «даёт 87.5% продаж», «даёт 87.5% эффекта».
_SHARE_PHRASE = re.compile(r"(\d+(?:\.\d+)?)%\s*(?:медиа-вклада|продаж|эффекта)")


# ─── Правило-источник ────────────────────────────────────────────────────────

def test_source_is_engine_contribution_pct_not_recount():
    """Поле движка — источник: даже если пересчёт от вкладов дал бы другое
    (канал выпал при слиянии имён), показывается contribution_pct."""
    chs = [
        {"name": "A", "contribution": 875.0, "contribution_pct": 87.4},
        {"name": "B", "contribution": 125.0, "contribution_pct": 12.6},
    ]
    assert channel_share_pcts(chs) == [87.4, 12.6]


def test_fallback_without_field_uses_all_channels():
    """Старый результат без contribution_pct: знаменатель — ВСЕ каналы,
    а не видимые строки."""
    chs = _dec_12(with_pct=False)["channels"]
    shares = channel_share_pcts(chs)
    assert shares[0] == 30.0
    assert shares[:10] != [round(v / 970 * 100, 1) for v in (300, 150, 100, 90, 80, 70, 60, 50, 40, 30)]


def test_partial_field_falls_back_for_all_channels():
    """Смешанный список (у части каналов поля нет) не смешивает знаменатели."""
    chs = [
        {"name": "A", "contribution": 600.0, "contribution_pct": 99.0},
        {"name": "B", "contribution": 400.0},
    ]
    assert channel_share_pcts(chs) == [60.0, 40.0]


def test_adapter_carries_engine_field_to_payload():
    p = _payload(_dec_875())
    assert [c["contribution_pct"] for c in p["channels"]] == [87.5, 7.5, 5.0]
    assert p["narrative_facts"]["leader_share_contrib_pct"] == 87.5


# ─── Видимое число лидера одинаково на всех поверхностях ─────────────────────

def test_leader_share_same_visible_number_everywhere_875():
    dec = _dec_875()
    html = _html(dec)
    web_rows = _html_visible_shares(html)
    assert web_rows[LEADER] == "87.5", f"строка лидера веб-таблицы: {web_rows!r}"

    plain = _plain(html)
    web_phrases = _SHARE_PHRASE.findall(plain)
    assert web_phrases, "в веб-отчёте не нашлось ни одной фразы с долей лидера"
    assert set(web_phrases) == {"87.5"}, f"доля лидера в тексте веб-отчёта: {web_phrases!r}"
    assert "Один канал даёт 87.5% медиа-вклада" in plain, "заголовок S7 веб-отчёта"
    big = re.search(r'<div class="big-number" data-counter-end="([^"]*)">([^<]*)</div>', html)
    assert big and big.group(2) == "87.5%" and big.group(1) == "87.5", \
        f"крупное число доли лидера: {big.groups() if big else None!r}"
    assert "88%" not in plain

    text, pptx_rows = _pptx(_payload(dec))
    assert pptx_rows[LEADER] == "87.5", f"строка лидера презентации: {pptx_rows!r}"
    pptx_phrases = _SHARE_PHRASE.findall(text)
    assert pptx_phrases, "в презентации не нашлось ни одной фразы с долей лидера"
    assert set(pptx_phrases) == {"87.5"}, f"доля лидера в тексте презентации: {pptx_phrases!r}"
    assert "он даёт 87.5% медиа-вклада" in text, "заголовок S7 презентации"
    assert "88%" not in text


@pytest.mark.parametrize("with_pct", [True, False], ids=["поле движка", "фолбэк без поля"])
def test_12_channels_web_and_pptx_agree(with_pct):
    """M-1: веб делил на видимые 10 каналов (30.9), презентация — на все (30.0)."""
    dec = _dec_12(with_pct)
    web_rows = _html_visible_shares(_html(dec))
    assert len(web_rows) == 10
    _, pptx_rows = _pptx(_payload(dec))
    assert web_rows["Канал 01"] == pptx_rows["Канал 01"] == "30.0", (web_rows, pptx_rows)
    assert web_rows == pptx_rows


def test_builders_without_field_use_all_channels():
    """Построители, получившие каналы БЕЗ contribution_pct (данные собраны мимо
    адаптера), считают долю по ВСЕМ каналам, а не по видимым 10 строкам."""
    payload = _payload(_dec_12(with_pct=False))
    for c in payload["channels"]:
        c.pop("contribution_pct", None)
    from aurora_html import build_html as build_html_from_payload
    web_rows = _html_visible_shares(build_html_from_payload(payload))
    _, pptx_rows = _pptx(payload)
    assert web_rows["Канал 01"] == pptx_rows["Канал 01"] == "30.0", (web_rows, pptx_rows)


def _top_n_pct(text: str) -> str:
    m = re.search(r"(?:дают|обеспечивают) (\d+(?:\.\d+)?)% медиа-вклада", text)
    assert m, f"заголовок «топ-N дают X%» не найден: {text[:300]!r}"
    return m.group(1)


def test_top_n_title_equals_sum_of_visible_rows():
    """Заголовок топ-N = сумма ВИДИМЫХ строк топ-N, а не округлённое накопление."""
    dec = _dec_rounding_edge()
    html = _html(dec)
    web_rows = _html_visible_shares(html)
    assert list(web_rows.values()) == ["50.1", "35.3", "14.5"]
    top2 = f"{float(web_rows['Канал X']) + float(web_rows['Канал Y']):.1f}"
    assert top2 == "85.4"
    assert _top_n_pct(_plain(html)) == top2, "заголовок S7 веб-отчёта ≠ сумме строк топ-2"

    text, pptx_rows = _pptx(_payload(dec))
    assert pptx_rows == web_rows
    assert _top_n_pct(text) == top2, "заголовок S7 презентации ≠ сумме строк топ-2"


def test_12_channels_top_n_title_equals_sum_of_visible_rows():
    dec = _dec_12(with_pct=True)
    html = _html(dec)
    web_rows = list(_html_visible_shares(html).values())
    # накопление до 85%: 300+150+100+90+80+70+60 = 850 → топ-7
    top7 = f"{sum(float(v) for v in web_rows[:7]):.1f}"
    assert top7 == "85.0"
    assert _top_n_pct(_plain(html)) == top7


def _deck_two_channels(leader_pct, out):
    from aurora_pptx.builder import AuroraPPTXBuilder
    rest = round(100.0 - leader_pct, 1)
    dec = {"channels": [
        {"name": LEADER, "spend": 1_000_000.0, "contribution": leader_pct * 10,
         "contribution_pct": leader_pct, "roi": 1.5},
        {"name": "Канал B", "spend": 300_000.0, "contribution": rest * 10,
         "contribution_pct": rest, "roi": 0.5},
    ]}
    prs = AuroraPPTXBuilder(_payload(dec)).build()
    prs.save(out)
    return prs


@pytest.mark.parametrize("leader_pct", [
    87.5,
    pytest.param(100.0, marks=pytest.mark.xfail(strict=True, reason=(
        "Открыто (s50): «100.0%» – 6 знаков, проверка переполнения не считает его "
        "декором (DECOR_MAX_LEN = 5) и видит наезд оценки высоты строки на подпись "
        "под числом на 0.2\". Сторож не ослабляется, решение – за ведущим."))),
])
def test_pptx_big_number_with_decimal_fits(leader_pct, tmp_path):
    """Крупное число доли лидера с одной десятой («87.5%», крайний «100.0%»)
    шире целого и при кегле 140 уходило второй строкой за низ слайда. Проверка
    переполнения – целиком, без фильтров."""
    from aurora_pptx.check_overflow import check
    out = str(tmp_path / "deck.pptx")
    _deck_two_channels(leader_pct, out)
    issues, _ = check(out)
    assert issues == [], "\n".join(f"слайд {s}: [{k}] {d}" for s, k, d in issues)


def test_pptx_big_number_100_stays_one_line(tmp_path):
    """Крайний случай «100.0%»: само число – в одну строку своего бокса (кегль
    ужимается), а не переносом за низ слайда. Мерка – та же, что у проверки
    переполнения (text_metrics)."""
    from aurora_pptx import text_metrics as TM
    prs = _deck_two_channels(100.0, str(tmp_path / "deck.pptx"))
    shapes = [sh for slide in prs.slides for sh in slide.shapes
              if sh.has_text_frame and sh.text_frame.text.strip() == "100.0%"]
    assert shapes, "крупное число «100.0%» не найдено в колоде"
    for sh in shapes:
        run = sh.text_frame.paragraphs[0].runs[0]
        size_pt = run.font.size.pt
        lines = TM.wrap_lines("100.0%", int(sh.width), size_pt, font_name=run.font.name or "Georgia")
        assert lines == 1, f"«100.0%» кеглем {size_pt} в боксе {sh.width / 914400:.2f}\" – строк {lines}"


# ─── Счётчик крупного числа в браузере ────────────────────────────────────────

def _extract_js_function(js: str, name: str) -> str:
    start = js.index(f"function {name}(")
    i = js.index("{", start)
    depth = 0
    while i < len(js):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                return js[start:i + 1]
        i += 1
    raise AssertionError(f"не нашёл конец функции {name!r}")


@pytest.mark.parametrize("reduced_motion", [True, False], ids=["без анимации", "с анимацией"])
def test_big_number_counter_keeps_one_decimal(reduced_motion):
    """Отгружаемый JS счётчика (setupCounters → animateCounter) исполняется в
    Node на элементе с data-counter-end="87.5": на экране остаётся «87.5%»,
    а не «88%». Целое значение остаётся целым."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node не найден в PATH — нечем исполнить отгружаемый JS")
    from aurora_html.interactive import bootstrap_js
    js = bootstrap_js("light", "{}", "{}", {"ui": {}, "empty_states": {}, "verdicts": {}})
    funcs = "\n".join(_extract_js_function(js, n) for n in (
        "counterDecimals", "counterText", "animateCounter", "formatCounterValue", "setupCounters",
    ))
    script = (
        f"var PREFERS_REDUCED_MOTION = {'true' if reduced_motion else 'false'};\n"
        "var t = 0; global.requestAnimationFrame = function(f) { t += 5000; f(t); };\n"
        "function IO(cb) { this.observe = function(n) { cb([{isIntersecting: true, target: n}]); };"
        " this.unobserve = function() {}; }\n"
        "global.IntersectionObserver = IO; global.window = { IntersectionObserver: IO };\n"
        "function El(end, text) { this.textContent = text;"
        " this.getAttribute = function() { return end; }; }\n"
        "var els = [new El('87.5', '87.5%'), new El('42', '42%')];\n"
        "global.document = { querySelectorAll: function() { return els; } };\n"
        f"{funcs}\n"
        "setupCounters();\n"
        "console.log(JSON.stringify(els.map(function(e) { return e.textContent; })));\n"
    )
    proc = subprocess.run([node, "-e", script], capture_output=True, text=True,
                          timeout=15, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == ["87.5%", "42%"]
