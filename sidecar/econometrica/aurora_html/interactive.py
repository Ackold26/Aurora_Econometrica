"""
aurora_html.interactive — JS snippets for interactivity.

Composed into one `<script>` block in shell.html at build time, then
SHA-256 hashed for CSP.

Features (full in M3):
- TOC scroll-spy (IntersectionObserver)
- Sortable action table (click <th>, persist sort)
- Drill-down side-panel
- Scenario switcher dropdown
- Budget what-if slider (Hill saturation in JS; per-channel params available)
- Timeline dataZoom
- Keyboard shortcuts (T / ? / 1-9 / Ctrl+K / Esc / P / C)
- Search/filter action table
- Animated number counters (respects prefers-reduced-motion)
- Loading skeletons
- Section fade-in staggered
- Scroll progress bar
- Copy-link / copy-CSV / copy-PNG helpers
- Theme toggle (cycles light → dark → fun, updates ECharts, persists)
- Error boundary (window.onerror graceful fallback)
"""
from __future__ import annotations


def bootstrap_js(theme_preference_key: str = 'aurora-html-theme') -> str:
    """Root JS bundle — resolves theme + binds ECharts + event listeners.

    M3 implementation. Returns compact JS string.
    """
    return ""  # M3


def keyboard_shortcuts_js() -> str:
    """Global keydown handler — M3."""
    return ""
