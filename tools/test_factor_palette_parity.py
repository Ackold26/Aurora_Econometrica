"""Т3.3 (2026-07-04): канарейка паритета палитр факторов декомпозиции.

Три зеркальные палитры цветов выносимых факторов синхронизируются РУКАМИ:
  • PPTX   — aurora_pptx/charts.py::_FACTOR_RGB
  • HTML   — aurora_html/interactive.py::FACTOR_COLORS (внутри JS-шаблона)
  • Svelte — components/pipeline/ChannelTimeline.svelte::FACTOR_COLORS

При добавлении нового выносимого типа (я дополняла дважды: seasonality, category)
легко забыть одну из трёх → фактор в одном канале цветной, в другом серый
('94A3B8'/mutedColor fallback). Класс тот же, что У2 (test_frontend_schema_parity):
кросс-файловый дрейф молча. Требование: множество ключей каждой палитры ⊇
decomposer._BREAKOUT_TYPES ∪ {positive_control}.

🔴 ЯКОРЬ: добавляешь тип в _BREAKOUT_TYPES → добавь цвет во ВСЕ ТРИ палитры +
FACTOR_LABELS (Svelte) + _FACTOR_GROUP_LABELS (decomposer), и этот тест зелёный.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PPTX_CHARTS = SIDECAR / 'econometrica' / 'aurora_pptx' / 'charts.py'
HTML_INTERACTIVE = SIDECAR / 'econometrica' / 'aurora_html' / 'interactive.py'
SVELTE_TIMELINE = ROOT / 'src' / 'lib' / 'components' / 'pipeline' / 'ChannelTimeline.svelte'

# ключ (опц. в кавычках) : значение-цвет (опц. #, ровно 6 hex) — един для py/js/svelte
_KEY_COLOR_RE = re.compile(r"""['"]?([a-z_][a-z0-9_]*)['"]?\s*:\s*['"]#?[0-9A-Fa-f]{6}""")


def _palette_keys(path: Path, start_marker: str, end_marker: str) -> set[str]:
    """Ключи палитры между маркером объявления и первым закрывающим маркером."""
    text = path.read_text(encoding='utf-8')
    i = text.find(start_marker)
    assert i != -1, f'не найден маркер {start_marker!r} в {path.name}'
    j = text.find(end_marker, i + len(start_marker))
    assert j != -1, f'не найден конец {end_marker!r} после {start_marker!r} в {path.name}'
    block = text[i:j]
    return set(_KEY_COLOR_RE.findall(block))


def _required_types() -> set[str]:
    """decomposer._BREAKOUT_TYPES ∪ {positive_control} — что палитры обязаны красить."""
    from engines.decomposer import _BREAKOUT_TYPES
    return set(_BREAKOUT_TYPES) | {'positive_control'}


PALETTES = {
    'PPTX charts._FACTOR_RGB': (PPTX_CHARTS, '_FACTOR_RGB = {', '}'),
    'HTML interactive.FACTOR_COLORS': (HTML_INTERACTIVE, 'FACTOR_COLORS = {{', '}}'),
    'Svelte ChannelTimeline.FACTOR_COLORS': (SVELTE_TIMELINE, 'const FACTOR_COLORS = {', '};'),
}


def test_required_types_nonempty():
    """Санити: _BREAKOUT_TYPES реально загрузился и непуст (иначе тест бессмыслен)."""
    req = _required_types()
    assert 'seasonality' in req and 'category' in req, f'ожидались новые типы Т1/ФазаБ: {req}'
    assert len(req) >= 8, f'слишком мало типов, парсинг подозрителен: {req}'


def test_each_palette_covers_breakout_types():
    """Каждая из 3 палитр красит ВСЕ выносимые типы (+positive_control)."""
    req = _required_types()
    problems = []
    for name, (path, start, end) in PALETTES.items():
        keys = _palette_keys(path, start, end)
        missing = req - keys
        if missing:
            problems.append(f'{name}: не хватает цветов для {sorted(missing)}')
    assert not problems, 'дрейф палитр факторов:\n  ' + '\n  '.join(problems)


def test_palettes_mutually_consistent():
    """Три палитры несут ОДИН набор ключей (не только ⊇ required, но и без лишнего дрейфа)."""
    key_sets = {
        name: _palette_keys(path, start, end)
        for name, (path, start, end) in PALETTES.items()
    }
    reference = key_sets['Svelte ChannelTimeline.FACTOR_COLORS']
    problems = []
    for name, keys in key_sets.items():
        if keys != reference:
            problems.append(f'{name}: {sorted(keys ^ reference)} расходится с Svelte-эталоном')
    assert not problems, 'палитры разошлись по составу ключей:\n  ' + '\n  '.join(problems)
