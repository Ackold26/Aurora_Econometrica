"""s48, продолжение (2026-09-14) — фон выгружаемой PNG-картинки графика.

Нашла при приёмке: `setupCopyPng()` (interactive.py, кнопки «Сохранить PNG» —
это ЕДИНСТВЕННЫЙ код-путь выгрузки графика картинкой в отчёте, обслуживает
все 9 кнопок `data-copy-chart`, grep по `getDataURL`/`toDataURL`/`canvas` в
aurora_html/*.py подтверждает: других мест нет) вызывал
`chart.getDataURL({..., backgroundColor: '#ffffff'})` — белым константой,
а весь текст графика (подписи значений, оси, легенда) красится под фон
ТЕКУЩЕЙ темы через `pal.textColor`/`pal.textMutedColor` (currentPalette()).
В тёмной теме это светлый текст поверх белого фона картинки — контраст
падал до ~1.2:1 (textColor) и ~2.3:1 (textMutedColor), при этом сам экран
внутри приложения читался нормально: дефект был виден только в
экспортированном файле.

Правка: `currentSurfaceColor()` читает `--surface` текущей темы из
computed style документа — тот же фон, что уже стоит под графиком на экране
(.chart-container{background:var(--surface)}, layout.css) — и передаёт его
в getDataURL. Картинка тогда самосогласована в любой теме (тот же фон, что
на экране, с тем же текстом, что на экране).

Тест не выполняет getDataURL в браузере (пакет не тянет headless-браузер —
тот же принцип, что у test_html_static_chart_labels.py и
test_html_datalabel_contrast.py: дешёвая проверка на уровне текста бандла +
пересчёт контраста на РЕАЛЬНЫХ значениях из двух сгенерированных файлов
токенов (aurora_html.css - фон --surface; aurora_html_tokens.js - текст
темы), а не на продублированных константах).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from aurora_html.interactive import bootstrap_js

_ROOT = Path(__file__).resolve().parent.parent / "aurora_html" / "templates"
_CSS = _ROOT / "aurora_html.css"
_TOKENS_JS = _ROOT / "aurora_html_tokens.js"
_MIN_CONTRAST = 4.5

_STRINGS = {"ui": {}, "empty_states": {}, "verdicts": {}}


def _js() -> str:
    return bootstrap_js("light", "{}", "{}", _STRINGS)


def _rel_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def chan(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def _contrast(hex_a: str, hex_b: str) -> float:
    la, lb = _rel_luminance(hex_a), _rel_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _load_surfaces() -> dict:
    """Реальный --surface каждой темы из СГЕНЕРИРОВАННОГО aurora_html.css -
    того же файла, что подключает браузер."""
    css = _CSS.read_text(encoding="utf-8")
    out = {}
    for theme in ("light", "dark", "fun"):
        block = re.search(r'\[data-theme="%s"\]\s*\{([^}]*)\}' % theme, css, re.S)
        assert block, f"aurora_html.css: нет блока [data-theme=\"{theme}\"] - формат файла изменился?"
        surf = re.search(r"--surface:\s*(#[0-9A-Fa-f]{6})", block.group(1))
        assert surf, f"aurora_html.css: нет --surface в теме {theme}"
        out[theme] = surf.group(1)
    return out


def _load_theme_palettes() -> dict:
    text = _TOKENS_JS.read_text(encoding="utf-8")
    m = re.search(r"window\.AURORA_THEMES\s*=\s*(\{.*\});", text, re.S)
    assert m, "aurora_html_tokens.js: не нашёл window.AURORA_THEMES"
    return json.loads(m.group(1))


SURFACES = _load_surfaces()
PALETTES = _load_theme_palettes()


@pytest.mark.parametrize("theme", sorted(SURFACES.keys()))
@pytest.mark.parametrize("text_key", ["textColor", "textMutedColor"])
def test_exported_png_фон_даёт_wcag_4_5_с_текстом_темы(theme, text_key):
    """Фон экспортируемой PNG (= --surface текущей темы, после правки) должен
    контрастировать с тем же текстом, каким график и рисуется на экране."""
    surface = SURFACES[theme]
    text_color = PALETTES[theme][text_key]
    contrast = _contrast(surface, text_color)
    assert contrast >= _MIN_CONTRAST, (
        f"тема={theme} {text_key}={text_color} на фоне экспорта --surface={surface} "
        f"даёт {contrast:.2f}:1 (< {_MIN_CONTRAST}:1)"
    )


def test_export_png_регрессия_белый_фон_константой_не_вернулась():
    """Раньше здесь была `backgroundColor: '#ffffff'` вне зависимости от темы -
    в дальнейшем не должна тихо вернуться."""
    js = _js()
    assert "function setupCopyPng" in js
    fn = js.split("function setupCopyPng", 1)[1].split("function ", 1)[0]
    assert "currentSurfaceColor()" in fn, "фон экспорта больше не читает --surface текущей темы"
    assert not re.search(r"backgroundColor:\s*['\"]#fff", fn, re.I), (
        "фон экспортируемой PNG снова зашит белой константой"
    )


def test_export_png_фон_идёт_через_setoption_а_не_через_getdataurl_опцию():
    """Регрессия на конкретную граблю: хосты инициализированы renderer:'svg'
    (initChart/initChartFromHost), а у SVG-рендерера getDataURL() полностью
    игнорирует свои опции (проверено на живом отчёте: backgroundColor в
    getDataURL() не долетал до SVG). Фон обязан идти через chart.setOption()
    ДО getDataURL(), иначе фикс контраста молча ничего не чинит."""
    js = _js()
    assert "renderer: 'svg'" in js, "хосты уже не renderer:'svg' - проверка выше устарела"
    fn = js.split("function setupCopyPng", 1)[1].split("function ", 1)[0]
    assert re.search(r"setOption\(\{\s*backgroundColor:\s*currentSurfaceColor\(\)", fn), (
        "фон экспорта не выставлен через chart.setOption() перед getDataURL()"
    )
    assert not re.search(r"getDataURL\(\{[^}]*backgroundColor", fn), (
        "backgroundColor передан аргументом в getDataURL() - у svg-рендерера он там молча игнорируется"
    )


def test_currentsurfacecolor_читает_css_переменную_surface():
    """Регрессия на способ чтения фона: должен быть computed style документа,
    не повторно захардкоженный список цветов по темам."""
    js = _js()
    assert "function currentSurfaceColor" in js
    fn = js.split("function currentSurfaceColor", 1)[1].split("function ", 1)[0]
    assert "--surface" in fn
    assert "getComputedStyle" in fn
