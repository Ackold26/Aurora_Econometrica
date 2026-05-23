"""
aurora_html.themes - theme metadata (non-CSS config).

CSS variables per theme live in templates/aurora_html.css (generated from
Standards/tokens/build.py --target html-css).

ECharts palettes live in templates/aurora_html_tokens.js (window.AURORA_THEMES),
consumed at runtime by chart re-theming.

This module holds Python-side theme metadata used by builder.py for
initial theme resolution + fallback.
"""
from __future__ import annotations

VALID_THEMES = ('light', 'dark', 'fun')

THEME_META = {
    'light': {
        'display_name': 'Светлая',
        'display_icon': '☼',
        'color_scheme': 'light',
        'description': 'Email-friendly, деловой контекст',
    },
    'dark': {
        'display_name': 'Тёмная',
        'display_icon': '☾',
        'color_scheme': 'dark',
        'description': 'Презентация, позднее чтение',
    },
    'fun': {
        'display_name': 'Тёплая',
        'display_icon': '✦',
        'color_scheme': 'light',
        'description': 'Креативный режим',
    },
}


def resolve_initial_theme(requested: str | None) -> str:
    """Pick valid theme, fallback to 'light'."""
    if requested in VALID_THEMES:
        return requested
    return 'light'
