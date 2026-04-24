"""
aurora_html.builder — AuroraHTMLBuilder orchestrator.

Assembles the 14-section HTML report by composing:
- outer shell.html (string.Template)
- inline assets (CSS, tokens JS, ECharts, WOFF2 fonts as data URIs, SVG favicon)
- section renderers (sections.py, 14 functions)
- interactivity JS (interactive.py - stubs in M2, full in M3)
- hash-based CSP (security.py)
- trust signals (report ID, methodology badge)

M2 scope: full narrative + static layout + CSP + fonts + ECharts bundled.
M3 adds interactive bootstrap JS.
M4 polish.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Any

from . import TEMPLATES_DIR
from . import themes as themes_mod
from . import security
from .sections import SECTION_RENDERERS
from .interactive import bootstrap_js

logger = logging.getLogger('econometrica.aurora_html')

# Month names for Russian date formatting
_RU_MONTHS = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _fmt_ru_date(dt: datetime) -> str:
    return f"{dt.day} {_RU_MONTHS[dt.month]} {dt.year}"


def _fmt_human_time(dt: datetime) -> str:
    """Human-friendly timestamp for footer."""
    return dt.strftime("%d.%m.%Y %H:%M")


# SVG favicon: Aurora wordmark dot + sacred lime accent
_FAVICON_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="6" fill="#0A1628"/>
<circle cx="16" cy="16" r="6" fill="#CCFF00"/>
<path d="M16 20l-2.5 4h5z" fill="#C5A46D"/>
</svg>"""


def _svg_to_data_uri(svg: str) -> str:
    """Convert SVG string to base64 data URI."""
    b64 = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    return f"data:image/svg+xml;base64,{b64}"


def _woff2_to_data_uri(path: Path) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode('ascii')
    return f"data:font/woff2;base64,{b64}"


class AuroraHTMLBuilder:
    """Build tier-1 Aurora AI interactive HTML report."""

    def __init__(self, data: dict, initial_theme: str = 'light'):
        self.data = data or {}
        self.meta = self.data.get('meta', {}) or {}
        self.diagnostics = self.data.get('diagnostics', {}) or {}
        self.channels = self.data.get('channels') or []
        self.facts = self.data.get('narrative_facts') or {}
        self.initial_theme = themes_mod.resolve_initial_theme(initial_theme)

        self.client = self.meta.get('client') or 'Client'
        self.project_id = self.meta.get('project_id') or 'PROJECT'
        self.version = self.meta.get('version') or '1.0.12'
        self.report_date = self.meta.get('report_date') or _fmt_ru_date(datetime.now())
        self.generated_dt = datetime.now()
        self.generated_iso = self.generated_dt.isoformat(timespec='seconds')
        self.generated_human = _fmt_human_time(self.generated_dt)

        self.report_id = self._compute_report_id()
        self.strings = self._load_strings()

    def _load_strings(self) -> dict:
        strings_path = Path(__file__).parent / "strings_ru.json"
        return json.loads(strings_path.read_text(encoding='utf-8'))

    def _compute_report_id(self) -> str:
        """Client-facing traceability hash."""
        fp_input = (
            f"{self.client}|{self.project_id}|{self.version}|"
            f"n_channels={len(self.channels)}|"
            f"diag={sorted(self.diagnostics.items())}|"
            f"ts={self.generated_iso}"
        )
        h = hashlib.sha256(fp_input.encode('utf-8')).hexdigest()[:12]
        return f"aurora-mmm-{h}"

    # ─── Inline assets ────────────────────────────────────────────────────

    def _fonts_css(self) -> str:
        """@font-face rules with WOFF2 data URIs."""
        fonts_dir = TEMPLATES_DIR / "fonts"
        rules = []
        for family, file_map in [
            ("Lora", {
                "400": ("lora-400-latin.woff2", "lora-400-cyrillic.woff2"),
            }),
            ("Inter", {
                "400": ("inter-400-latin.woff2", "inter-400-cyrillic.woff2"),
                "600": ("inter-600-latin.woff2", "inter-600-cyrillic.woff2"),
            }),
        ]:
            for weight, (latin_f, cyr_f) in file_map.items():
                latin_path = fonts_dir / latin_f
                cyr_path = fonts_dir / cyr_f
                if latin_path.exists():
                    rules.append(
                        f"@font-face {{\n"
                        f"  font-family: '{family}';\n"
                        f"  font-weight: {weight};\n"
                        f"  font-style: normal;\n"
                        f"  font-display: swap;\n"
                        f"  src: url({_woff2_to_data_uri(latin_path)}) format('woff2');\n"
                        f"  unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+2000-206F, U+20AC;\n"
                        f"}}"
                    )
                if cyr_path.exists():
                    rules.append(
                        f"@font-face {{\n"
                        f"  font-family: '{family}';\n"
                        f"  font-weight: {weight};\n"
                        f"  font-style: normal;\n"
                        f"  font-display: swap;\n"
                        f"  src: url({_woff2_to_data_uri(cyr_path)}) format('woff2');\n"
                        f"  unicode-range: U+0301, U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116;\n"
                        f"}}"
                    )
        return "\n".join(rules)

    def _tokens_css(self) -> str:
        path = TEMPLATES_DIR / "aurora_html.css"
        return path.read_text(encoding='utf-8') if path.exists() else ""

    def _tokens_js(self) -> str:
        path = TEMPLATES_DIR / "aurora_html_tokens.js"
        return path.read_text(encoding='utf-8') if path.exists() else ""

    def _layout_css(self) -> str:
        path = TEMPLATES_DIR / "layout.css"
        return path.read_text(encoding='utf-8') if path.exists() else ""

    def _echarts_js(self) -> str:
        path = TEMPLATES_DIR / "echarts.common.5.5.1.min.js"
        return path.read_text(encoding='utf-8') if path.exists() else "/* ECharts not bundled */"

    def _bootstrap_js(self) -> str:
        """Consolidated JS: bootstrap + chart data + interactive bindings."""
        chart_data = self._chart_data_json()
        model_ctx = self._model_context_json()
        bootstrap = bootstrap_js(
            initial_theme=self.initial_theme,
            chart_data_json=chart_data,
            model_context_json=model_ctx,
            strings=self.strings,
        )
        return bootstrap

    def _chart_data_json(self) -> str:
        """ECharts data payload, safely embedded (ensure_ascii=True)."""
        # Full chart data preparation lives in M3 charts.py.
        # M2: minimal shape so chart containers don't throw on missing keys.
        channels_sorted_m = sorted(
            self.channels,
            key=lambda c: float(c.get("mroas") or 0),
            reverse=True,
        )
        payload = {
            "mroas": {
                "names":  [c.get("name") for c in channels_sorted_m],
                "values": [float(c.get("mroas") or 0) for c in channels_sorted_m],
                "hero":   channels_sorted_m[0].get("name") if channels_sorted_m else None,
            },
            "share": {
                "names": [c.get("name") for c in self.channels],
                "spend_pct":  self._spend_pct_series(),
                "effect_pct": self._effect_pct_series(),
            },
            "timeline": {
                # M3 will wire real time_series; M2 emits placeholder.
                "weeks":   [],
                "baseline": [],
                "channels": {},
            },
        }
        return security.escape_js_embed(payload)

    def _spend_pct_series(self) -> list[float]:
        total = sum(float(c.get("spend") or 0) for c in self.channels) or 1.0
        return [round(float(c.get("spend") or 0) / total * 100, 1) for c in self.channels]

    def _effect_pct_series(self) -> list[float]:
        total = sum(float(c.get("contribution") or 0) for c in self.channels) or 1.0
        return [round(float(c.get("contribution") or 0) / total * 100, 1) for c in self.channels]

    def _model_context_json(self) -> str:
        """Model params passed to JS for budget what-if slider (M3 feature)."""
        payload = {
            "channel_params": self.data.get("model_channel_params", {}),
            "normalization":  self.data.get("model_normalization", {}),
            "baseline":       self.data.get("decompose_baseline", 0),
        }
        return security.escape_js_embed(payload)

    # ─── TOC + shortcuts ──────────────────────────────────────────────────

    def _toc_items(self) -> str:
        """Build TOC <li> list from strings.sections."""
        items = []
        for sid, _ in SECTION_RENDERERS:
            label = self.strings["sections"].get(sid, {}).get("label", sid)
            items.append(f'      <li><a href="#{sid}" data-toc-target="{sid}">{security.escape(label)}</a></li>')
        return "\n".join(items)

    def _shortcuts_rows(self) -> str:
        """Shortcuts modal table."""
        items = self.strings["ui"]["shortcuts"]["items"]
        rows = []
        for item in items:
            rows.append(
                f'<tr><td><kbd>{security.escape(item["keys"])}</kbd></td>'
                f'<td>{security.escape(item["action"])}</td></tr>'
            )
        return "\n".join(rows)

    # ─── Main build ───────────────────────────────────────────────────────

    def build(self) -> str:
        """Assemble final HTML string."""
        # 1. Render sections
        ctx = {
            "meta":        self.meta,
            "diagnostics": self.diagnostics,
            "channels":    self.channels,
            "facts":       self.facts,
            "strings":     self.strings,
            "report_id":   self.report_id,
        }
        sections_html = "\n".join(render(ctx) for _, render in SECTION_RENDERERS)

        # 2. Concatenate inline assets
        fonts_css = self._fonts_css()
        tokens_css = self._tokens_css()
        layout_css = self._layout_css()
        tokens_js = self._tokens_js()
        echarts_js = self._echarts_js()
        bootstrap = self._bootstrap_js()

        # 3. CSP hashes (must match exact bytes of inline <style> and <script>)
        #    We compute hashes of the CONCATENATED styles and CONCATENATED scripts
        #    but CSP v3 supports multiple hashes, so we hash each block separately.
        #    Shell has 3 style blocks (fonts/tokens/layout) and 3 script blocks.
        style_hashes = [
            security.csp_sha256(s) for s in (fonts_css, tokens_css, layout_css)
        ]
        script_hashes = [
            security.csp_sha256(s) for s in (echarts_js, tokens_js, bootstrap)
        ]
        csp_meta = self._build_csp_meta(style_hashes, script_hashes)

        # 4. Shell template substitution
        shell_tpl = Template((TEMPLATES_DIR / "shell.html").read_text(encoding='utf-8'))

        theme_icons = {'light': '☼', 'dark': '☾', 'fun': '✦'}
        ui = self.strings["ui"]

        doc_title = f"Aurora AI · MMM-отчёт · {self.client}"
        doc_description = f"Marketing Mix Modeling отчёт от Aurora AI. Report ID: {self.report_id}"

        html = shell_tpl.safe_substitute(
            initial_theme=self.initial_theme,
            doc_title=doc_title,
            doc_description=doc_description,
            version=self.version,
            favicon_data_uri=_svg_to_data_uri(_FAVICON_SVG),
            csp_meta=csp_meta,
            fonts_css=fonts_css,
            tokens_css=tokens_css,
            layout_css=layout_css,
            echarts_js=echarts_js,
            tokens_js=tokens_js,
            bootstrap_js=bootstrap,
            brand_wordmark=security.escape(self.strings["brand"]["wordmark"]),
            confidentiality_label=security.escape(self.strings["brand"]["confidentiality"]),
            client_suffix=security.escape(f" · {self.client}"),
            toc_toggle_label=security.escape(ui["toc"]["toggle_open"]),
            search_label=security.escape(ui["search"]["placeholder"]),
            theme_label=security.escape(ui["theme"]["label"]),
            theme_icon=theme_icons.get(self.initial_theme, '☼'),
            copy_link_label=security.escape(ui["buttons"]["copy_link"]),
            shortcuts_label=security.escape(ui["buttons"]["show_shortcuts"]),
            toc_title=security.escape(ui["toc"]["title"]),
            toc_items=self._toc_items(),
            sections=sections_html,
            report_id=security.escape(self.report_id),
            report_id_label=security.escape(ui["footer"]["report_id_label"]),
            generated_label=security.escape(ui["footer"]["generated_label"]),
            generated_iso=security.escape(self.generated_iso),
            generated_human=security.escape(self.generated_human),
            copyright_line=security.escape(
                self.strings["brand"]["copyright_template"].format(
                    year=self.generated_dt.year)
            ),
            shortcuts_title=security.escape(ui["shortcuts"]["title"]),
            shortcuts_rows=self._shortcuts_rows(),
            search_placeholder=security.escape(ui["search"]["placeholder"]),
            close_label=security.escape(ui["buttons"]["close"]),
        )
        return html

    def _build_csp_meta(self, style_hashes: list[str], script_hashes: list[str]) -> str:
        """Emit CSP meta using all inline hashes (no unsafe-inline)."""
        style_src = " ".join(style_hashes)
        script_src = " ".join(script_hashes)
        policy = "; ".join([
            "default-src 'none'",
            "img-src 'self' data: blob:",
            "font-src data:",
            f"style-src {style_src}",
            f"script-src {script_src}",
            "connect-src 'none'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        ])
        return f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
