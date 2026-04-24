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

    def __init__(
        self,
        data: dict,
        initial_theme: str = 'light',
        raw_model: dict | None = None,
        raw_decompose: dict | None = None,
        raw_optimize: dict | None = None,
        scenarios: list[dict] | None = None,
    ):
        self.data = data or {}
        self.meta = self.data.get('meta', {}) or {}
        self.diagnostics = self.data.get('diagnostics', {}) or {}
        self.channels = self.data.get('channels') or []
        self.facts = self.data.get('narrative_facts') or {}
        self.initial_theme = themes_mod.resolve_initial_theme(initial_theme)
        self.raw_model = raw_model or {}
        self.raw_decompose = raw_decompose or {}
        self.raw_optimize = raw_optimize or {}
        self.scenarios = scenarios or []

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
        """Full ECharts data payload, safely embedded (ensure_ascii=True).

        All 5 charts get their data here so JS can initialize without any
        further Python interaction. Each chart block is optional — JS checks
        presence before initializing.
        """
        channels_sorted_m = sorted(
            self.channels,
            key=lambda c: float(c.get("mroas") or 0),
            reverse=True,
        )

        # ─── Waterfall (decomposition) ─────────────────────────────────
        waterfall = self.raw_decompose.get("waterfall") or {}
        if isinstance(waterfall, dict):
            wf_labels = waterfall.get("labels") or []
            wf_values = waterfall.get("values") or []
        else:
            wf_labels = [str(w.get("category", "")) for w in waterfall]
            wf_values = [float(w.get("value", 0) or 0) for w in waterfall]

        # ─── Timeline stacked area ─────────────────────────────────────
        ts = self.raw_decompose.get("time_series") or {}
        ts_weeks = ts.get("dates") or ts.get("weeks") or []
        ts_baseline = ts.get("baseline") or []
        ts_channels = ts.get("channels") or {}

        # ─── Optimize comparison ───────────────────────────────────────
        opt_chs = self.raw_optimize.get("channels") or []
        opt_names = [c.get("name", "") for c in opt_chs]
        opt_current = [float(c.get("current_spend", 0) or 0) / 1_000_000.0 for c in opt_chs]
        opt_optimal = [float(c.get("optimal_spend", 0) or 0) / 1_000_000.0 for c in opt_chs]

        # ─── Scenarios (for switcher dropdown) ─────────────────────────
        scenarios_payload = []
        for sc in self.scenarios:
            totals = sc.get("totals") or {}
            scenarios_payload.append({
                "name":   sc.get("scenario_name") or sc.get("name") or "Сценарий",
                "lift":   float(totals.get("lift_pct") or 0),
                "roas":   float(totals.get("roas_money") or totals.get("roas") or 0),
                "budget": float(totals.get("total_spend_money") or totals.get("total_spend") or 0),
                "kpi":    float(totals.get("predicted_kpi") or 0),
            })

        payload = {
            "waterfall": {
                "labels": wf_labels,
                "values": [float(v) for v in wf_values],
            },
            "mroas": {
                "names":  [c.get("name") for c in channels_sorted_m],
                "values": [float(c.get("mroas") or 0) for c in channels_sorted_m],
                "hero":   channels_sorted_m[0].get("name") if channels_sorted_m else None,
                # Drill-down details per channel (for side-panel)
                "details": {
                    c.get("name"): {
                        "spend_mln":    round(float(c.get("spend") or 0) / 1e6, 2),
                        "contrib_mln":  round(float(c.get("contribution") or 0) / 1e6, 2),
                        "mroas":        float(c.get("mroas") or 0),
                        "verdict":      c.get("verdict") or "Watch",
                        "current_spend_mln": round(float(c.get("current_spend") or 0) / 1e6, 2),
                        "optimal_spend_mln": round(float(c.get("optimal_spend") or 0) / 1e6, 2),
                    }
                    for c in self.channels if c.get("name")
                },
            },
            "share": {
                "names":      [c.get("name") for c in self.channels],
                "spend_pct":  self._spend_pct_series(),
                "effect_pct": self._effect_pct_series(),
            },
            "timeline": {
                "weeks":    ts_weeks,
                "baseline": [float(v) for v in ts_baseline],
                "channels": {
                    name: [float(v) for v in series]
                    for name, series in ts_channels.items()
                },
                "channel_order": [c.get("name") for c in self.channels],
            },
            "optimize": {
                "names":   opt_names,
                "current": opt_current,
                "optimal": opt_optimal,
            },
            "scenarios": scenarios_payload,
        }
        return security.escape_js_embed(payload)

    def _spend_pct_series(self) -> list[float]:
        total = sum(float(c.get("spend") or 0) for c in self.channels) or 1.0
        return [round(float(c.get("spend") or 0) / total * 100, 1) for c in self.channels]

    def _effect_pct_series(self) -> list[float]:
        total = sum(float(c.get("contribution") or 0) for c in self.channels) or 1.0
        return [round(float(c.get("contribution") or 0) / total * 100, 1) for c in self.channels]

    def _model_context_json(self) -> str:
        """Model params for budget what-if slider.

        Structure:
          {
            channel_params: { "TV": {beta, alpha, gamma, adstock}, ... },
            normalization: { y_mean, y_std, media_means: {"TV": ...} },
            baseline_sum: float (сумма baseline за период для denormalization),
            current_spends_mln: { "TV": 120, ... },  # для reset button
            media_stds: { "TV": ... },  # для нормализации spend
          }

        If raw_model is absent, emits empty object and JS hides what-if UI.
        """
        channel_params = self.raw_model.get("channel_params", {}) or {}
        norm = self.raw_model.get("normalization", {}) or {}

        # Extract media_means and media_stds per channel (scalar per channel)
        media_means = norm.get("media_means") or {}
        media_stds = norm.get("media_stds") or {}

        # Baseline sum: from waterfall "Base" or time_series baseline
        baseline_sum = 0.0
        wf = self.raw_decompose.get("waterfall") or {}
        if isinstance(wf, dict):
            labels = wf.get("labels") or []
            values = wf.get("values") or []
            for lbl, v in zip(labels, values):
                if str(lbl).lower() in ("base", "baseline", "base sales", "base_sales"):
                    try:
                        baseline_sum = float(v)
                        break
                    except (TypeError, ValueError):
                        pass
        if baseline_sum == 0.0:
            ts_base = self.raw_decompose.get("time_series", {}).get("baseline") or []
            try:
                baseline_sum = float(sum(ts_base))
            except (TypeError, ValueError):
                baseline_sum = 0.0

        current_spends = {
            c.get("name"): round(float(c.get("spend") or 0) / 1e6, 2)
            for c in self.channels if c.get("name")
        }

        payload = {
            "channel_params":    channel_params,
            "normalization": {
                "y_mean":      float(norm.get("y_mean", 0) or 0),
                "y_std":       float(norm.get("y_std", 1) or 1),
                "media_means": media_means,
                "media_stds":  media_stds,
            },
            "baseline_sum":       float(baseline_sum),
            "current_spends_mln": current_spends,
            "enabled": bool(channel_params and media_means and norm.get("y_std")),
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
