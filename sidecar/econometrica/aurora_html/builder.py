"""
aurora_html.builder - AuroraHTMLBuilder orchestrator.

Assembles the 14-section interactive HTML report by composing:
- outer shell.html (string.Template)
- inline assets (CSS, tokens JS, ECharts, WOFF2 fonts as data URIs, SVG favicon)
- section renderers (sections.py, 14 functions)
- interactive bootstrap JS (interactive.py)
- hash-based CSP per inline block (security.py)
- trust signals: Report ID SHA-256, methodology badge, confidentiality watermark
"""
from __future__ import annotations

import base64
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
try:
    from econometrica.engines.narrative_adapter import compute_report_id, _normalize_channel_name
except ImportError:
    from engines.narrative_adapter import compute_report_id, _normalize_channel_name

logger = logging.getLogger('econometrica.aurora_html')

# Month names for Russian date formatting
_RU_MONTHS = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _fmt_ru_date(dt: datetime) -> str:
    return f"{dt.day} {_RU_MONTHS[dt.month]} {dt.year}"


# Cached extraction of the static <noscript><style>...</style></noscript> block
# from shell.html. Computed once per process, hashed into CSP style-src so the
# noscript fallback styles render under strict CSP even when JS is enabled
# (Chrome parses and enforces CSP on noscript CSS regardless of JS state).
_NOSCRIPT_STYLE_CACHE: str | None = None


def _extract_noscript_style() -> str:
    """Extract the content of <noscript><style>...</style></noscript> from
    shell.html so its SHA-256 can be added to CSP style-src. Cached: the
    noscript block is static (no template variables), safe to memoize.
    """
    global _NOSCRIPT_STYLE_CACHE
    if _NOSCRIPT_STYLE_CACHE is not None:
        return _NOSCRIPT_STYLE_CACHE
    shell = (TEMPLATES_DIR / "shell.html").read_text(encoding='utf-8')
    # Match the first <style> ... </style> *inside* <noscript>. Non-greedy.
    m = re.search(r'<noscript>\s*<style>(.*?)</style>', shell, re.DOTALL)
    if not m:
        raise RuntimeError(
            "shell.html: <noscript><style>...</style></noscript> block not "
            "found; cannot compute CSP hash."
        )
    _NOSCRIPT_STYLE_CACHE = m.group(1)
    return _NOSCRIPT_STYLE_CACHE


def _fmt_human_time(dt: datetime) -> str:
    """Human-friendly timestamp for footer."""
    return dt.strftime("%d.%m.%Y %H:%M")


# SVG favicon: Aurora sigil - navy square + sacred lime dot + gold arc.
# Renders crisp at any size (16/32/180/512px). High recognisability in browser tab.
_FAVICON_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="7" fill="#0A1628"/>
<circle cx="16" cy="15" r="5.2" fill="none" stroke="#C5A46D" stroke-width="1.4" stroke-dasharray="18 12" stroke-linecap="round" transform="rotate(-30 16 15)"/>
<circle cx="16" cy="15" r="3" fill="#CCFF00"/>
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

        # Post-audit (2026-04-25): delegate to shared compute_report_id
        # so HTML and PPTX produce identical IDs for same pipeline output.
        # Product version removed from hash - Report ID identifies the
        # *report content*, not the software build that produced it.
        self.report_id = compute_report_id(
            self.client, self.project_id, self.channels, self.diagnostics,
        )
        self.strings = self._load_strings()

    def _load_strings(self) -> dict:
        strings_path = Path(__file__).parent / "strings_ru.json"
        return json.loads(strings_path.read_text(encoding='utf-8'))

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

    def _brand_mark_svg(self) -> str:
        """Aurora deliverable gold-accent SVG для cover hero.

        2026-05-04 - добавлен по запросу Антона. Inline SVG (не data URI) -
        позволяет CSS темам стилизовать через currentColor если когда-то понадобится,
        и сохраняет accessibility (можно поставить aria-label на <svg>). XML
        declaration вырезается т.к. inline в HTML body запрещён.
        """
        path = TEMPLATES_DIR / "brand_mark.svg"
        if not path.exists():
            return ""
        svg = path.read_text(encoding='utf-8')
        # Strip XML declaration + Adobe generator comment для cleaner inline.
        if svg.startswith('<?xml'):
            end = svg.find('?>')
            if end != -1:
                svg = svg[end + 2:].lstrip()
        if svg.startswith('<!--'):
            end = svg.find('-->')
            if end != -1:
                svg = svg[end + 3:].lstrip()
        return svg

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
        further Python interaction. Each chart block is optional - JS checks
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
        # Normalize channel keys to match self.channels names (which went
        # through _normalize_channel_name). Without this, JS lookup
        # data.channels[channel_order[i]] returns undefined → only Baseline
        # renders. PPTX/XLSX use raw decompose data, so they're unaffected.
        raw_channels = ts.get("channels") or {}
        ts_channels: dict[str, list] = {}
        for raw_name, series in raw_channels.items():
            norm = _normalize_channel_name(raw_name) or raw_name
            ts_channels[norm] = series

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
        media_means = dict(norm.get("media_means") or {})
        media_stds = dict(norm.get("media_stds") or {})

        # v2.1.0 (пилот 2026-05-17): backfill из channel_params.adstock_mean_posterior
        # (Bayesian pickles). Это тот же mean что используется decomposer'ом для
        # spend/mean Hill normalization. Без этого backfill what-if KPI = 0%
        # для pickles без top-level media_means dict.
        for ch_name, ch_p in channel_params.items():
            if ch_name in media_means and media_means[ch_name]:
                continue
            mean_post = (ch_p or {}).get("adstock_mean_posterior")
            if isinstance(mean_post, (int, float)) and mean_post > 0:
                media_means[ch_name] = float(mean_post)

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

        # v2.1.0 (пилот 2026-05-17): enabled gate. Bug: media_means dict отсутствовал /
        # пустой в некоторых pickle вариантах → enabled=False → what-if UI скрывался
        # ИЛИ показывался но KPI всегда 0%. Fallback: channel_params[ch].mean per-channel.
        per_ch_means_ok = any(
            isinstance((p or {}).get("mean"), (int, float)) and (p or {}).get("mean") and (p or {}).get("mean") > 0
            for p in channel_params.values()
        )
        means_available = bool(media_means) or per_ch_means_ok

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
            "enabled": bool(channel_params and means_available and norm.get("y_std")),
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
        # v2.1.0 (Pilot C): model_version forwarded к sections для engine detection.
        # OLS-режим (model_version='1.0-ols' или diagnostics.engine='ols')
        # переключает методологический копи: closed-form/bootstrap вместо MCMC/NUTS.
        model_version = (
            self.raw_model.get('model_version')
            or self.raw_decompose.get('model_version')
            or self.data.get('model_version')
        )
        # 1. Render sections
        ctx = {
            "meta":        self.meta,
            "diagnostics": self.diagnostics,
            "channels":    self.channels,
            "facts":       self.facts,
            "strings":     self.strings,
            "report_id":   self.report_id,
            "model_version": model_version,
            "brand_mark_svg": self._brand_mark_svg(),
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
        #    Shell wraps each substitution with newlines:
        #        <style>\n${fonts_css}\n</style>
        #    The browser computes sha256 over EVERYTHING between the tags
        #    (including those wrapper newlines), so we must hash the wrapped
        #    form, not the raw substitution value. Static noscript block is
        #    also read from shell.html exactly as written (incl. indentation).
        noscript_css = _extract_noscript_style()
        style_blocks_as_emitted = (
            f"\n{fonts_css}\n",
            f"\n{tokens_css}\n",
            f"\n{layout_css}\n",
            noscript_css,  # already includes its own leading/trailing whitespace
        )
        script_blocks_as_emitted = (
            f"\n{echarts_js}\n",
            f"\n{tokens_js}\n",
            f"\n{bootstrap}\n",
        )
        style_hashes = [security.csp_sha256(s) for s in style_blocks_as_emitted]
        script_hashes = [security.csp_sha256(s) for s in script_blocks_as_emitted]
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
        """Emit CSP meta using all inline hashes.

        `style-src` stays hash-based (no 'unsafe-inline') - strict XSS defense
        over <style> blocks. `style-src-attr 'unsafe-inline'` explicitly
        permits inline style="..." attributes (used for dynamic data-driven
        widths, colors, etc. in sections.py that can't be static classes).
        CSP3 separates these directives; modern browsers (Chrome 77+, FF 86+,
        Safari 16+) honour the split. All user-controlled strings embedded
        into style attrs are escape()'d via security.escape, so XSS surface
        for inline attrs is closed upstream.
        """
        style_src = " ".join(style_hashes)
        script_src = " ".join(script_hashes)
        policy = "; ".join([
            "default-src 'none'",
            "img-src 'self' data: blob:",
            "font-src data:",
            f"style-src {style_src}",
            "style-src-attr 'unsafe-inline'",
            f"script-src {script_src}",
            "connect-src 'none'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        ])
        return f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
