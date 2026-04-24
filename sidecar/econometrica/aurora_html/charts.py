"""
aurora_html.charts - ECharts JSON config generators.

Emits ECharts option objects for 5 chart types:
- Waterfall (decomposition)
- mROAS bar (hero channel highlighted)
- Share vs Effect (side-by-side bars)
- Timeline stacked area (baseline + top-5 channels)
- Optimize comparison (current vs optimal)

All use SVG renderer (crisp on any DPI). Theme-aware via AURORA_THEMES
lookup in generated aurora_html_tokens.js. Full implementation M3.
"""
from __future__ import annotations

from typing import Any


def build_waterfall_option(data: dict) -> dict:
    """Sales decomposition waterfall. M3."""
    return {}


def build_mroas_option(data: dict) -> dict:
    """Horizontal bar chart mROAS per channel, hero gold. M3."""
    return {}


def build_share_option(data: dict) -> dict:
    """Side-by-side bars: % бюджета vs % эффекта. M3."""
    return {}


def build_timeline_option(data: dict) -> dict:
    """Stacked area chart weekly sales decomposition + dataZoom. M3."""
    return {}


def build_optimize_option(data: dict) -> dict:
    """Comparison bars: current vs optimal per channel. M3."""
    return {}
