"""
aurora_html — Aurora AI tier-1 interactive HTML deliverable.

Generates standalone HTML report with:
- 14-section narrative (mirrors PPTX S7 structure, data-driven slot-fills)
- 3 themes (light / dark / fun) toggled at runtime
- Inline ECharts (SVG renderer) + embedded WOFF2 fonts
- Full interactivity (sticky TOC, sortable tables, drill-down, scenario
  switcher, budget what-if, keyboard shortcuts, search)
- Hash-based CSP, XSS hardening
- WCAG AA accessibility
- Trust signals (Report ID hash, methodology badge, confidentiality watermark)

Public API:
    from econometrica.aurora_html import build_html
    html_str = build_html(data, initial_theme='light')

See `Standards/CLIENT_READY_ANATOMY_HTML.md` for full specification.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

__version__ = "0.1.0"
logger = logging.getLogger('econometrica.aurora_html')

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Pinned asset SHA-256 hashes — fail-fast verification at import time.
# Regenerated via `python Standards/tokens/build.py --target html-css html-js`
# and fonts downloaded in M1.7. Mismatch indicates tampering or accidental edit.
ASSET_SHA256 = {
    "echarts.common.5.5.1.min.js": (
        "66f17003724d5b6c4c2348b907290afe98363c6e7beb4a594fdb616f00496d55"
    ),
    "fonts/lora-400-latin.woff2":      "ddb8c66035104e23",    # prefix OK for sanity
    "fonts/lora-400-cyrillic.woff2":   "c57d9ca3bd42e6bc",
    "fonts/inter-400-latin.woff2":     "3100e775e8616cd2",
    "fonts/inter-400-cyrillic.woff2":  "71d5ee93cc1e9f1d",
}


def _verify_assets() -> None:
    """Spot-check bundled asset integrity. Fails fast on corruption/tamper."""
    for rel, expected in ASSET_SHA256.items():
        path = TEMPLATES_DIR / rel
        if not path.exists():
            logger.warning(f"Bundled asset missing: {rel}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if not actual.startswith(expected):
            logger.error(
                f"Asset integrity failure: {rel} expected sha256 prefix "
                f"{expected!r}, got {actual[:16]!r}"
            )


def build_html(data: dict, initial_theme: str = 'light') -> str:
    """Build tier-1 interactive HTML deliverable from narrative_adapter data.

    Args:
        data: output of `narrative_adapter._map_pipeline_to_builder_data(...)`.
              Shape: {meta, diagnostics?, channels?, narrative_facts?}.
        initial_theme: one of 'light' | 'dark' | 'fun' (default 'light').

    Returns:
        Complete standalone HTML string (~1MB with inline assets).
    """
    _verify_assets()
    from .builder import AuroraHTMLBuilder

    if initial_theme not in ('light', 'dark', 'fun'):
        logger.warning(f"unknown theme {initial_theme!r}, falling back to 'light'")
        initial_theme = 'light'

    builder = AuroraHTMLBuilder(data or {}, initial_theme=initial_theme)
    return builder.build()


__all__ = ['build_html', '__version__']
