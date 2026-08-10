"""2026-08-10: раскрытие вердикта unknown в клиентских отчётах (HTML + PPTX).

🔴 ЧТО БЫЛО. `honesty_verdict` — одно из четырёх состояний (reliable/uncertain/
unreliable/unknown). `unknown` означает «надёжность не проверена» — например,
пересчёт вердикта упал в аварийную ветку (`aurora_html/sections.py`, локальный
`except Exception: verdict_str = "unknown"`). Плашка при этом НЕ рисовалась
вовсе (`if verdict_str not in ("unreliable", "uncertain"): return provenance_html`)
— клиент читал молчание как «всё хорошо». То же — в PPTX: бейдж «Вердикт
надёжности: качество не измерено» рисовался, но без развёрнутой оговорки,
какую получают uncertain/unreliable.

Решение владельца: отсутствие подтверждённой надёжности обязано быть видно
клиенту во ВСЕХ выходах. Текст — единый источник
`utils.diagnostics.RELIABILITY_UNKNOWN_NOTE` (SSOT, как и PROVENANCE_MISMATCH_NOTE
рядом), заголовок — «Надёжность модели не подтверждена».

Сторожа ниже покрывают: явный unknown, пустую строку, отсутствие ключа (когда
пересчёт недоступен/авариен), молчание reliable (защита от перепредупреждения),
неизменность текстов uncertain/unreliable, и единый источник текста (HTML и
PPTX не дублируют константу литералом).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from aurora_html.sections import _reliability_disclaimer_html
from aurora_pptx.builder import AuroraPPTXBuilder
from utils.diagnostics import RELIABILITY_UNKNOWN_NOTE

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")

_TITLE = "Надёжность модели не подтверждена"


def _pptx_text(prs) -> str:
    parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
    return "\n".join(parts)


def _pptx_payload(honesty_verdict=None, *, drop_key=False):
    with open(_FIXTURE, encoding="utf-8") as f:
        p = json.load(f)
    if drop_key:
        p["diagnostics"].pop("honesty_verdict", None)
    else:
        p["diagnostics"]["honesty_verdict"] = honesty_verdict
    return p


# ── 1. HTML: unknown явный, пустая строка, отсутствие ключа ────────────────


def test_html_shows_disclosure_when_verdict_explicitly_unknown():
    html = _reliability_disclaimer_html({"diagnostics": {"honesty_verdict": "unknown"}})
    assert _TITLE in html
    assert RELIABILITY_UNKNOWN_NOTE in html
    assert "reliability-disclaimer" in html


def test_html_shows_disclosure_when_verdict_empty_string():
    """Пустая строка трактуется как unknown, а не как «показывать нечего»."""
    html = _reliability_disclaimer_html({"diagnostics": {"honesty_verdict": ""}})
    assert _TITLE in html
    assert RELIABILITY_UNKNOWN_NOTE in html


def test_html_shows_disclosure_when_key_missing_and_diagnostics_empty():
    """Ключ отсутствует, диагностика пуста — пересчитать нечего, честный unknown."""
    html = _reliability_disclaimer_html({"diagnostics": {}})
    assert _TITLE in html
    assert RELIABILITY_UNKNOWN_NOTE in html


def test_html_shows_disclosure_when_recompute_crashes():
    """Аварийная ветка (2026-08-10, корень дефекта): пересчёт вердикта падает
    исключением — `checks` битого типа ломает `.get()` внутри
    `model_reliability_verdict`. Ловится `except Exception` в
    `_reliability_disclaimer_html` → verdict_str = "unknown" → плашка ОБЯЗАНА
    появиться. Раньше это был именно молчащий путь.
    """
    html = _reliability_disclaimer_html({"diagnostics": {"checks": "битые данные"}})
    assert _TITLE in html
    assert RELIABILITY_UNKNOWN_NOTE in html


# ── 2. HTML: reliable молчит (защита от перепредупреждения) ────────────────


def test_html_reliable_does_not_show_unknown_disclosure():
    html = _reliability_disclaimer_html({"diagnostics": {"honesty_verdict": "reliable"}})
    assert html == ""
    assert _TITLE not in html
    assert RELIABILITY_UNKNOWN_NOTE not in html


# ── 3. HTML: uncertain/unreliable — тексты прежние, unknown-плашка не лезет ──


def test_html_uncertain_text_unchanged():
    html = _reliability_disclaimer_html({
        "diagnostics": {
            "honesty_verdict": "uncertain",
            "honesty_caveat_text": "оговорка про тонкие данные",
        }
    })
    assert "оговорка про тонкие данные" in html
    assert _TITLE not in html
    assert RELIABILITY_UNKNOWN_NOTE not in html


def test_html_unreliable_text_unchanged():
    html = _reliability_disclaimer_html({
        "diagnostics": {
            "honesty_verdict": "unreliable",
            "honesty_caveat_text": "модель не сошлась",
        }
    })
    assert "модель не сошлась" in html
    assert _TITLE not in html
    assert RELIABILITY_UNKNOWN_NOTE not in html


def test_html_unreliable_default_text_unchanged_when_no_caveat():
    """Без honesty_caveat_text — legacy-формулировка unreliable дословно прежняя."""
    html = _reliability_disclaimer_html({"diagnostics": {"honesty_verdict": "unreliable"}})
    assert "Модель имеет высокий R-hat или много расходящихся цепей" in html


def test_html_uncertain_default_text_unchanged_when_no_caveat():
    """Без honesty_caveat_text — legacy-формулировка uncertain дословно прежняя."""
    html = _reliability_disclaimer_html({"diagnostics": {"honesty_verdict": "uncertain"}})
    assert "Узкий объём данных или слабый prior-coverage" in html


# ── 4. PPTX: те же четыре сценария unknown ──────────────────────────────────


def test_pptx_shows_disclosure_when_verdict_explicitly_unknown():
    txt = _pptx_text(AuroraPPTXBuilder(_pptx_payload("unknown")).build())
    assert _TITLE in txt
    assert RELIABILITY_UNKNOWN_NOTE in txt


def test_pptx_shows_disclosure_when_verdict_empty_string():
    txt = _pptx_text(AuroraPPTXBuilder(_pptx_payload("")).build())
    assert _TITLE in txt
    assert RELIABILITY_UNKNOWN_NOTE in txt


def test_pptx_shows_disclosure_when_key_missing():
    txt = _pptx_text(AuroraPPTXBuilder(_pptx_payload(drop_key=True)).build())
    assert _TITLE in txt
    assert RELIABILITY_UNKNOWN_NOTE in txt


# ── 5. PPTX: reliable молчит, uncertain/unreliable не меняются ─────────────


def test_pptx_reliable_does_not_show_unknown_disclosure():
    txt = _pptx_text(AuroraPPTXBuilder(_pptx_payload("reliable")).build())
    assert _TITLE not in txt
    assert RELIABILITY_UNKNOWN_NOTE not in txt


def test_pptx_uncertain_label_unchanged():
    txt = _pptx_text(AuroraPPTXBuilder(_pptx_payload("uncertain")).build())
    assert "Вердикт надёжности: требует осторожности" in txt
    assert _TITLE not in txt
    assert RELIABILITY_UNKNOWN_NOTE not in txt


def test_pptx_unreliable_label_unchanged():
    txt = _pptx_text(AuroraPPTXBuilder(_pptx_payload("unreliable")).build())
    assert "Вердикт надёжности: ненадёжна" in txt
    assert _TITLE not in txt
    assert RELIABILITY_UNKNOWN_NOTE not in txt


# ── 6. Единый источник: HTML и PPTX берут текст из константы, не из литерала ─


def test_html_disclosure_text_sourced_from_constant(monkeypatch):
    """Подмена RELIABILITY_UNKNOWN_NOTE обязана отразиться в HTML — значит
    текст импортируется, а не задублирован строкой в sections.py."""
    import utils.diagnostics as diagnostics_mod

    monkeypatch.setattr(diagnostics_mod, "RELIABILITY_UNKNOWN_NOTE", "МАРКЕР-ПОДМЕНЫ-ХТМЛ")
    html = _reliability_disclaimer_html({"diagnostics": {"honesty_verdict": "unknown"}})
    assert "МАРКЕР-ПОДМЕНЫ-ХТМЛ" in html
    assert RELIABILITY_UNKNOWN_NOTE not in html  # исходный импортированный текст — для сравнения


def test_pptx_disclosure_text_sourced_from_constant(monkeypatch):
    """Тот же сторож для PPTX-билдера."""
    import utils.diagnostics as diagnostics_mod

    monkeypatch.setattr(diagnostics_mod, "RELIABILITY_UNKNOWN_NOTE", "МАРКЕР-ПОДМЕНЫ-ПОПТХ")
    txt = _pptx_text(AuroraPPTXBuilder(_pptx_payload("unknown")).build())
    assert "МАРКЕР-ПОДМЕНЫ-ПОПТХ" in txt


# ── 7. Документ целиком: баннер и таблица каналов не противоречат друг другу ─
#
# 2026-08-10 (сторож на правку `channel_action.soften_verdict_display`): прежде
# отсутствие вердикта (None/''/пробелы) давало КАНАЛУ твёрдую директиву
# («Увеличить») наравне с reliable, а баннер сверху уже честно писал
# «Надёжность модели не подтверждена» — отчёт противоречил сам себе в ОДНОМ
# документе. Тесты ниже проверяют именно это - класс дефекта на уровне
# собранного файла (HTML/PPTX), а не изолированный вызов функции (см. секцию 1
# выше и test_soften_verdict_display_preserves_direction в
# test_deliverable_thinness_disclosure.py).

# Каналы с явной директивой (не Watch/Uncertain) - без хотя бы одного
# директивного канала тест ничего не стережёт (canonical: mroas ≥ 1.2 +
# optimal > current → Scale, см. engines.channel_action).
_DIRECTIVE_CHANNELS = {"channels": [
    {"name": "TV", "spend": 100e6, "contribution": 200e6, "roi": 2.0,
     "mroas": 1.5, "optimal_spend": 130e6, "current_spend": 100e6},
    {"name": "Social", "spend": 50e6, "contribution": 120e6, "roi": 2.4, "mroas": 1.6},
]}


def test_html_report_no_firm_badge_alongside_unknown_banner(tmp_path):
    """HTML целиком: при отсутствующем вердикте (model_data без diagnostics -
    «пересчитать нечего», тот же класс, что явный unknown) документ обязан
    показывать И баннер, И смягчённые вердикты каналов - не одно из двух.

    Собран РЕАЛЬНЫМ производственным швом (`engines.html_export.build_html`
    → `narrative_adapter._map_pipeline_to_builder_data` →
    `aurora_html.build_html`), а не вручную собранным payload — иначе тест
    проверял бы fallback-ветку `sections.py::render_action_table`
    (`c.get("verdict_display") or soften_verdict_display(verdict, None)[0]`,
    для channels без precomputed verdict_display/verdict_modality), а не
    реальный путь данных, где оба поля выставляет narrative_adapter.
    """
    from engines.html_export import build_html as _build_html_file
    from engines.narrative_adapter import _map_pipeline_to_builder_data

    payload = _map_pipeline_to_builder_data(
        model_data={}, decompose_data=_DIRECTIVE_CHANNELS,
        optimize_data={}, scenarios=[], project_id="t",
    )
    assert payload["diagnostics"].get("honesty_verdict") is None, (
        "фикстура должна давать «нет вердикта вовсе» - иначе тест проверяет не тот сценарий"
    )
    directive = [c for c in payload["channels"] if c.get("verdict") not in ("Watch", "Uncertain")]
    assert directive, "фикстура не даёт директивных каналов - тесту нечего стеречь"

    out = str(tmp_path / "report.html")
    result = _build_html_file(
        model_data={}, decompose_data=_DIRECTIVE_CHANNELS, optimize_data={},
        output_path=out, project_id="t",
    )
    assert result.get("status") == "ok", result
    html = Path(out).read_text(encoding="utf-8")

    assert _TITLE in html, "баннер «Надёжность модели не подтверждена» обязан появиться"
    assert "verdict-mod-firm" not in html, (
        "хотя бы один канал показан ТВЁРДОЙ директивой (CSS-класс verdict-mod-firm) "
        "рядом с баннером неподтверждённой надёжности - отчёт противоречит сам себе"
    )


def test_pptx_report_no_bare_firm_label_when_verdict_missing_or_empty():
    """PPTX то же самое: 5 директивных каналов фикстуры (4×Scale, 1×Cut)
    получают вердикт-метку ПРЯМО в момент сборки слайда
    (`soften_verdict_display(verdict, self.honesty_verdict)`,
    aurora_pptx/builder.py:2197), а не из precomputed поля - значит дефект
    ловится тем же способом, что и в HTML: по факту в собранном файле, а не по
    значению атрибута self.honesty_verdict."""
    firm_labels = ("Увеличить", "Остановить")  # Scale/Cut в этой фикстуре
    for случай, kwargs in (
        ("None", {"honesty_verdict": None}),
        ("пустая строка", {"honesty_verdict": ""}),
        ("ключ отсутствует", {"drop_key": True}),
    ):
        txt = _pptx_text(AuroraPPTXBuilder(_pptx_payload(**kwargs)).build())
        assert _TITLE in txt, f"{случай}: баннер unknown обязан появиться"
        # Метка вердикта - отдельный текстовый блок (одна строка на shape), в
        # отличие от статичного глоссария («Вердикт по каналу: Увеличить /
        # Держать / …») - тот единой строкой перечисляет ВСЕ метки и не
        # является per-канал бейджем. Точное совпадение целой строки отличает
        # бейдж от глоссария и не даёт ложных срабатываний.
        lines = {ln.strip() for ln in txt.split("\n")}
        for label in firm_labels:
            assert label not in lines, (
                f"{случай}: ярлык «{label}» показан твёрдой директивой без «(предв.)» "
                f"отдельным блоком - рядом с баннером неподтверждённой надёжности"
            )
