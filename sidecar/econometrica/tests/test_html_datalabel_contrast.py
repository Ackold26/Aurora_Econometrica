"""s48 (2026-09-14) — контраст подписей значений на графиках веб-отчёта.

Жалоба владельца: подписи значений (числа у столбцов) читаются плохо и в
тёмной, и в светлой теме. Разведка нашла один настоящий источник дефекта:
`buildForecastCompareOption` (график сравнения вариантов плана,
Projects/PULSE_s48_datalabels.md) держал цвет подписи внутри столбца
(`position: 'insideBottom'`) константой `'#ffffff'` — белым текстом поверх
заливки СЕРИИ (hero/muted-бар), а не поверх фона полотна. Заливка серии не
зависит от темы (hero-бар — тот же hex во всех трёх темах), поэтому белый
проваливал контраст на gold hero-баре и на светлом muted-баре (light/fun) —
и это воспроизводилось в любой теме, где принят именно такой вариант плана.

Починка — `labelColorForFill()` в interactive.py: выбор между тёмным ink
светлой темы и белым по относительной яркости ФАКТИЧЕСКОЙ заливки (порог
0.179, WCAG relative luminance). Остальные подписи значений (mROAS, доля
бюджета/эффекта, waterfall, optimize) лежат СНАРУЖИ фигуры — на фоне
полотна (--surface), там уже стоит pal.textColor, и он контрастен фону
карточки во всех темах (см. таблицу ДО/ПОСЛЕ в PULSE-файле) - трогать не
требовалось.

Тест не дублирует hex-значения константами: цвета читаются из СГЕНЕРИРОВАННОГО
файла токенов (aurora_html_tokens.js — тот же файл, что подключает браузер),
поэтому тест ловит и будущий ребрендинг палитры, если новый hero/muted-бар
снова окажется недостаточно контрастным с выбранным полюсом чёрный/белый.

🔴 Аудит s48 (14.09.2026): до этой правки проверка порога считала выбор цвета
питон-портом `_label_color_for_fill()` — переписанной вручную копией логики
`labelColorForFill()`, а не самим отгружаемым JS. Мутация «тело
`labelColorForFill()` в interactive.py заменено на `return '#FFFFFF';`»
(имя функции, `relLuminance`, порог 0.179 в комментарии остались нетронуты)
оставляла все 17 тестов этого файла зелёными — порт продолжал считать
правильно, а клиенту уехал бы код, всегда возвращающий белый. Теперь
`_label_color_for_fill_real()` вырезает ТЕКСТ функций `relLuminance` и
`labelColorForFill` из реально сгенерированного бандла (`bootstrap_js()`,
тот же вызов, что кладёт HTML в отчёт клиента) и исполняет его в Node —
мутация тела функции меняет то, что видит проверка (доказано мутацией,
см. отчёт: без Node тест skip, не false-green).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from aurora_html.interactive import bootstrap_js

_TOKENS_JS = Path(__file__).resolve().parent.parent / "aurora_html" / "templates" / "aurora_html_tokens.js"
_MIN_CONTRAST = 4.5  # WCAG AA, текст мелкий (<18.66px) - жёсткая норма, не 3:1
_LUMINANCE_THRESHOLD = 0.179  # см. обоснование в interactive.py::labelColorForFill

_STRINGS = {"ui": {}, "empty_states": {}, "verdicts": {}}


def _js() -> str:
    return bootstrap_js("light", "{}", "{}", _STRINGS)


def _load_theme_palettes() -> dict:
    """Читает window.AURORA_THEMES из СГЕНЕРИРОВАННОГО файла - реальные цвета,
    не переписанные вручную в тест."""
    text = _TOKENS_JS.read_text(encoding="utf-8")
    m = re.search(r"window\.AURORA_THEMES\s*=\s*(\{.*\});", text, re.S)
    assert m, "aurora_html_tokens.js: не нашёл window.AURORA_THEMES - формат файла изменился?"
    return json.loads(m.group(1))


def _rel_luminance(hex_color: str) -> float:
    """WCAG relative luminance, формула 1:1 с relLuminance() в interactive.py."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def chan(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def _contrast(hex_a: str, hex_b: str) -> float:
    la, lb = _rel_luminance(hex_a), _rel_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _extract_js_function(js: str, name: str) -> str:
    """Вырезает ТЕКСТ функции `name` из реально сгенерированного бандла —
    от `function name(` до закрывающей фигурной скобки тела (баланс скобок,
    не regex до первого `}`, тело содержит вложенные `{}`)."""
    marker = f"function {name}("
    start = js.index(marker)
    brace_start = js.index("{", start)
    depth = 0
    i = brace_start
    while i < len(js):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                return js[start:i + 1]
        i += 1
    raise AssertionError(f"не нашёл закрывающую скобку функции {name!r}")


def _label_color_for_fill_real(fill_hexes: list[str]) -> list[str]:
    """Зовёт РЕАЛЬНЫЙ отгружаемый JS (`relLuminance`/`labelColorForFill`,
    вырезанные из bootstrap_js() — того же вызова, что кладёт HTML в отчёт
    клиента), а не питон-переписку его логики. Мутация тела функции меняет
    то, что видит эта проверка — питон-порт был бы слеп к ней (доказано
    аудитом s48: подмена тела на `return '#FFFFFF';` оставляла порт зелёным).
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node не найден в PATH - нечем исполнить отгружаемый JS напрямую")
    js = _js()
    real_rel_luminance = _extract_js_function(js, "relLuminance")
    real_label_color_for_fill = _extract_js_function(js, "labelColorForFill")
    script = (
        f"{real_rel_luminance}\n{real_label_color_for_fill}\n"
        f"global.window = {{ AURORA_THEMES: {json.dumps(PALETTES)} }};\n"
        f"var fills = {json.dumps(fill_hexes)};\n"
        "console.log(JSON.stringify(fills.map(labelColorForFill)));\n"
    )
    proc = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0, f"node упал при исполнении отгружаемого JS: {proc.stderr}"
    return json.loads(proc.stdout)


PALETTES = _load_theme_palettes()


@pytest.mark.parametrize("theme", sorted(PALETTES.keys()))
@pytest.mark.parametrize("fill_key", ["heroColor", "mutedColor"])
def test_inside_bar_label_color_проходит_wcag_4_5_на_реальной_заливке(theme, fill_key):
    """Подпись ВНУТРИ заливки серии (insideBottom, buildForecastCompareOption)
    должна читаться поверх фактического hero/muted-бара своей темы.

    Цвет берёт не питон-порт, а реально отгружаемый JS (`_label_color_for_fill_real`) —
    иначе подмена тела `labelColorForFill()` в бандле проходит незамеченной."""
    fill = PALETTES[theme][fill_key]
    chosen = _label_color_for_fill_real([fill])[0]
    contrast = _contrast(chosen, fill)
    assert contrast >= _MIN_CONTRAST, (
        f"тема={theme} заливка={fill_key}={fill} выбран текст={chosen} "
        f"даёт {contrast:.2f}:1 (< {_MIN_CONTRAST}:1)"
    )


def test_forecast_compare_не_держит_белую_подпись_константой():
    """Регрессия: раньше insideBottom-подпись была `'#ffffff'` вне зависимости
    от заливки. Проверяем ИСХОДНЫЙ JS-бандл (тот же принцип, что у
    test_html_static_chart_labels.py) - не факт наличия функции, а конкретный
    фрагмент, которого физически не могло быть до правки."""
    js = _js()
    assert "function buildForecastCompareOption" in js
    fn = js.split("function buildForecastCompareOption", 1)[1].split("function initChart", 1)[0]
    assert "labelColorForFill" in fn, "нет расчёта цвета подписи по заливке"
    # Ищем именно ПРИСВОЕНИЕ (`color: '#ffffff'`), а не любое упоминание —
    # строка встречается в русском комментарии к самой правке.
    assert not re.search(r"color:\s*['\"]#fff", fn, re.I), (
        "подпись внутри столбца снова зашита белой константой"
    )


def test_labelcolorforfill_использует_порог_обоснованный_в_коде():
    """Порог 0.179 должен жить в самом JS (не только в этом тесте) - иначе
    тест и код могут разойтись молча."""
    js = _js()
    assert "0.179" in js
    assert "function labelColorForFill" in js
    assert "function relLuminance" in js
