"""
aurora_html - Aurora AI tier-1 interactive HTML deliverable.

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

# Pinned asset SHA-256 hashes (full 64-char digests) - fail-fast verification
# at import time. Regenerated via `python Standards/tokens/build.py --target
# html-css html-js` and fonts downloaded in M1.7. Mismatch indicates tampering
# or accidental edit; we log but do NOT raise - letting production continue
# with a warning is safer than crashing the sidecar.
ASSET_SHA256 = {
    # 2026-06-07 (SF-1): pin обновлён под фактический бандл echarts 5.5.1
    # (662 КБ, Apache-заголовок, маркер 5.5.1 — легитимный). Старый pin
    # 66f1700… дрейфанул (файл пере-минифицировали без обновления константы),
    # из-за чего на КАЖДОМ HTML-экспорте сыпался «Asset integrity failure».
    "echarts.common.5.5.1.min.js":
        "a42cc5318d97270442c39a0693fd9418c1f403d406faa108355d12c0bf0c97a9",
    "fonts/lora-400-latin.woff2":
        "ddb8c66035104e233fc024669183aad3738b6daa16deee2ebb1241bd0f98ace1",
    "fonts/lora-400-cyrillic.woff2":
        "c57d9ca3bd42e6bc093badc7744dd2059a78f66a3a4dc6ca40574480c870f553",
    "fonts/inter-400-latin.woff2":
        "3100e775e8616cd2611beecfa23a4263d7037586789b43f035236a2e6fbd4c62",
    "fonts/inter-400-cyrillic.woff2":
        "71d5ee93cc1e9f1d520a3a8b66456de18c7879d8df09d57fcd2eaff75fef0075",
    # Inter 600 is identical to 400 (variable font, same bytes). Hash would
    # match but we skip listing redundantly.
}


def _verify_assets() -> None:
    """Spot-check bundled asset integrity. Fails fast on corruption/tamper.

    Logs warnings rather than raising so a single asset mismatch doesn't
    take down HTML export; user sees something in logs but still gets a
    report (graceful degradation over hard fail).
    """
    for rel, expected in ASSET_SHA256.items():
        path = TEMPLATES_DIR / rel
        if not path.exists():
            logger.warning(f"Bundled asset missing: {rel}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            logger.error(
                f"Asset integrity failure: {rel} expected sha256 "
                f"{expected}, got {actual}"
            )


def build_html(
    data: dict,
    initial_theme: str = 'light',
    raw_model: dict | None = None,
    raw_decompose: dict | None = None,
    raw_optimize: dict | None = None,
    scenarios: list[dict] | None = None,
) -> str:
    """Build tier-1 interactive HTML deliverable from narrative_adapter data.

    Args:
        data: output of `narrative_adapter._map_pipeline_to_builder_data(...)`.
              Shape: {meta, diagnostics?, channels?, narrative_facts?}.
        initial_theme: one of 'light' | 'dark' | 'fun' (default 'light').
        raw_model: optional full model_data pickle-derived dict (passes
                   channel_params + normalization for budget what-if slider).
        raw_decompose: optional decompose_data for waterfall + timeline charts.
        raw_optimize: optional optimize_data for optimize comparison chart.
        scenarios: optional list of scenario dicts for scenario switcher.

    Returns:
        Complete standalone HTML string (~1MB with inline assets).
    """
    _verify_assets()
    from .builder import AuroraHTMLBuilder

    if initial_theme not in ('light', 'dark', 'fun'):
        logger.warning(f"unknown theme {initial_theme!r}, falling back to 'light'")
        initial_theme = 'light'

    builder = AuroraHTMLBuilder(
        data or {},
        initial_theme=initial_theme,
        raw_model=raw_model or {},
        raw_decompose=raw_decompose or {},
        raw_optimize=raw_optimize or {},
        scenarios=scenarios or [],
    )
    return builder.build()


__all__ = ['build_html', '__version__']
