"""
aurora_pptx.builder — production PPTX builder (13-slide tier-1 MMM report).

Ported from build_wireframe.py (finalized 2026-04-24 after iterative review with Антон).
Uses aurora_tokens (generated from Standards/tokens/tokens.json) for brand consistency.

Session 3 scope: initial port with default Kagocel data (pilot).
Session 4 (M4): параметризовать через data dict from Econometrica pipeline.

Public API:
    from econometrica.aurora_pptx.builder import AuroraPPTXBuilder
    builder = AuroraPPTXBuilder()
    prs = builder.build()
    prs.save(output_path)

Or via convenience function:
    from econometrica.aurora_pptx import build_pptx
    prs = build_pptx(data, lang='ru')

Brand principles applied (per Standards/CLIENT_READY_ANATOMY.md):
  - One gold accent per slide (strict discipline)
  - Running header + minimal footer (no duplication)
  - Sacred lime #CCFF00 under action titles
  - Pull quotes in Georgia italic
  - SCQAR structure в executive summary
  - Methodology includes explicit limitations
  - Closing slide inspirational, not technical
  - No em dash anywhere (Aurora rule)
  - Safe zones: top 0.25", bottom 0.20" (footer hairline 7.05)
  - Sources left-bottom quadrant, prижаты to footer hairline
  - Line_spacing=1.0 for headings
"""

from __future__ import annotations

import math
import zlib
from datetime import datetime

try:
    from econometrica.engines.narrative_adapter import (
        compute_report_id,
        derive_action_headline,
    )
except ImportError:
    from engines.narrative_adapter import (
        compute_report_id,
        derive_action_headline,
    )

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

try:
    from aurora_tokens import COLORS, TYPOGRAPHY, SIZING
except ImportError as e:
    raise RuntimeError(
        "aurora_tokens not generated. Run: python Standards/tokens/build.py --target python"
    ) from e


def hex_to_rgb(h):
    return RGBColor.from_string(h.lstrip("#").upper())


def _fmt_pct(v, fallback="-"):
    """N1 (Phase 0.1 fix-session 2026-04-25): conditional precision — never lies via rounding to 0%.
    Mirrors aurora_html/sections.py:_fmt_pct. See that file for behavior table.
    """
    if v is None:
        return fallback
    try:
        f = float(v)
    except (TypeError, ValueError):
        return fallback
    if f == 0:
        return "0%"
    av = abs(f)
    if av < 0.1:
        return "<0.1%" if f > 0 else ">-0.1%"
    if av < 1.0:
        return f"{f:.1f}%"
    return f"{round(f)}%"


class AuroraPPTXBuilder:
    """Production PPTX builder for Aurora AI Econometrica MMM reports.

    Currently uses default pilot data (Kagocel). Session 4 will parametrize
    via data dict passed from Econometrica pipeline.
    """

    def __init__(self, data=None, lang="ru"):
        if lang != "ru":
            raise NotImplementedError(
                f"lang={lang!r} not yet supported. RU-only pilot; EN scheduled for v1.0.12."
            )
        self.data = data or {}
        self.lang = lang
        # Tokens now come from generated aurora_tokens module (not JSON load)
        self.t = {"color": COLORS, "typography": TYPOGRAPHY, "sizing": SIZING}
        self.prs = Presentation()
        self.prs.slide_width = Inches(13.333)
        self.prs.slide_height = Inches(7.5)

        c = self.t["color"]
        self.deep_100 = hex_to_rgb(c["brand"]["deep"]["100"])
        self.deep_80 = hex_to_rgb(c["brand"]["deep"]["80"])
        self.deep_60 = hex_to_rgb(c["brand"]["deep"]["60"])
        self.deep_40 = hex_to_rgb(c["brand"]["deep"]["40"])
        self.deep_20 = hex_to_rgb(c["brand"]["deep"]["20"])
        self.gold = hex_to_rgb(c["brand"]["gold"]["primary"])
        self.gold_muted = hex_to_rgb(c["brand"]["gold"]["muted"])
        self.rule_color = hex_to_rgb(c["brand"]["rule"])
        self.lime = hex_to_rgb(c["brand"]["sig"]["lime"])
        self.white = hex_to_rgb(c["brand"]["bg"]["white"])
        self.bg_quiet = hex_to_rgb(c["brand"]["bg"]["quiet"])

        ty = self.t["typography"]
        self.serif = ty["fontFamily"]["serif"]
        self.sans = ty["fontFamily"]["sans"]
        self.mono = ty["fontFamily"]["mono"]

        self.safe = 0.4
        self.w = 13.333
        self.h = 7.5

        # --- Meta (Session 4 M4: parametrized via data.meta, fallback = Kagocel pilot) ---
        meta = self.data.get("meta") or {}
        self.client = meta.get("client", "Kagocel")
        self.project_id = meta.get("project_id", "KAGOCEL-Q1-2026")
        self.version = meta.get("version", "1.0.11")
        self.report_date = meta.get("report_date", "24 апреля 2026")
        self.period_label = meta.get("period_label", "Q1 2026")
        self.forecast_period_label = meta.get("forecast_period_label", "Q3-Q4 2026")
        self.data_window_label = meta.get("data_window_label", "W01 W13 2026")
        # Stage C.6.3: TOC shrunk to 5 real sections with content (Option B
        # symmetric tier-1 structure). Previous 8-section layout promised
        # sections 4/6/7 (Модель / Оптимизация / Рекомендации) with no
        # dedicated slides; now each section-divider slide precedes real
        # content. Header "01 / 05" honest across the deck.
        self.section_names = meta.get("section_names", [
            "Executive summary",        # 1: TOC + ataglance + keymsg + SCQAR
            "Декомпозиция вкладов",     # 2: divider + chart + table + timeline
            "Методология",              # 3: divider + methodology
            "Данные и качество",        # 4: divider + sources
            "Приложение и источники",   # 5: divider + glossary + colophon
        ])
        self.total_sections = len(self.section_names)
        self.total_slides = meta.get("total_slides", 16)
        # Physical page where each section begins (first content slide).
        self.toc_page_refs = meta.get("toc_page_refs", [3, 6, 10, 12, 14])
        # Stage C.6.2/C.6.3: physical-slide → (section_idx, section_label) map.
        # 16-slide expanded layout: 3 new section dividers (s_div_meth @ 10,
        # s_div_data @ 12, s_div_appendix @ 14) provide visual anchoring
        # symmetric to the existing Декомпозиция divider at page 4.
        self.slide_to_section = meta.get("slide_to_section") or {
            2:  (1, "Executive summary"),          # TOC
            3:  (1, "Executive summary"),          # At a glance
            4:  (1, "Executive summary"),          # Key message
            5:  (1, "Executive summary"),          # SCQAR
            6:  (2, "Декомпозиция вкладов"),       # Section divider
            7:  (2, "Декомпозиция вкладов"),       # Action chart (mROAS)
            8:  (2, "Декомпозиция вкладов"),       # Action table (portfolio)
            9:  (2, "Декомпозиция вкладов"),       # Action timeline
            10: (3, "Методология"),                # Methodology divider
            11: (3, "Методология"),                # Methodology content
            12: (4, "Данные и качество"),          # Data divider
            13: (4, "Данные и качество"),          # Sources content
            14: (5, "Приложение и источники"),     # Appendix divider
            15: (5, "Приложение и источники"),     # Glossary
            16: (5, "Приложение и источники"),     # Colophon
        }
        # Header center label (shown on every content slide)
        self.header_project_label = meta.get(
            "header_project_label",
            f"{self.client.upper()} . MMM REPORT . {self.period_label}",
        )
        # Copyright footer on cover — dynamic year for future-proofing
        _year = datetime.now().year
        self.copyright_line = meta.get(
            "copyright_line",
            f"© {_year} Aurora AI. Конфиденциально",
        )
        # Source-note label template (client name substituted)
        self.sources_client_label = meta.get("sources_client_label", self.client)

        # --- Diagnostics (Phase 2 numbers — parametrized metric callouts) ---
        diag = self.data.get("diagnostics") or {}
        self.mqs_score = diag.get("mqs_score", 87)
        self.mqs_tier_label = diag.get("mqs_tier_label", "GOOD - готовность к production")
        self.r_squared = diag.get("r_squared", 0.872)
        self.mape_pct = diag.get("mape_pct", 8.3)
        self.r_hat_max = diag.get("r_hat_max", 1.008)
        self.ess_min = diag.get("ess_min", 1247)

        # --- Channels + narrative facts (Session C — Path C parametrization) ---
        # If adapter supplied channels + facts: real client data drives slide
        # templates. Otherwise builder keeps its Kagocel pilot narrative
        # (wireframe / preview mode) — single source-of-truth guard lives
        # with `self.facts is None` checks in each slide method.
        self.channels = self.data.get("channels") or []
        self.facts = self.data.get("narrative_facts")
        self.time_series = self.data.get("time_series") or None

        # --- Report ID (Stage B.4, post-audit unified 2026-04-25) ---
        # Deterministic trace hash shared with aurora_html. Uses the raw
        # diagnostics dict from data (NOT the Kagocel fallback attrs like
        # self.mqs_score=87), so partial-data runs don't leak pilot values
        # into the hash. Same pipeline output → same ID in HTML and PPTX.
        raw_diagnostics = self.data.get("diagnostics") or {}
        self.report_id = self.data.get("report_id") or compute_report_id(
            self.client, self.project_id, self.channels, raw_diagnostics,
        )

    # ---------- Primitives ----------

    def _blank(self):
        return self.prs.slides.add_slide(self.prs.slide_layouts[6])

    def _text(self, slide, x, y, w, h, text, *,
              font=None, size=12, bold=False, italic=False,
              color=None, align=None, line_spacing=None):
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0); tf.margin_right = Inches(0)
        tf.margin_top = Inches(0); tf.margin_bottom = Inches(0)
        p = tf.paragraphs[0]
        if align is not None:
            p.alignment = align
        if line_spacing is not None:
            p.line_spacing = line_spacing
        r = p.add_run()
        r.text = text
        f = r.font
        f.name = font or self.sans
        f.size = Pt(size)
        f.bold = bold
        f.italic = italic
        if color:
            f.color.rgb = color
        return tb

    def _rich(self, slide, x, y, w, h, runs, *, line_spacing=1.3, align=None):
        """Multi-run paragraph. runs = list of (text, opts_dict)."""
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0); tf.margin_right = Inches(0)
        tf.margin_top = Inches(0); tf.margin_bottom = Inches(0)
        p = tf.paragraphs[0]
        p.line_spacing = line_spacing
        if align is not None:
            p.alignment = align
        for text, opts in runs:
            r = p.add_run()
            r.text = text
            f = r.font
            f.name = opts.get("font", self.sans)
            f.size = Pt(opts.get("size", 12))
            f.bold = opts.get("bold", False)
            f.italic = opts.get("italic", False)
            f.color.rgb = opts.get("color", self.deep_100)
        return tb

    def _paragraphs(self, slide, x, y, w, h, lines, *, line_spacing=1.35):
        """Paragraph list. lines = list of (text, opts)."""
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0); tf.margin_right = Inches(0)
        tf.margin_top = Inches(0); tf.margin_bottom = Inches(0)
        for i, item in enumerate(lines):
            text, opts = item if isinstance(item, tuple) else (item, {})
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.line_spacing = opts.get("line_spacing", line_spacing)
            if "align" in opts:
                p.alignment = opts["align"]
            r = p.add_run()
            r.text = text
            f = r.font
            f.name = opts.get("font", self.sans)
            f.size = Pt(opts.get("size", 11))
            f.bold = opts.get("bold", False)
            f.italic = opts.get("italic", False)
            f.color.rgb = opts.get("color", self.deep_100)
        return tb

    def _hairline(self, slide, x, y, width, *, weight=0.5, color=None):
        line = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            Inches(x), Inches(y), Inches(x + width), Inches(y)
        )
        line.line.color.rgb = color or self.rule_color
        line.line.width = Pt(weight)
        return line

    def _vline(self, slide, x, y, height, *, weight=0.5, color=None):
        line = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            Inches(x), Inches(y), Inches(x), Inches(y + height)
        )
        line.line.color.rgb = color or self.rule_color
        line.line.width = Pt(weight)
        return line

    def _lime_under(self, slide, x, y, width):
        line = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            Inches(x), Inches(y), Inches(x + width), Inches(y)
        )
        line.line.color.rgb = self.lime
        line.line.width = Pt(2)

    def _vbar(self, slide, x, y, height, *, weight=2, color=None):
        line = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            Inches(x), Inches(y), Inches(x), Inches(y + height)
        )
        line.line.color.rgb = color or self.gold
        line.line.width = Pt(weight)

    def _rect(self, slide, x, y, w, h, *, fill=None, line=False):
        shape = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(x), Inches(y), Inches(w), Inches(h)
        )
        if fill is not None:
            shape.fill.solid()
            shape.fill.fore_color.rgb = fill
        else:
            shape.fill.background()
        if not line:
            shape.line.fill.background()
        return shape

    def _arrow(self, slide, x1, y1, x2, y2, *, weight=0.75, color=None):
        """Thin annotation arrow."""
        line = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            Inches(x1), Inches(y1), Inches(x2), Inches(y2)
        )
        line.line.color.rgb = color or self.deep_80
        line.line.width = Pt(weight)
        # Arrowhead on the end
        try:
            from pptx.oxml.ns import qn
            from lxml import etree
            ln = line.line._get_or_add_ln()
            tailEnd = etree.SubElement(ln, qn('a:tailEnd'))
            tailEnd.set('type', 'triangle')
            tailEnd.set('w', 'sm')
            tailEnd.set('len', 'sm')
        except Exception:
            pass
        return line

    # ---------- Wordmark (strict typographic logo) ----------

    def _wordmark(self, slide, x, y, *, size=12, color=None):
        """'AURORA | AI' as strict typographic lockup with gold divider."""
        col = color or self.deep_100
        # Scale factor - wordmark width grows with size
        scale = size / 12.0
        w_aurora = 0.95 * scale
        w_gap = 0.08 * scale
        w_ai = 0.28 * scale
        height = 0.22 * scale

        # AURORA in serif small caps
        tb = slide.shapes.add_textbox(
            Inches(x), Inches(y), Inches(w_aurora + 0.1), Inches(height)
        )
        tf = tb.text_frame
        tf.margin_left = Inches(0); tf.margin_right = Inches(0)
        tf.margin_top = Inches(0); tf.margin_bottom = Inches(0)
        tf.word_wrap = False
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = "AURORA"
        r.font.name = self.serif
        r.font.size = Pt(size)
        r.font.bold = False
        r.font.color.rgb = col

        # Gold vertical bar divider
        div_x = x + w_aurora + w_gap
        line = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            Inches(div_x), Inches(y + height * 0.15),
            Inches(div_x), Inches(y + height * 0.85)
        )
        line.line.color.rgb = self.gold
        line.line.width = Pt(max(0.75, size / 12))

        # AI in bold
        ai_x = div_x + w_gap
        tb2 = slide.shapes.add_textbox(
            Inches(ai_x), Inches(y), Inches(w_ai + 0.1), Inches(height)
        )
        tf2 = tb2.text_frame
        tf2.margin_left = Inches(0); tf2.margin_right = Inches(0)
        tf2.margin_top = Inches(0); tf2.margin_bottom = Inches(0)
        tf2.word_wrap = False
        p2 = tf2.paragraphs[0]
        r2 = p2.add_run()
        r2.text = "AI"
        r2.font.name = self.serif
        r2.font.size = Pt(size)
        r2.font.bold = True
        r2.font.color.rgb = col

    # ---------- Running header (top of content slides) ----------

    def _header(self, slide, *, slide_num=None, section_idx=None, section_label=None,
                include_confidential=True, include_project=False):
        """Slim running header: closer to top edge (y=0.25) to reclaim content space.

        Stage B.2: center "project identifier" textbox removed — it was
        leaking internal project slug + MMM REPORT + period into every
        slide (35 chars of visual noise). Tier-1 minimalism: left section
        label + right CONFIDENTIAL only. `include_project` kept as a
        parameter (default False) for explicit opt-in if ever needed.

        Stage C.6.2: prefer `slide_num` which resolves (section_idx,
        section_label) via self.slide_to_section. Explicit section_idx /
        section_label still accepted for backward compat and edge overrides.
        """
        if slide_num is not None and slide_num in self.slide_to_section:
            mapped_idx, mapped_label = self.slide_to_section[slide_num]
            if section_idx is None:
                section_idx = mapped_idx
            if section_label is None:
                section_label = mapped_label
        if section_idx is None or section_label is None:
            raise ValueError(
                "_header requires either slide_num (mapped in slide_to_section) "
                "or explicit section_idx + section_label"
            )
        y = 0.25  # compact safe_top zone
        # Left: section tag like "03 / 08 . Methodology"
        self._text(
            slide, self.safe, y, 5.0, 0.2,
            f"{section_idx:02d} / {self.total_sections:02d} . {section_label.upper()}",
            font=self.sans, size=8, bold=True, color=self.deep_100, align=PP_ALIGN.LEFT,
        )
        # Center: project identifier — DISABLED by default (Stage B.2)
        if include_project:
            self._text(
                slide, 4.5, y, 4.333, 0.2,
                self.header_project_label,
                font=self.sans, size=8, color=self.deep_60,
                align=PP_ALIGN.CENTER,
            )
        # Right: classification
        if include_confidential:
            self._text(
                slide, self.w - self.safe - 4.0, y, 4.0, 0.2,
                "CONFIDENTIAL",
                font=self.sans, size=8, italic=True, color=self.deep_60,
                align=PP_ALIGN.RIGHT,
            )
        # Hairline under header (at y=0.50, was 0.70)
        self._hairline(slide, self.safe, y + 0.25, self.w - 2 * self.safe, weight=0.25)

    # ---------- Footer (minimal: mini wordmark + page num) ----------

    def _footer(self, slide, page_num, *, show_page=True, show_wordmark=True):
        """Footer: hairline at y=7.05 (fixed safe_bottom boundary).
        Elements (wordmark + page num) visually centered between hairline and slide bottom (7.50).
        Midpoint = 7.275 → element_y = 7.20.

        `show_wordmark=False` suppresses the left-rail wordmark (used on the
        colophon which renders a hero wordmark in its body — avoids the
        tiny-wordmark-plus-hero-wordmark visual repetition).
        """
        self._hairline(slide, self.safe, 7.05, self.w - 2 * self.safe, weight=0.25)
        element_y = 7.20  # visual center of (7.05, 7.50) zone
        # Left: mini wordmark (suppressed on colophon)
        if show_wordmark:
            self._wordmark(slide, self.safe, element_y, size=8, color=self.deep_60)
        # Center: page num в формате "N/Total"
        if show_page:
            self._text(
                slide, 0, element_y, self.w, 0.18,
                f"{page_num}/{self.total_slides}",
                font=self.sans, size=9, color=self.deep_60,
                align=PP_ALIGN.CENTER,
            )

    # ---------- Section progress bar (little dots with current highlighted) ----------

    def _section_progress(self, slide, x, y, *, current):
        """8 numbered pills showing section progression, current is gold."""
        pill_w = 0.35
        pill_gap = 0.08
        total = self.total_sections
        for i in range(total):
            px = x + i * (pill_w + pill_gap)
            is_current = (i + 1) == current
            # Number
            self._text(
                slide, px, y, pill_w, 0.18,
                f"{i+1:02d}",
                font=self.sans, size=7, bold=is_current,
                color=self.gold if is_current else self.deep_40,
                align=PP_ALIGN.CENTER,
            )
            # Underline hairline
            self._hairline(
                slide, px, y + 0.2, pill_w,
                weight=1.25 if is_current else 0.25,
                color=self.gold if is_current else self.rule_color,
            )

    # ---------- Action title block (full pattern with lime) ----------

    def _action_title(self, slide, text, *, show_lime=True, y=1.0, height=0.95,
                      size=22):
        """Stage C.4: size made overridable so long titles (4+ lines) can
        shrink to 18-20pt to fit. Default 22pt preserved for short titles.
        """
        left = self.safe
        width = self.w - 2 * self.safe
        self._text(
            slide, left, y, width, height,
            text, font=self.serif, size=size, bold=True,
            color=self.deep_100, line_spacing=1.0,
        )
        if show_lime:
            self._lime_under(slide, left, y + height, width)

    # ---------- Pull quote (serif italic 20pt with gold vertical bar) ----------

    def _pull_quote(self, slide, x, y, w, h, text, *, size=18, with_bar=True):
        if with_bar:
            self._vbar(slide, x - 0.1, y, h, weight=2.5, color=self.gold)
        self._text(
            slide, x, y, w, h, text,
            font=self.serif, size=size, italic=True,
            color=self.deep_80, line_spacing=1.35,
        )

    # ---------- Big number (hero callout) ----------

    def _big_number(self, slide, x, y, number, *, label, support=None, size=96):
        self._text(
            slide, x, y - 0.3, 5.0, 0.25, label.upper(),
            font=self.sans, size=8, bold=True, color=self.gold,
        )
        self._hairline(slide, x, y - 0.05, 1.2, weight=0.75, color=self.gold)
        self._text(
            slide, x, y, 5.0, size / 50,
            number, font=self.serif, size=size, color=self.deep_100,
        )
        if support:
            self._text(
                slide, x, y + size / 55, 5.0, 0.3, support,
                font=self.sans, size=10, italic=True, color=self.deep_60,
            )

    # ---------- Source footnote (hairline + italic source) ----------

    def _source(self, slide, y, *, text, width=None):
        """Source footnote. Left-bottom quadrant positioning:
        - No own hairline (footer hairline is single bottom divider)
        - Max width 8.3 inch (left 2/3 of slide) - right side reserved
        - Font size 7 italic deep_60 - minimal weight
        - y=6.67 default: max close to footer hairline 6.85 (0.03 gap above)"""
        width = width or 8.3
        self._text(
            slide, self.safe, y, width, 0.2, text,
            font=self.sans, size=7, italic=True, color=self.deep_60,
        )

    # ---------- Category tag (small gold label above content) ----------

    def _category(self, slide, x, y, text, *, w=6.0, color=None):
        self._text(
            slide, x, y, w, 0.2, text.upper(),
            font=self.sans, size=8, bold=True,
            color=color or self.gold,
        )

    # ----------------------------------------------------------------
    # Narrative helpers (Session C — Path C parametrization)
    # ----------------------------------------------------------------

    def _build_at_a_glance_findings(self):
        """Five findings for s02, slot-filled from self.channels + self.facts.
        Returns list of (num, finding, support) tuples. Safe when some fields
        are None — missing data is elided rather than showing '-'.
        """
        f = self.facts or {}
        leader = f.get("leader_channel") or "Лидер"
        hero = f.get("hero_channel") or leader
        leader_contrib_pct = f.get("leader_share_contrib_pct")
        leader_spend_pct = f.get("leader_share_spend_pct")
        weighted_roi = f.get("weighted_roi")
        reallocation_mln = f.get("reallocation_mln")
        expected_lift_pct = f.get("expected_lift_pct")
        honest = bool(f.get("honest_narrative"))
        media_pct = f.get("media_contribution_pct")
        baseline_pct = f.get("baseline_pct")

        by_mroas = sorted(self.channels, key=lambda c: float(c.get("mroas") or 0), reverse=True)
        hero_ch = by_mroas[0] if by_mroas else {}
        hero_mroas = float(hero_ch.get("mroas") or 0)
        hero_spend_pct = None
        if self.facts and self.facts.get("total_budget_mln"):
            hero_spend_mln = float(hero_ch.get("spend") or 0) / 1_000_000
            total_mln = self.facts.get("total_budget_mln") or 0
            if total_mln > 0:
                hero_spend_pct = hero_spend_mln / total_mln * 100

        # Finding 1 — leader contribution vs budget share
        # Honest mode: baseline-dominated → disclose actual media share, not
        # leader's share-of-media (misleading "X% sales" phrasing).
        if honest and media_pct is not None and baseline_pct is not None:
            f1 = f"Медиа-вклад {_fmt_pct(media_pct)}, baseline {_fmt_pct(baseline_pct)} - модель объясняет продажи через organic"
            s1 = f"{leader} - лидер среди медиа ({_fmt_pct(leader_contrib_pct)} media-вклада)" if leader_contrib_pct is not None else f"{leader} - лидер среди медиа"
        else:
            if leader_contrib_pct is not None and leader_spend_pct is not None:
                f1 = f"{leader} - {_fmt_pct(leader_contrib_pct)} продаж при {_fmt_pct(leader_spend_pct)} бюджета"
            else:
                f1 = f"{leader} - максимальный вклад в продажи"
            if weighted_roi is not None:
                s1 = f"ROI {weighted_roi:.1f}× средневзвешенный по каналам"
            else:
                s1 = "Основной драйвер портфеля"

        # Finding 2 — hero channel by mROAS
        if honest and hero_mroas < 1.0:
            f2 = f"{hero} - лучший среди медиа, но под breakeven (mROAS {hero_mroas:.1f}×)"
            s2 = "ROI < 1× означает что канал тратит больше чем приносит"
        elif hero_mroas > 0:
            f2 = f"{hero} - самый эффективный канал, mROAS {hero_mroas:.1f}×"
            s2 = f"Текущий бюджет на нём {_fmt_pct(hero_spend_pct)}" if hero_spend_pct is not None else "Потенциал для перераспределения бюджета"
        else:
            f2 = f"{hero} - наиболее эффективный канал по mROAS"
            s2 = "Потенциал для перераспределения бюджета"

        # Finding 3 — reallocation / honest disclosure
        def _fmt_mln(v):
            if v is None:
                return "0"
            return f"{v:.1f}" if v < 10 else f"{v:.0f}"

        all_below_breakeven = bool(self.channels) and all(
            (float(c.get("mroas") or c.get("roi") or 0) < 1.0) for c in self.channels
        )
        if honest and all_below_breakeven:
            f3 = "Рекомендация: все каналы под breakeven - сократить медиа или диагностика данных"
            s3 = "При weighted ROI < 1× оптимизация перераспределением не вернёт прибыльность"
        elif reallocation_mln and reallocation_mln >= 0.5 and (
            f.get("cut_source_channel") and f.get("scale_destination_channel")
        ):
            # L15 (math-fix v1.4 Section C): action-driven reallocation subjects
            cut_source = f.get("cut_source_channel")
            scale_dest = f.get("scale_destination_channel")
            f3 = f"Рекомендация: перераспределить {_fmt_mln(reallocation_mln)} млн из {cut_source} в {scale_dest}"
            s3 = f"Ожидаемый прирост ROAS: +{expected_lift_pct:.1f} пп" if expected_lift_pct is not None else "Ожидаемый эффект - положительный"
        elif reallocation_mln and reallocation_mln >= 0.5 and hero != leader:
            # Legacy fallback when cut_source/scale_destination not yet populated
            f3 = f"Рекомендация: перераспределить {_fmt_mln(reallocation_mln)} млн из {leader} в {hero}"
            s3 = f"Ожидаемый прирост ROAS: +{expected_lift_pct:.1f} пп" if expected_lift_pct is not None else "Ожидаемый эффект - положительный"
        else:
            f3 = "Рекомендация: сохранить текущую аллокацию по лидеру портфеля"
            s3 = f"Ожидаемый прирост ROAS: +{expected_lift_pct:.1f} пп" if expected_lift_pct is not None else "Портфель близок к оптимуму"

        # Finding 4 — verdict distribution (how portfolio looks)
        # Stage C.3: idiomatic Russian plural forms (no lazy "канал(ов)" hack).
        verdicts = [c.get("verdict") for c in self.channels]
        scale_n = sum(1 for v in verdicts if v == "Scale")
        cut_n = sum(1 for v in verdicts if v in ("Cut", "Reduce"))
        def _ru_channels(n: int) -> str:
            if n == 0:
                return "ни одного канала"
            if n % 10 == 1 and n % 100 != 11:
                return f"{n} канал"
            if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
                return f"{n} канала"
            return f"{n} каналов"
        f4 = f"Портфель: {_ru_channels(scale_n)} к росту, {_ru_channels(cut_n)} к сокращению"
        s4 = f"Из {len(self.channels)} активных каналов - чёткая рекомендация по каждому"

        # Finding 5 — MQS quality signal (guards None / non-numeric mqs_score)
        try:
            mqs = float(self.mqs_score) if self.mqs_score is not None else 0.0
        except (TypeError, ValueError):
            mqs = 0.0
        if mqs >= 80:
            f5 = f"Качество модели: MQS {mqs:.0f}/100 - готовность к использованию"
            s5 = "Можно опираться на рекомендации в планировании"
        elif mqs >= 60:
            f5 = f"Качество модели: MQS {mqs:.0f}/100 - приемлемо"
            s5 = "Рекомендации валидны с учётом диагностических метрик"
        else:
            f5 = f"Качество модели: MQS {mqs:.0f}/100 - требует доработки"
            s5 = "Следует расширить период данных перед финальными решениями"

        return [
            ("01", f1, s1),
            ("02", f2, s2),
            ("03", f3, s3),
            ("04", f4, s4),
            ("05", f5, s5),
        ]

    def _build_action_table_rows(self, channels):
        """Format merged channels list into the (name, budget, contrib, mROAS,
        share_pct, verdict, footnote) tuples consumed by s07 action table.
        Auto-generates footnote superscripts only for Reduce/Cut verdicts,
        keyed by order (max 3 footnotes to fit bottom-block layout).
        """
        total_contrib = sum(float(c.get("contribution") or 0) for c in channels) or 1.0
        # Assign footnote numbers to the first 3 flagged channels (Reduce/Cut).
        # Filter within channels[:10] (same slice the row loop uses) so the
        # bottom-block footnote text and the row superscript always pair up.
        # (Pre-fix bug: flagged could include channel 15+ which has no rendered
        # row, leaving the bottom-block footnote orphaned.)
        visible = channels[:10]
        flagged = [c for c in visible if c.get("verdict") in ("Reduce", "Cut")][:3]
        fn_by_name = {c["name"]: str(i + 1) for i, c in enumerate(flagged) if c.get("name")}

        rows = []
        for c in channels[:10]:
            name = c.get("name") or "-"
            spend = float(c.get("spend") or 0)
            contrib = float(c.get("contribution") or 0)
            mroas = c.get("mroas")
            verdict = c.get("verdict", "Watch")

            budget_str = f"{spend / 1_000_000:.0f}" if spend else "0"
            contrib_str = f"{contrib / 1_000_000:.0f}" if contrib else "0"
            roi_str = f"{float(mroas):.1f}" if mroas else "-"
            share_pct = int(round(contrib / total_contrib * 100))
            share_str = f"{share_pct}" if share_pct > 0 else "0"
            footnote = fn_by_name.get(name, "")

            # Phase 1.9: posterior 90% HDI bracket on mROAS — None when v1.0/v1.1 pickle.
            ci_low = c.get("mroas_ci_low")
            ci_high = c.get("mroas_ci_high")
            ci_str = ""
            if ci_low is not None and ci_high is not None:
                ci_str = f"[{float(ci_low):.1f} - {float(ci_high):.1f}]"

            rows.append((name, budget_str, contrib_str, roi_str, share_str, verdict, footnote, ci_str))
        return rows

    # ----------------------------------------------------------------
    # SLIDE 01 - COVER
    # ----------------------------------------------------------------

    def s01_cover(self):
        slide = self._blank()

        # Full-height thin gold vertical line (right margin) - visual anchor
        self._vline(
            slide, self.w - self.safe - 0.1,
            self.safe, self.h - 2 * self.safe,
            weight=1.0, color=self.gold,
        )

        # Wordmark top-left
        self._wordmark(slide, self.safe, self.safe, size=16, color=self.deep_100)

        # Horizontal hairline full-width (margin to right-gold-line)
        self._hairline(
            slide, self.safe, self.safe + 0.55,
            self.w - 2 * self.safe - 0.15,
            weight=0.5,
        )

        # Category tag
        self._text(
            slide, self.safe, self.safe + 0.65, 10.0, 0.25,
            "MARKETING MIX MODEL REPORT",
            font=self.sans, size=9, color=self.deep_60,
        )

        # Main title - left aligned, serif regular (not bold - confidence)
        self._text(
            slide, self.safe, 2.6, self.w - 2 * self.safe, 1.3,
            "Декомпозиция медиабюджета",
            font=self.serif, size=48, bold=False, color=self.deep_100,
            line_spacing=1.0,
        )
        # Subtitle in italic
        self._text(
            slide, self.safe, 4.0, self.w - 2 * self.safe, 0.55,
            "и рекомендации по оптимизации",
            font=self.serif, size=24, italic=True, color=self.deep_80,
        )

        # Sacred lime under title
        self._lime_under(slide, self.safe, 4.65, 1.4)

        # 4-column metadata grid bottom
        grid_y = 6.1
        grid_x = self.safe
        cols = [
            ("ПОДГОТОВЛЕНО ДЛЯ", self.client),
            ("ДАТА",              self.report_date),
            ("REPORT ID",         self.report_id),
            ("КЛАССИФИКАЦИЯ",    "Confidential"),
        ]
        col_w = (self.w - 2 * self.safe - 0.2) / 4
        for i, (label, val) in enumerate(cols):
            cx = grid_x + i * col_w
            self._text(
                slide, cx, grid_y, col_w, 0.2, label,
                font=self.sans, size=8, bold=True, color=self.deep_60,
            )
            self._text(
                slide, cx, grid_y + 0.28, col_w, 0.4, val,
                font=self.serif, size=16, color=self.deep_100,
            )
            # Column divider (except last)
            if i < len(cols) - 1:
                self._vline(
                    slide, cx + col_w - 0.05, grid_y + 0.05,
                    0.65, weight=0.25,
                )

        # Bottom hairline + confidentiality (text vertically centered between hairline 7.10 and slide bottom 7.50)
        self._hairline(slide, self.safe, 7.10, self.w - 2 * self.safe - 0.15, weight=0.5)
        # Midpoint 7.30; text box height 0.15 → y = 7.225
        self._text(
            slide, self.safe, 7.225, self.w - 2 * self.safe - 0.15, 0.15,
            self.copyright_line,
            font=self.sans, size=7, italic=True, color=self.deep_60,
            align=PP_ALIGN.CENTER,
        )

    # ----------------------------------------------------------------
    # SLIDE 02 - AT A GLANCE (5 key findings)
    # ----------------------------------------------------------------

    def s02_at_a_glance(self):
        slide = self._blank()
        self._header(slide, slide_num=3)

        self._category(slide, self.safe, 0.60, "ОТЧЁТ ЗА 60 СЕКУНД")
        self._text(
            slide, self.safe, 0.70, 10.0, 0.7,
            "Пять находок",
            font=self.serif, size=32, color=self.deep_100,
        )
        self._hairline(slide, self.safe, 1.50, 1.2, weight=0.75, color=self.gold)

        # Five findings — slot-fill from facts when channels present,
        # else Kagocel pilot text (preview / wireframe mode).
        findings = self._build_at_a_glance_findings() if (self.facts and self.channels) else [
            ("01", "TV обеспечивает 42% инкрементальных продаж при 28% доли бюджета",
             "ROI 1.8× выше среднего по каналам"),
            ("02", "Насыщение на TV начинается с 80 TRP/нед",
             "Предельный ROI падает на 22% относительно IV кв. 2025"),
            ("03", "Digital video - самый эффективный канал с mROAS 1.9×",
             "Текущий бюджет на нём меньше 15%"),
            ("04", "Базовый уровень растёт на 8% год к году - кампании работают на долгосроке",
             "Бренд-эффект виден в динамике"),
            ("05", "Рекомендация: перераспределить 25 млн из TV в digital video",
             "Ожидаемый прирост ROAS: +12 пп к III-IV кв. 2026"),
        ]
        # Stage C.4: findings_y 1.80 → 1.95 (more breathing room below title);
        # finding height 0.45 → 0.55, support y-offset 0.42 → 0.55,
        # step 0.92 → 1.02 (italic subtitle was overlapping next finding).
        y = 1.95
        for i, (num, finding, support) in enumerate(findings):
            # Number
            self._text(
                slide, self.safe, y, 0.7, 0.5, num,
                font=self.serif, size=28, color=self.gold,
            )
            # Finding in Georgia bold
            self._text(
                slide, self.safe + 0.9, y, 9.0, 0.55, finding,
                font=self.serif, size=15, bold=True, color=self.deep_100,
            )
            # Support text (moved lower so italic subtitle doesn't overlap)
            self._text(
                slide, self.safe + 0.9, y + 0.55, 9.0, 0.3, support,
                font=self.sans, size=10, italic=True, color=self.deep_60,
            )
            # Hairline between items only (not after last - footer has its own rule)
            if i < len(findings) - 1:
                self._hairline(slide, self.safe, y + 0.92, self.w - 2 * self.safe, weight=0.25)
            y += 1.02

        self._footer(slide, 3)  # Stage C.6.1: was 2 (TOC moved ahead of Executive Summary)

    # ----------------------------------------------------------------
    # SLIDE 03 - TOC
    # ----------------------------------------------------------------

    def s03_toc(self):
        slide = self._blank()
        self._header(slide, slide_num=2)

        self._category(slide, self.safe, 0.60, "AGENDA")
        self._text(
            slide, self.safe, 0.70, 10.0, 0.7, "Содержание отчёта",
            font=self.serif, size=32, color=self.deep_100,
        )
        self._hairline(slide, self.safe, 1.50, 1.2, weight=0.75, color=self.gold)

        # Main list (5 sections - Stage C.6.3 honest TOC)
        y = 1.85
        for i, (name, pg) in enumerate(zip(self.section_names, self.toc_page_refs), start=1):
            # Number
            self._text(
                slide, self.safe, y, 0.8, 0.4,
                f"{i:02d}", font=self.serif, size=20, color=self.gold,
            )
            # Section name
            self._text(
                slide, self.safe + 0.9, y + 0.05, 7.5, 0.3,
                name, font=self.serif, size=17, color=self.deep_100,
            )
            # Leader dots (dense, tier-1 TOC style)
            leader = "." * 80
            self._text(
                slide, 5.5, y + 0.08, 3.8, 0.3, leader,
                font=self.sans, size=9, color=self.deep_40,
            )
            # Page num (just number, no "стр.")
            self._text(
                slide, 9.5, y + 0.05, 0.6, 0.3,
                f"{pg:02d}",
                font=self.serif, size=14, color=self.deep_100,
                align=PP_ALIGN.RIGHT,
            )
            # Hairline
            self._hairline(slide, self.safe, y + 0.5, 9.7, weight=0.25)
            y += 0.5

        # Right metadata sidebar
        side_x = 10.8
        side_y = 1.85
        side_w = self.w - self.safe - side_x
        # Card bg
        self._rect(slide, side_x, side_y, side_w, 4.0, fill=self.bg_quiet)
        self._text(
            slide, side_x + 0.2, side_y + 0.2, side_w - 0.4, 0.25,
            "ЧТЕНИЕ", font=self.sans, size=8, bold=True, color=self.gold,
        )
        self._hairline(slide, side_x + 0.2, side_y + 0.47, 1.0, weight=0.5, color=self.gold)

        meta = [
            ("Время",            "~12 мин"),
            ("Страниц",          f"{self.total_slides}"),
            ("Разделов",         f"{self.total_sections}"),
            ("Таблиц",           "3"),
            ("Графиков",         "4"),
            ("Слов",             "~2 800"),
            ("MQS модели",       f"{self.mqs_score:.0f} / 100"),
            ("Данные",           self.data_window_label),
        ]
        my = side_y + 0.7
        for label, val in meta:
            self._text(
                slide, side_x + 0.2, my, 0.9, 0.2, label,
                font=self.sans, size=9, color=self.deep_60,
            )
            self._text(
                slide, side_x + 1.1, my, side_w - 1.3, 0.2, val,
                font=self.sans, size=9, bold=True, color=self.deep_100,
                align=PP_ALIGN.RIGHT,
            )
            my += 0.3

        self._footer(slide, 2)  # Stage C.6.1: was 3 (TOC now physical slide 2)

    # ----------------------------------------------------------------
    # SLIDE 04 - SECTION DIVIDER WITH TAKEAWAY
    # ----------------------------------------------------------------

    def _render_section_divider(self, slide_num, *, takeaway, topics):
        """Tier-1 section-divider slide with big number, takeaway, topic list.

        Stage C.6.3: extracted from s04 for reuse by 3 new dividers
        (Методология / Данные / Приложение). `takeaway` may be any string;
        `topics` is a list of short phrases rendered as bullets.
        """
        slide = self._blank()
        self._header(slide, slide_num=slide_num, include_confidential=True)
        section_idx, section_label = self.slide_to_section[slide_num]

        # Big number
        self._text(
            slide, self.safe, 1.3, 4.5, 3.5,
            f"{section_idx:02d}",
            font=self.serif, size=220, color=self.deep_20,
        )

        # Section label
        self._text(
            slide, self.safe + 4.3, 2.1, 8.0, 0.3,
            f"РАЗДЕЛ {section_idx:02d} / {self.total_sections:02d}",
            font=self.sans, size=9, bold=True, color=self.gold,
        )
        # Section name
        self._text(
            slide, self.safe + 4.3, 2.5, 8.0, 0.8,
            section_label,
            font=self.serif, size=40, color=self.deep_100,
        )
        self._lime_under(slide, self.safe + 4.3, 3.35, 2.5)

        # KEY TAKEAWAY
        self._text(
            slide, self.safe + 4.3, 3.7, 8.0, 0.3, "ОСНОВНОЙ ВЫВОД",
            font=self.sans, size=8, bold=True, color=self.gold,
        )
        self._text(
            slide, self.safe + 4.3, 4.05, 8.0, 1.3,
            takeaway,
            font=self.serif, size=20, italic=True, color=self.deep_80,
            line_spacing=1.3,
        )

        # In this section
        self._text(
            slide, self.safe + 4.3, 5.6, 8.0, 0.25, "В ЭТОМ РАЗДЕЛЕ",
            font=self.sans, size=8, bold=True, color=self.deep_60,
        )
        ty = 5.9
        for topic in topics:
            self._text(
                slide, self.safe + 4.3, ty, 8.0, 0.3, f"·  {topic}",
                font=self.sans, size=11, color=self.deep_100,
            )
            ty += 0.28

        # Progress bar
        self._section_progress(slide, self.safe, 6.3, current=section_idx)

        self._footer(slide, slide_num)
        return slide

    def s04_section_divider(self):
        """Divider for section 2 'Декомпозиция вкладов'."""
        if self.facts:
            leader = self.facts.get("leader_channel") or "Лидер"
            cpct = self.facts.get("leader_share_contrib_pct")
            spct = self.facts.get("leader_share_spend_pct")
            if cpct is not None and spct is not None:
                takeaway = (
                    f"{leader} генерирует {_fmt_pct(cpct)} продаж при {_fmt_pct(spct)} бюджета - "
                    "основная точка оптимизации портфеля"
                )
            else:
                takeaway = f"{leader} - основной драйвер портфеля и точка оптимизации"
        else:
            takeaway = "TV генерирует 42% продаж при 28% бюджета - основная точка оптимизации портфеля"
        self._render_section_divider(
            slide_num=6,
            takeaway=takeaway,
            topics=[
                "Индивидуальные вклады каналов и ROI ранжирование",
                "Портфельная таблица с вердиктами по каналам",
                "Декомпозиция недельной динамики продаж",
            ],
        )

    def s_divider_methodology(self):
        """NEW divider for section 3 'Методология'."""
        self._render_section_divider(
            slide_num=10,
            takeaway=(
                "Байесовский MMM с адстоком и Hill-насыщением - "
                "прозрачная математическая модель с интервалами доверия"
            ),
            topics=[
                "Спецификация модели и уравнение отклика",
                "Априорные распределения и ограничения параметров",
                "Диагностика сходимости MCMC",
            ],
        )

    def s_divider_data(self):
        """NEW divider for section 4 'Данные и качество'."""
        tb_mln = self.facts.get("total_budget_mln") if self.facts else None
        if tb_mln:
            takeaway = (
                f"Данные охватывают {self.data_window_label}, бюджет {tb_mln:.0f} млн руб - "
                f"MQS модели {self.mqs_score:.0f}/100"
            )
        else:
            takeaway = (
                f"Данные охватывают {self.data_window_label} - "
                f"MQS модели {self.mqs_score:.0f}/100, готовность к production"
            )
        self._render_section_divider(
            slide_num=12,
            takeaway=takeaway,
            topics=[
                "Источники данных и период наблюдения",
                "Процедуры очистки и обработка выбросов",
                "Метрики качества модели и спецификация",
            ],
        )

    def s_divider_appendix(self):
        """NEW divider for section 5 'Приложение и источники'."""
        self._render_section_divider(
            slide_num=14,
            takeaway=(
                "Справочные материалы отчёта - глоссарий терминов, "
                "методологические ссылки и контактная информация"
            ),
            topics=[
                "Глоссарий ключевых терминов и метрик",
                "Источники данных и референсы",
                "Контакты команды Aurora AI",
            ],
        )

    # ----------------------------------------------------------------
    # SLIDE 05 - KEY MESSAGE (Big Number + Pull Quote)
    # ----------------------------------------------------------------

    def s05_key_message(self):
        slide = self._blank()
        self._header(slide, slide_num=4)

        self._category(slide, self.safe, 0.60, "КЛЮЧЕВОЙ ВЫВОД")

        # Title + big number + pull quote — slot-fill from facts when present,
        # else Kagocel pilot (preview / wireframe mode).
        if self.facts and self.channels:
            leader = self.facts.get("leader_channel") or "Лидер"
            hero = self.facts.get("hero_channel") or leader
            cpct = self.facts.get("leader_share_contrib_pct")
            spct = self.facts.get("leader_share_spend_pct")
            wr = self.facts.get("weighted_roi")
            honest = bool(self.facts.get("honest_narrative"))
            media_pct = self.facts.get("media_contribution_pct")
            baseline_pct = self.facts.get("baseline_pct")

            if honest and media_pct is not None and baseline_pct is not None:
                # Honest narrative: baseline-dominated model (media < 10%).
                # Disclose this rather than leading with leader's media-share.
                title = "Модель преимущественно отражает baseline - медиа-вклад ограничен"
                big_number = _fmt_pct(media_pct)
                big_label = "Медиа-вклад в продажи"
                big_support = f"Baseline: {_fmt_pct(baseline_pct)}. ROI портфеля {wr:.2f}× средневзвешенный." if wr is not None else f"Baseline: {_fmt_pct(baseline_pct)}."
                quote_txt = (
                    f"{leader} - лидер среди медиа ({_fmt_pct(cpct)} media-вклада), "
                    f"но абсолютный media-эффект {_fmt_pct(media_pct)} от продаж. "
                    "Низкая инкрементальность - проверить adstock, saturation, качество данных."
                )
            else:
                # Action title — leader's position statement
                title = f"{leader} остаётся основным драйвером, но эффективность требует проверки насыщения"
                # Big number — leader contribution share
                big_number = _fmt_pct(cpct) if cpct is not None else "-"
                big_label = f"Доля {leader} в инкрементальных продажах"
                if spct is not None and wr is not None:
                    big_support = f"При {_fmt_pct(spct)} доли бюджета. ROI портфеля {wr:.1f}× средневзвешенный."
                else:
                    big_support = "Лидер по вкладу в продажи"
                # Pull quote — hero outperforms leader, reallocate signal
                if hero != leader:
                    quote_txt = (
                        f"Каждый рубль в {hero} возвращает больше, чем в {leader}. "
                        "Сигнал к перераспределению части бюджета в digital."
                    )
                else:
                    quote_txt = (
                        f"{leader} - единственный лидер и по вкладу, и по эффективности. "
                        "Бюджет следует сохранить до признаков насыщения."
                    )
        else:
            title = "TV остаётся основным драйвером, но эффективность достигла локального максимума"
            big_number = "42%"
            big_label = "Доля TV в инкрементальных продажах, I кв."
            big_support = "При 28% доли бюджета. ROI 1.8× выше среднего."
            quote_txt = (
                "Каждый рубль в TV возвращает в 1.8 раза больше, "
                "чем среднее по каналам. Однако начиная с 80 TRP/нед "
                "маржинальный возврат падает - сигнал к перераспределению в digital."
            )

        self._action_title(
            slide,
            title,
            show_lime=True, y=0.80, height=0.90,
        )

        # Left: big number
        self._big_number(
            slide, self.safe, 3.3,
            number=big_number,
            label=big_label,
            support=big_support,
            size=140,
        )

        # Right: pull quote
        quote_x = 6.8
        quote_y = 3.1
        quote_w = self.w - self.safe - quote_x
        self._pull_quote(
            slide, quote_x, quote_y, quote_w, 2.6,
            quote_txt,
            size=18, with_bar=True,
        )

        # Attribution
        self._text(
            slide, quote_x, quote_y + 2.7, quote_w, 0.25,
            "ВЫВОД ИЗ MMM-ДЕКОМПОЗИЦИИ",
            font=self.sans, size=8, bold=True, color=self.deep_60,
        )

        # Source footnote at bottom
        self._source(
            slide, 6.87,
            text=(
                f"Источник: Bayesian MMM · {self.report_id}; данные {self.sources_client_label} {self.data_window_label}; "
                "модель откалибрована под FMCG-бенчмарки."
            ),
        )

        self._footer(slide, 4)

    # ----------------------------------------------------------------
    # SLIDE 06 - ACTION + CHART + COMMENTARY (with annotation)
    # ----------------------------------------------------------------

    def s06_action_chart(self):
        slide = self._blank()
        self._header(slide, slide_num=7)

        self._category(slide, self.safe, 0.60, "ROI ПО КАНАЛАМ")

        # Stage C.5: McKinsey action-first headline via narrative_adapter.
        # Shared helper keeps PPTX+HTML in sync and applies zero-effect guard.
        action_title = (
            derive_action_headline(self.channels, self.facts, "mroas")
            or "Сбалансировать портфель по mROAS"
        )

        # Stage C.4: action title on s06 can run 4+ lines when channel
        # names are long. Height bumped to 1.10 (was 0.80) + font 20pt
        # (was 22pt) to prevent overflow into label row below.
        self._action_title(
            slide,
            action_title,
            show_lime=True, y=0.80, height=1.10, size=20,
        )

        # Chart zone (left 58%)
        chart_x = self.safe
        chart_y = 1.95
        chart_w = (self.w - 2 * self.safe) * 0.58
        chart_h = 3.7

        # Chart title & subtitle
        self._text(
            slide, chart_x, chart_y, chart_w, 0.25,
            "MROAS ПО КАНАЛАМ / МУЛЬТИПЛИКАТОР",
            font=self.sans, size=9, bold=True, color=self.deep_80,
        )
        self._text(
            slide, chart_x, chart_y + 0.27, chart_w, 0.22,
            "Marginal ROI последнего вложенного рубля, Q1 2026",
            font=self.sans, size=9, italic=True, color=self.deep_60,
        )
        # Hairline removed per brand rule - minimize horizontal lines

        # NATIVE PPTX CHART (production-ready) - editable в PowerPoint
        # Data source: adapter-supplied channels sorted by mROAS desc (up to 10),
        # else Kagocel pilot bars for preview / wireframe mode.
        if self.channels:
            by_mroas = sorted(
                self.channels,
                key=lambda c: float(c.get("mroas") or 0),
                reverse=True,
            )[:10]
            bar_labels = [c.get("name") or "-" for c in by_mroas]
            bar_values = [float(c.get("mroas") or 0) for c in by_mroas]
        else:
            bar_labels = ["Digital video", "Search", "TV", "OOH", "Social", "Print"]
            bar_values = [1.9, 1.7, 1.5, 1.2, 1.0, 0.7]
        hero_idx = 0  # by_mroas[0] after sort — highest mROAS (the hero)

        chart_data = CategoryChartData()
        # Reversed: PPTX bar chart renders first category at bottom
        chart_data.categories = list(reversed(bar_labels))
        chart_data.add_series("mROAS", list(reversed(bar_values)))

        bar_area_x = chart_x
        bar_area_y = chart_y + 0.75
        bar_area_w = chart_w
        bar_area_h = 2.9

        graphic_frame = slide.shapes.add_chart(
            XL_CHART_TYPE.BAR_CLUSTERED,
            Inches(bar_area_x), Inches(bar_area_y),
            Inches(bar_area_w), Inches(bar_area_h),
            chart_data,
        )
        chart = graphic_frame.chart
        chart.has_legend = False
        chart.has_title = False

        # Color discipline: ONE gold hero bar (Digital video = last after reverse), others muted
        series = chart.plots[0].series[0]
        # reversed order — hero is at index len-1
        reversed_hero = len(bar_values) - 1 - hero_idx
        for i, point in enumerate(series.points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = self.gold if i == reversed_hero else self.deep_40
            point.format.line.fill.background()

        # Data labels on bar ends
        plot = chart.plots[0]
        plot.has_data_labels = True
        data_labels = plot.data_labels
        data_labels.number_format = '0.0"×"'
        data_labels.font.size = Pt(10)
        data_labels.font.name = self.sans
        data_labels.font.color.rgb = self.deep_80
        from pptx.enum.chart import XL_DATA_LABEL_POSITION
        try:
            data_labels.position = XL_DATA_LABEL_POSITION.OUTSIDE_END
        except Exception:
            pass

        # Axis styling - minimalist (tier-1 MBB spec)
        cat_axis = chart.category_axis
        cat_axis.tick_labels.font.size = Pt(10)
        cat_axis.tick_labels.font.name = self.sans
        cat_axis.tick_labels.font.color.rgb = self.deep_100
        cat_axis.format.line.fill.background()  # no axis line

        val_axis = chart.value_axis
        val_axis.visible = False  # hide numeric value axis (labels are direct)
        val_axis.major_unit = 0.5
        val_axis.minimum_scale = 0
        # Adaptive axis max: accommodate real client mROAS values up to 5×+
        _max_v = max(bar_values) if bar_values else 2.0
        val_axis.maximum_scale = max(2.2, _max_v * 1.15)

        # Gap between bars
        from pptx.oxml.ns import qn
        ser = series._element
        ser_pr = ser.find(qn('c:spPr'))
        # Set gap width via XML (python-pptx limitation for gap_width)
        try:
            bar_chart = chart.plots[0]._element
            gap = bar_chart.find(qn('c:gapWidth'))
            if gap is not None:
                gap.set('val', '60')
        except Exception:
            pass

        # Breakeven reference note above chart (small, tier-1 annotation)
        self._text(
            slide, chart_x + chart_w - 2.5, bar_area_y - 0.22, 2.5, 0.18,
            "1.0× = безубыточность  ·  выше = прибыльно",
            font=self.sans, size=7, italic=True, color=self.deep_60,
            align=PP_ALIGN.RIGHT,
        )

        # Source at bottom (unified position max low to footer hairline)
        self._source(
            slide, 6.87,
            text=f"Источник: Bayesian MMM Aurora AI · {self.report_id}; медианы апостериорного распределения",
        )

        # Right rail: commentary (42%)
        right_x = chart_x + chart_w + 0.4
        right_w = self.w - self.safe - right_x

        self._text(
            slide, right_x, chart_y, right_w, 0.25,
            "ЧТО ЭТО ЗНАЧИТ",
            font=self.sans, size=9, bold=True, color=self.gold,
        )
        self._hairline(slide, right_x, chart_y + 0.3, 1.0, weight=0.75, color=self.gold)

        # Commentary — math-fix v1.0.14.1 B refactor (2026-04-28).
        # Pre-fix: hardcoded «явный потенциал для наращивания» / «потенциал
        # удержания» / «топ-2 канала» blocks based на mROAS rank — independent
        # от derive_verdict в action table → contradictions.
        # Post-fix: action-driven. Reads ch['action_label']/['action_reasoning']
        # populated narrative_adapter via single-source-of-truth
        # engines.channel_action.compute_channel_action. Action в s07 table cell
        # + s06 commentary lead garanteed identical per channel.
        if self.channels and self.facts:
            # Sort by action priority (Scale=5 first, ..., Cut=0). De-dup по
            # action key so same action не shown 3× для 3 Scale channels.
            by_priority = sorted(
                self.channels,
                key=lambda c: (
                    -int(c.get("action_priority") or 0),
                    -float(c.get("mroas") or 0),
                ),
            )
            commentary: list[tuple[str, str]] = []
            seen_actions: set[str] = set()
            for ch in by_priority:
                ch_action = ch.get("action") or "Watch"
                if ch_action == "Uncertain":
                    continue
                if ch_action in seen_actions:
                    continue
                seen_actions.add(ch_action)
                ch_name = ch.get("name") or "-"
                label = ch.get("action_label") or ch_action
                reasoning = ch.get("action_reasoning") or (
                    f"mROAS {float(ch.get('mroas') or 0):.1f}× - рекомендация по портфелю."
                )
                commentary.append((
                    f"{ch_name} - {label}.",
                    f" {reasoning}",
                ))
                if len(commentary) >= 3:
                    break
            # Fallback (legacy callers без action decoration)
            if not commentary:
                hero = by_priority[0] if by_priority else {}
                hero_name = hero.get("name") or "Лидер"
                hero_m = float(hero.get("mroas") or 0)
                commentary.append((
                    f"{hero_name} - лидер по mROAS.",
                    f" mROAS {hero_m:.1f}×. Бюджет следует пересмотреть с учётом saturation.",
                ))
        else:
            # Wireframe placeholder when no channels (preview mode)
            commentary = [
                ("Digital video - Масштабировать.",
                 " mROAS 1.9× — Optimizer рекомендует +50%, недо-инвестирован."),
                ("Search - Удерживать.",
                 " mROAS 1.7× стабилен, gap +1пп — баланс."),
                ("Print и Radio - Сократить.",
                 " mROAS 0.7-0.75× ниже breakeven — бюджет приносит убыток."),
            ]
        cy = chart_y + 0.55
        for lead, body in commentary:
            self._rich(
                slide, right_x, cy, right_w, 1.3,
                runs=[
                    (lead, {"font": self.sans, "size": 11, "bold": True, "color": self.deep_100}),
                    (body, {"font": self.sans, "size": 11, "color": self.deep_80}),
                ],
                line_spacing=1.35,
            )
            self._vbar(slide, right_x - 0.15, cy + 0.03, 1.2, weight=2, color=self.gold)
            cy += 1.35

        self._footer(slide, 7)

    # ----------------------------------------------------------------
    # SLIDE 07 - ACTION + TABLE (with conditional formatting & footnotes)
    # ----------------------------------------------------------------

    def s07_action_table(self):
        slide = self._blank()
        self._header(slide, slide_num=8)

        self._category(slide, self.safe, 0.60, "ПОРТФЕЛЬ КАНАЛОВ")

        # Action title - data-driven: top-N contributors covering >=85% of
        # incremental sales. Handles edge cases (single channel, all-zero
        # contributions, balanced portfolio) with idiomatic Russian phrasing.
        # Fallback ("Пять каналов...") applies only in preview / wireframe
        # mode when no channels supplied.
        # Stage C.5: McKinsey action-first headline via narrative_adapter.
        # Covers all edge cases (all-zero / single-channel / consolidate / balanced).
        s07_title = (
            derive_action_headline(self.channels, self.facts, "portfolio")
            or "Консолидировать до топ-5 каналов - они обеспечивают 87% продаж"
        )
        self._action_title(
            slide, s07_title,
            show_lime=True, y=0.80, height=0.80,
        )

        # Custom table
        table_x = self.safe
        table_y = 1.95
        table_w = self.w - 2 * self.safe
        # Proportional columns: Channel / Budget / Contribution / ROI / Share / Verdict
        col_weights = [3.2, 1.8, 1.8, 1.4, 1.5, 1.8]
        total_w = sum(col_weights)
        col_widths = [w * (table_w / total_w) for w in col_weights]

        # Header
        headers = ["Канал", "Бюджет", "Вклад", "mROAS", "Доля эффекта", "Вердикт"]
        units =   ["",      "₽ млн",  "₽ млн",  "×",     "%",             ""]
        x = table_x
        for i, (hdr, cw) in enumerate(zip(headers, col_widths)):
            align = PP_ALIGN.LEFT if i in (0, 5) else PP_ALIGN.RIGHT
            self._text(
                slide, x + (0.05 if align == PP_ALIGN.LEFT else 0),
                table_y, cw - 0.1, 0.25,
                hdr.upper(),
                font=self.sans, size=9, bold=True, color=self.deep_100, align=align,
            )
            if units[i]:
                self._text(
                    slide, x + (0.05 if align == PP_ALIGN.LEFT else 0),
                    table_y + 0.27, cw - 0.1, 0.2, units[i],
                    font=self.sans, size=8, italic=True, color=self.deep_60, align=align,
                )
            x += cw
        # Header hairline (thick)
        self._hairline(slide, table_x, table_y + 0.55, table_w, weight=0.75, color=self.deep_100)

        # Data rows — sourced from adapter-supplied self.channels when present;
        # fallback to Kagocel pilot rows for preview / wireframe mode.
        if self.channels:
            rows = self._build_action_table_rows(self.channels)
        else:
            rows = [
                ("Digital video", "65",  "110",  "1.9", "26",  "Scale",  ""),
                ("TV",            "120", "180",  "1.5", "42",  "Scale",  "1"),
                ("Search",        "28",  "48",   "1.7", "11",  "Scale",  ""),
                ("OOH",           "35",  "52",   "1.5", "12",  "Hold",   ""),
                ("Social",        "18",  "24",   "1.3", "6",   "Watch",  "2"),
                ("Print",         "12",  "8",    "0.7", "2",   "Cut",    "3"),
                ("Radio",         "8",   "6",    "0.8", "1",   "Cut",    ""),
            ]
        verdict_colors = {
            "Scale":  (self.deep_100, True),
            "Hold":   (self.deep_60, False),
            "Watch":  (self.deep_60, False),
            "Reduce": (self.gold_muted, True),
            "Cut":    (self.gold, True),
        }
        # Stage C.3: display verdicts in Russian. Enum keys stay English
        # internally so derive_verdict() and downstream narrative helpers
        # remain unchanged.
        verdict_ru = {
            "Scale":  "Увеличить",
            "Hold":   "Держать",
            "Watch":  "Наблюдать",
            "Reduce": "Сократить",
            "Cut":    "Остановить",
        }
        row_y = table_y + 0.65
        for row in rows:
            # Phase 1.9: rows are 8-tuples (added ci_str). Backward compat for fallback
            # 7-tuple wireframe rows: pad with empty ci_str.
            if len(row) == 7:
                row = row + ("",)
            channel, budget, contrib, roi, share, verdict, footnote, ci_str = row
            # Channel name
            x = table_x
            self._text(
                slide, x + 0.05, row_y, col_widths[0] - 0.1, 0.3,
                channel,
                font=self.sans, size=11, bold=True, color=self.deep_100,
            )
            x += col_widths[0]
            # Budget
            self._text(
                slide, x, row_y, col_widths[1] - 0.1, 0.3, budget,
                font=self.sans, size=11, color=self.deep_100,
                align=PP_ALIGN.RIGHT,
            )
            x += col_widths[1]
            # Contribution
            self._text(
                slide, x, row_y, col_widths[2] - 0.1, 0.3, contrib,
                font=self.sans, size=11, color=self.deep_100,
                align=PP_ALIGN.RIGHT,
            )
            x += col_widths[2]
            # mROAS (with footnote and/or Phase 1.9 90% HDI bracket if present)
            mroas_runs = [(roi, {"font": self.sans, "size": 11, "color": self.deep_100})]
            if ci_str:
                mroas_runs.append(
                    (" " + ci_str, {"font": self.sans, "size": 8, "color": self.deep_60})
                )
            if footnote:
                mroas_runs.append(
                    (footnote, {"font": self.sans, "size": 7, "color": self.gold})
                )
            if len(mroas_runs) > 1:
                self._rich(
                    slide, x, row_y, col_widths[3] - 0.1, 0.3,
                    runs=mroas_runs,
                    align=PP_ALIGN.RIGHT,
                )
            else:
                self._text(
                    slide, x, row_y, col_widths[3] - 0.1, 0.3, roi,
                    font=self.sans, size=11, color=self.deep_100,
                    align=PP_ALIGN.RIGHT,
                )
            x += col_widths[3]
            # Share %
            self._text(
                slide, x, row_y, col_widths[4] - 0.1, 0.3, share,
                font=self.sans, size=11, color=self.deep_100,
                align=PP_ALIGN.RIGHT,
            )
            x += col_widths[4]
            # Verdict — fallback to Hold styling if unknown key
            vcolor, vbold = verdict_colors.get(verdict, (self.deep_60, False))
            verdict_label = verdict_ru.get(verdict, verdict)
            self._text(
                slide, x + 0.05, row_y, col_widths[5] - 0.1, 0.3, verdict_label,
                font=self.sans, size=11, bold=vbold, color=vcolor,
            )
            # Row hairline
            self._hairline(slide, table_x, row_y + 0.32, table_w, weight=0.25, color=self.deep_20)
            row_y += 0.35

        # Total row (compact) — data-driven when facts present, else Kagocel pilot
        self._text(
            slide, table_x + 0.05, row_y + 0.02, col_widths[0] - 0.1, 0.25,
            "ИТОГО",
            font=self.sans, size=10, bold=True, color=self.deep_100,
        )
        if self.facts:
            tb = self.facts.get("total_budget_mln") or 0
            tc = self.facts.get("total_contrib_mln") or 0
            wr = self.facts.get("weighted_roi")
            totals = [
                f"{tb:.0f}",
                f"{tc:.0f}",
                f"{wr:.2f}" if wr is not None else "-",
                "100",
            ]
        else:
            totals = ["286", "428", "1.50", "100"]
        aligns = [PP_ALIGN.RIGHT] * 4
        x = table_x + col_widths[0]
        for w, v, al in zip(col_widths[1:5], totals, aligns):
            self._text(
                slide, x, row_y + 0.02, w - 0.1, 0.25, v,
                font=self.sans, size=11, bold=True, color=self.deep_100,
                align=al,
            )
            x += w
        self._hairline(slide, table_x, row_y + 0.32, table_w, weight=0.75, color=self.deep_100)

        # Unified bottom block: ПРИМЕЧАНИЯ label + up to 3 data-driven footnotes
        # generated from flagged channels (Reduce/Cut) - matches footnote
        # numbers already assigned in _build_action_table_rows. Preview /
        # wireframe mode falls back to Kagocel pilot footnotes below.
        if self.channels:
            # Filter flagged within the same [:10] window the table rows use,
            # so bottom-block text pairs with the rendered row superscripts.
            flagged = [c for c in self.channels[:10] if c.get("verdict") in ("Reduce", "Cut")][:3]
            reason_by_verdict = {
                "Cut": "ниже точки безубыточности по mROAS; рекомендовано остановить или перевести в другие каналы.",
                "Reduce": "достигнуто насыщение; маржинальный возврат от дополнительного рубля ниже среднего по портфелю.",
            }
            footnotes = [
                (str(i + 1), f"{c.get('name') or '-'}: {reason_by_verdict.get(c.get('verdict'), 'рекомендовано пересмотреть аллокацию.')}")
                for i, c in enumerate(flagged)
            ]
            if not footnotes:
                # No flagged channels - single informational note.
                footnotes = [("1", "Все каналы портфеля в рабочем диапазоне mROAS; критических рекомендаций нет.")]
        else:
            footnotes = [
                ("1", "TV: mROAS считается при текущих 85 TRP/нед; выше 100 TRP/нед ROI падает ниже 1.2×."),
                ("2", "Social volatile - mROAS 1.3× median, но CI 0.8 1.8× (высокая неопределённость)."),
                ("3", "Print: ниже точки безубыточности; рекомендация основана на 3-квартальном тренде."),
            ]
        line_h = 0.14
        # Layout (bottom-up): source (6.87) · fn3 (6.73) · fn2 (6.59) · fn1 (6.45) · label (6.30)
        label_y = 6.30
        self._text(
            slide, self.safe, label_y, 1.5, line_h, "ПРИМЕЧАНИЯ",
            font=self.sans, size=7, bold=True, color=self.deep_60,
        )
        fy = label_y + 0.15
        for num, txt in footnotes:
            self._rich(
                slide, self.safe, fy, 8.3, line_h,
                runs=[
                    (num, {"font": self.sans, "size": 7, "bold": True, "color": self.gold}),
                    ("  " + txt, {"font": self.sans, "size": 7, "italic": True, "color": self.deep_60}),
                ],
                line_spacing=1.0,
            )
            fy += line_h
        # Source at y=6.67 (max close to footer hairline 6.85)
        self._source(
            slide, 6.87,
            text=f"Источник: Bayesian MMM Aurora AI · {self.report_id}; доверительный интервал 95%, медианы апостериорного распределения."
        )

        self._footer(slide, 7)

    # ----------------------------------------------------------------
    # SLIDE 08 - ACTION + FULL TIMELINE (with annotations)
    # ----------------------------------------------------------------

    def s08_action_timeline(self):
        slide = self._blank()
        self._header(slide, slide_num=9)

        self._category(slide, self.safe, 0.60, "ДИНАМИКА")

        # Stage C.5: timeline action headline = schedule recommendation.
        title = (
            derive_action_headline(self.channels, self.facts, "timeline")
            or "Пульсирующее размещение вместо непрерывного - экономия 15-20% без потери охвата"
        )
        self._action_title(
            slide,
            title,
            show_lime=True, y=0.80, height=0.80,
        )

        chart_x = self.safe
        chart_y = 1.95
        chart_w = self.w - 2 * self.safe
        chart_h = 3.7

        # Subtitle: when real time_series is present we know exact period
        # range; otherwise fall back to data_window_label preview text.
        ts = self.time_series if isinstance(self.time_series, dict) else None
        if ts and ts.get("dates"):
            dates_list = list(ts["dates"])
            period_label = f"{dates_list[0]} - {dates_list[-1]}" if dates_list else self.data_window_label
        else:
            period_label = self.data_window_label

        self._text(
            slide, chart_x, chart_y, chart_w, 0.25,
            "ПРОДАЖИ ПО ПЕРИОДАМ / ₽",
            font=self.sans, size=9, bold=True, color=self.deep_80,
        )
        self._text(
            slide, chart_x, chart_y + 0.27, chart_w, 0.22,
            f"Базовый уровень + вклад каждого канала · {period_label}",
            font=self.sans, size=9, italic=True, color=self.deep_60,
        )
        # Hairline removed per brand rule - minimize horizontal lines

        # ── Real stacked area chart from decomposition.time_series ────────
        # If pipeline provided per-period series, render a native python-pptx
        # AREA_STACKED chart (real data, real categorical x-axis). Otherwise
        # fall back to legacy preview/wireframe mode that paints stylized
        # rectangles week-by-week (Kagocel pilot bands).
        if ts and ts.get("dates") and ts.get("baseline"):
            from .charts import make_timeline_area

            chart_inner_x = chart_x
            chart_inner_y = chart_y + 0.8
            chart_inner_w = chart_w
            chart_inner_h = 2.8

            channel_series = ts.get("channels") or {}
            # Trim to top-5 channels by total contribution to keep legend
            # readable; small contributors aggregate into baseline visually
            # (approximation — true total would re-add their per-period sums).
            ranked = sorted(
                channel_series.items(),
                key=lambda kv: sum(float(v) for v in kv[1] or []),
                reverse=True,
            )[:5]
            channel_dict = {name: list(values) for name, values in ranked}

            make_timeline_area(
                slide,
                chart_inner_x, chart_inner_y, chart_inner_w, chart_inner_h,
                dates=list(ts["dates"]),
                baseline=list(ts["baseline"]),
                channel_series=channel_dict,
            )

            # Source at bottom (unified position, real-data variant)
            self._source(
                slide, 6.87,
                text=f"Источник: {self.sources_client_label}, продажи за период {period_label}; декомпозиция Bayesian MMM · {self.report_id}",
            )

            self._footer(slide, 9)
            return

        # ── Legacy preview/wireframe path (no real time_series) ───────────
        weeks = 13
        area_x = chart_x + 0.7  # leave space for y-axis labels
        area_y = chart_y + 0.8
        area_w = chart_w - 2.8  # leave space for legend on right
        area_h = 2.6

        # Bands - data-driven from top contributors when channels present,
        # else Kagocel pilot bands (preview / wireframe mode).
        # Target peak-sum under area_h (2.6") accounting for leader seasonal
        # multiplier up to 1.6×.
        palette = [self.gold, self.deep_80, self.deep_60, self.deep_40, self.deep_20, self.deep_20]
        if self.channels:
            by_contrib = sorted(
                self.channels,
                key=lambda c: float(c.get("contribution") or 0),
                reverse=True,
            )[:5]
            total_c = sum(float(c.get("contribution") or 0) for c in by_contrib) or 1.0
            # Channel bands occupy ~55% of total height; baseline ~45%.
            channel_h_budget = 1.10  # inches, fits sum × peak mod ≤ area_h
            baseline_h = 0.85
            bands = [("Базовый уровень", self.deep_40, baseline_h)]
            for i, c in enumerate(by_contrib):
                share = float(c.get("contribution") or 0) / total_c
                bands.append((
                    c.get("name") or "-",
                    palette[i % len(palette)],
                    max(0.05, share * channel_h_budget),
                ))
            # Leader name = first channel after baseline (highest contribution)
            leader_name = bands[1][0] if len(bands) > 1 else None
        else:
            bands = [
                ("Базовый уровень", self.deep_40, 0.85),
                ("TV",            self.gold,    0.55),
                ("Digital video", self.deep_80, 0.35),
                ("Search",        self.deep_60, 0.17),
                ("OOH",           self.deep_20, 0.12),
                ("Social",        self.deep_20, 0.07),
            ]
            leader_name = "TV"
        seg_w = area_w / weeks

        # Draw stacked with seasonal modulation.
        # Preview mode retains W06/W11 TV flights; real-data mode uses generic
        # sinusoidal seasonality without synthetic flight spikes.
        preview_mode = not self.channels
        for w_idx in range(weeks):
            week_x = area_x + w_idx * seg_w
            base_mod = 0.9 + 0.15 * math.sin(w_idx / 13 * 2 * math.pi)
            if preview_mode and w_idx in (5, 10):
                leader_mod = 1.6
            elif preview_mode:
                leader_mod = 0.85 if w_idx in (4, 6, 9, 11) else 0.7
            else:
                leader_mod = 0.95 + 0.15 * math.sin(w_idx / 4.2 + 0.7)

            y_top = area_y + area_h
            for name, col, base_h in bands:
                if name == leader_name:
                    h_band = base_h * leader_mod
                elif name == "Baseline":
                    h_band = base_h * base_mod
                else:
                    # zlib.crc32 is deterministic across processes (unlike
                    # built-in hash() which is salted with PYTHONHASHSEED).
                    # Keeps band modulation phase stable between builds so
                    # slide XML content is reproducible for diffing / review.
                    # (Outer PPTX SHA still varies due to python-pptx save-time
                    # timestamps in docProps/core.xml - that is outside scope.)
                    jitter = zlib.crc32(name.encode("utf-8")) % 7
                    h_band = base_h * (0.95 + 0.1 * math.sin(w_idx / 5 + jitter))
                y_top -= h_band
                self._rect(slide, week_x, y_top, seg_w, h_band, fill=col)

        # Y-axis label ticks (3 values)
        for i, (v, y_pos) in enumerate([(5, 0.1), (3, area_h / 2), (0, area_h - 0.1)]):
            self._text(
                slide, chart_x, area_y + y_pos - 0.1, 0.6, 0.2,
                str(v), font=self.sans, size=8, color=self.deep_60,
                align=PP_ALIGN.RIGHT,
            )
        self._vline(slide, area_x, area_y, area_h, weight=0.5, color=self.deep_60)

        # X-axis labels
        self._hairline(slide, area_x, area_y + area_h, area_w, weight=0.5, color=self.deep_60)
        for wk in [1, 3, 5, 7, 9, 11, 13]:
            xp = area_x + (wk - 1) * seg_w
            self._text(
                slide, xp - 0.25, area_y + area_h + 0.08, 0.5, 0.18,
                f"W{wk:02d}",
                font=self.sans, size=7, color=self.deep_60, align=PP_ALIGN.CENTER,
            )

        # Annotations - only in preview mode (TV flight narrative is Kagocel-
        # specific). Real-data runs show clean bands without flight callouts;
        # per-week peak detection is deferred to XLSX "Динамика" sheet.
        if preview_mode:
            w06_x = area_x + 5 * seg_w + seg_w / 2
            ann_y_top = area_y - 0.3
            self._text(
                slide, w06_x - 0.9, ann_y_top, 1.8, 0.2,
                "TV FLIGHT . 95 TRP/нед",
                font=self.sans, size=7, bold=True, color=self.gold, align=PP_ALIGN.CENTER,
            )
            self._vline(slide, w06_x, area_y, 0.08, weight=1.5, color=self.gold)

            w11_x = area_x + 10 * seg_w + seg_w / 2
            self._text(
                slide, w11_x - 0.9, ann_y_top, 1.8, 0.2,
                "HOLIDAY PUSH . DIGITAL",
                font=self.sans, size=7, bold=True, color=self.gold, align=PP_ALIGN.CENTER,
            )
            self._vline(slide, w11_x, area_y, 0.08, weight=1.5, color=self.gold)

        # Legend on the right
        leg_x = area_x + area_w + 0.3
        leg_y = area_y + 0.1
        leg_w = chart_x + chart_w - leg_x
        self._text(
            slide, leg_x, leg_y - 0.3, leg_w, 0.2, "КАНАЛЫ",
            font=self.sans, size=8, bold=True, color=self.deep_80,
        )
        self._hairline(slide, leg_x, leg_y - 0.05, 0.8, weight=0.5, color=self.rule_color)
        for i, (name, col, _) in enumerate(bands):
            sw = self._rect(
                slide, leg_x, leg_y + i * 0.35, 0.15, 0.15, fill=col,
            )
            self._text(
                slide, leg_x + 0.25, leg_y + i * 0.35 - 0.02, leg_w - 0.3, 0.2, name,
                font=self.sans, size=9, color=self.deep_100,
            )

        # Source at bottom (unified position)
        self._source(
            slide, 6.87,
            text=f"Источник: {self.sources_client_label}, продажи за период {self.data_window_label}; декомпозиция Bayesian MMM · {self.report_id}",
        )

        self._footer(slide, 9)

    # ----------------------------------------------------------------
    # SLIDE 09 - EXECUTIVE SUMMARY (SCQAR)
    # ----------------------------------------------------------------

    def s09_scqar(self):
        slide = self._blank()
        self._header(slide, slide_num=5)

        self._category(slide, self.safe, 0.60, "РЕКОМЕНДАЦИЯ")

        # Build SCQAR blocks from facts when present, else Kagocel pilot.
        if self.facts and self.channels:
            f = self.facts
            leader = f.get("leader_channel") or "Лидер"
            hero = f.get("hero_channel") or leader
            tb = f.get("total_budget_mln") or 0
            n_ch = f.get("n_active_channels") or len(self.channels)
            wr = f.get("weighted_roi")
            leader_spend_pct = f.get("leader_share_spend_pct")
            realloc = f.get("reallocation_mln") or 0
            lift = f.get("expected_lift_pct")
            # Hero mROAS
            hero_ch = next((c for c in self.channels if c.get("name") == hero), {})
            hero_m = float(hero_ch.get("mroas") or 0)
            # Underperformer names. L23 fix (2026-04-29): dedup от cut_source —
            # narrative_adapter уже исключил cut_source из underperformer_names
            # в facts dict, но self.channels — raw merged list. Apply here
            # locally for PPTX consistency (avoid «из TRPs ... остановить TRPs»).
            cut_source_local = (self.facts or {}).get("cut_source_channel")
            underperf = [
                c.get("name") for c in self.channels
                if c.get("verdict") in ("Cut", "Reduce") and c.get("name") != cut_source_local
            ]
            underperf_str = ", ".join(underperf) if underperf else "отстающие каналы"

            # Stage C.5: McKinsey 3-scenario SCQAR action headline.
            # narrative_adapter.derive_action_headline handles:
            #   - Risk (all underperf) → "Сократить X и сфокусировать на Y"
            #   - Rebalance (lift ≥ 0.5pp) → "Перераспределить N млн ₽ в Y - +X пп к ROAS"
            #   - Hold + control (weak lift) → "Портфель сбалансирован - A/B тест"
            action_title = (
                derive_action_headline(self.channels, self.facts, "scqar")
                or f"Пересмотреть аллокацию {leader}"
            )

            situation_body = (
                f"{self.client} размещает {tb:.0f} млн ₽ в квартал через {n_ch} активных каналов. "
                + (f"Средневзвешенный ROI {wr:.1f}×, " if wr is not None else "")
                + f"MQS модели {self.mqs_score:.0f}/100."
            )

            # L14 (math-fix v1.4 Section C, 2026-04-29): use budget_dominator
            # вместо leader (top contribution). budget_dominator = max spend.
            budget_dom = f.get("budget_dominator_channel") or leader
            bd_spend_pct = f.get("budget_dominator_spend_pct") or leader_spend_pct
            bd_contrib_pct = f.get("budget_dominator_contrib_pct") or 0.0
            complication_parts = []
            if budget_dom and bd_spend_pct is not None and abs((bd_spend_pct or 0) - (bd_contrib_pct or 0)) >= 5.0:
                complication_parts.append(
                    f"{budget_dom} занимает {_fmt_pct(bd_spend_pct)} бюджета, "
                    f"но даёт {_fmt_pct(bd_contrib_pct)} эффекта"
                )
            if hero != leader and hero_m >= 1.0:
                complication_parts.append(f"по mROAS {hero} опережает ({hero_m:.1f}×)")
            if underperf:
                complication_parts.append(f"{underperf_str} тянут портфель вниз")
            complication_body = ". ".join(complication_parts) + (". Портфель требует перебалансировки." if complication_parts else "Портфель требует перебалансировки.")

            # L15 (math-fix v1.4 Section C, 2026-04-29): use cut_source /
            # scale_destination from action_summary вместо leader/hero.
            cut_source = f.get("cut_source_channel")
            scale_dest = f.get("scale_destination_channel")
            answer_parts = []
            if cut_source and scale_dest and realloc >= 1:
                answer_parts.append(f"Перераспределить {realloc:.0f} млн ₽ из {cut_source} в {scale_dest}")
            elif scale_dest and realloc >= 1:
                answer_parts.append(f"Нарастить {scale_dest} на ~{realloc:.0f} млн ₽")
            elif cut_source and realloc >= 1:
                answer_parts.append(f"Сократить {cut_source} ({realloc:.0f} млн ₽)")
            if underperf:
                answer_parts.append(f"остановить {underperf_str}")
            answer_body = "; ".join(answer_parts) + "." if answer_parts else f"Сохранить текущую аллокацию по {leader} с контролем насыщения."

            blocks = [
                {"label": "СИТУАЦИЯ", "height": 0.6, "body": situation_body},
                {"label": "ПРОБЛЕМА", "height": 0.8, "body": complication_body},
                {"label": "ВОПРОС", "height": 0.55,
                 "body": "Как перераспределить бюджет, чтобы поднять ROAS без снижения охвата знания?",
                 "accent": True},
                {"label": "ОТВЕТ", "height": 0.6, "body": answer_body},
                {"label": "РЕКОМЕНДАЦИИ", "height": 2.3, "body": None},
            ]
        else:
            action_title = "Сократить TV до 60 TRP/нед и удвоить Digital Video"
            blocks = [
                {"label":  "СИТУАЦИЯ",
                 "height": 0.6,
                 "body":   f"{self.client} размещает 286 млн ₽ в квартал через 5 активных каналов. Средневзвешенный ROI 1.5×, MQS модели {self.mqs_score:.0f}/100."},
                {"label":  "ПРОБЛЕМА",
                 "height": 0.8,
                 "body":   "TV достиг насыщения: выше 80 TRP/нед маржинальный ROI падает на 22% год к году. Digital video недоинвестирован (<15% бюджета при mROAS 1.9×). Портфель не оптимизирован."},
                {"label":  "ВОПРОС",
                 "height": 0.55,
                 "body":   "Как перераспределить бюджет, чтобы поднять ROAS без снижения охвата знания?",
                 "accent": True},
                {"label":  "ОТВЕТ",
                 "height": 0.6,
                 "body":   "Сократить TV с 120 до 90 млн ₽/квартал, увеличить Digital video с 65 до 100 млн, сохранить Search/OOH, остановить Print и Radio."},
                {"label":  "РЕКОМЕНДАЦИИ",
                 "height": 2.3,  # Stage C.4: was 2.0; 3 actions need more room
                 "body":   None},
            ]

        self._action_title(
            slide,
            action_title,
            show_lime=True, y=0.80, height=0.85,
        )

        y = 2.3
        for b in blocks:
            # Gold bar
            accent = b.get("accent", False)
            bar_color = self.gold if accent else self.deep_40
            self._vbar(slide, self.safe, y + 0.05, b["height"] - 0.1, weight=3 if accent else 2, color=bar_color)
            # Label
            self._text(
                slide, self.safe + 0.2, y, 2.0, 0.28, b["label"],
                font=self.sans, size=9, bold=True,
                color=self.gold if accent else self.deep_60,
            )
            # Body (Stage C.4: font 12→11 reduces wrap → no overlap between blocks)
            if b["body"]:
                self._text(
                    slide, self.safe + 2.3, y, 7.5, b["height"] - 0.1,
                    b["body"],
                    font=self.sans, size=11,
                    italic=accent,
                    color=self.deep_100,
                    line_spacing=1.3,
                )
            else:
                # Recommendation - 3 templated actions when facts present.
                # L15 audit fix (2026-04-29): Action 01 uses cut_source/scale_dest
                # from action_summary (NOT leader/hero) — same fix как s09 SCQAR.
                if self.facts and self.channels:
                    f = self.facts
                    leader = f.get("leader_channel") or "Лидер"
                    hero = f.get("hero_channel") or leader
                    realloc = f.get("reallocation_mln") or 0
                    lift = f.get("expected_lift_pct")
                    underperf = [c.get("name") for c in self.channels if c.get("verdict") in ("Cut",)]
                    lift_txt = f"+{lift:.1f} пп к ROAS по прогнозу" if lift is not None else "Положительный прирост ROAS по прогнозу"
                    cut_source = f.get("cut_source_channel")
                    scale_dest = f.get("scale_destination_channel")

                    if cut_source and scale_dest and realloc >= 1:
                        action_01_body = (
                            f" {realloc:.0f} млн ₽ из {cut_source} в {scale_dest}. "
                            "Отложенный эффект (adstock) компенсирует краткосрочный спад охвата."
                        )
                    elif scale_dest and realloc >= 1:
                        action_01_body = (
                            f" Нарастить {scale_dest} на ~{realloc:.0f} млн ₽ — "
                            "за счёт roll-over бюджета или дополнительных средств."
                        )
                    elif cut_source and realloc >= 1:
                        action_01_body = (
                            f" Сократить {cut_source} ({realloc:.0f} млн ₽) — "
                            "текущая аллокация неэффективна."
                        )
                    elif hero != leader and realloc >= 1:
                        # Legacy fallback (cut_source/scale_dest unavailable)
                        action_01_body = (
                            f" {realloc:.0f} млн ₽ из {leader} в {hero}. "
                            "Отложенный эффект (adstock) компенсирует краткосрочный спад охвата."
                        )
                    else:
                        action_01_body = f" Сохранить аллокацию по {leader} с контролем индикаторов насыщения."

                    actions = [
                        ("01", "Перераспределить бюджет.", action_01_body),
                        ("02",
                         "Пульсирующее размещение вместо непрерывного.",
                         f" Короткие флайты {leader} с паузами - экономия бюджета 15-20% при сохранении охвата."),
                        ("03",
                         "Целевой ретаргетинг через эффективные сегменты.",
                         f" Приоритетный сегмент - {scale_dest or hero}; {lift_txt}."
                            + (f" Бюджет переводим из {', '.join(underperf)}." if underperf else "")),
                    ]
                else:
                    actions = [
                        ("01",
                         "Перераспределить бюджет.",
                         " 25 млн ₽ из TV в Digital video. Экономия при сохранении инкрементальных продаж (отложенный эффект компенсирует)."),
                        ("02",
                         "Недельные пульсы вместо непрерывного размещения.",
                         " TV флайты по 60 TRP × 3 недели с паузами. Экономия 18%, охват устойчив."),
                        ("03",
                         "Целевой ретаргетинг W25-54 через CTV/OLV.",
                         " Сегмент с априорным ROI 2.1×; сейчас недоинвестирован. Потенциал +12 млн ₽ инкрементальных продаж."),
                    ]
                ay = y
                for num, lead, body in actions:
                    # Number
                    self._text(
                        slide, self.safe + 2.3, ay, 0.4, 0.3, num,
                        font=self.serif, size=13, color=self.gold,
                    )
                    # Lead (bold) on first line
                    self._text(
                        slide, self.safe + 2.8, ay, 7.0, 0.22, lead,
                        font=self.sans, size=11, bold=True, color=self.deep_100,
                    )
                    # Body (regular) on next line
                    self._text(
                        slide, self.safe + 2.8, ay + 0.25, 7.0, 0.35, body.strip(),
                        font=self.sans, size=11, color=self.deep_80, line_spacing=1.25,
                    )
                    ay += 0.65
            y += b["height"]

        # Expected impact box (bottom right)
        impact_x = 10.5
        impact_y = 5.2
        self._text(
            slide, impact_x, impact_y, 2.5, 0.22, "ОЖИДАЕМЫЙ ЭФФЕКТ",
            font=self.sans, size=8, bold=True, color=self.gold,
        )
        self._hairline(slide, impact_x, impact_y + 0.27, 1.2, weight=0.75, color=self.gold)
        if self.facts and self.facts.get("expected_lift_pct") is not None:
            impact_num = f"+{self.facts['expected_lift_pct']:.0f} пп"
        else:
            impact_num = "+12 пп"
        self._text(
            slide, impact_x, impact_y + 0.35, 2.5, 0.7, impact_num,
            font=self.serif, size=42, color=self.deep_100,
        )
        self._text(
            slide, impact_x, impact_y + 1.1, 2.5, 0.22, "Прогнозный ROAS",
            font=self.sans, size=10, italic=True, color=self.deep_60,
        )

        self._footer(slide, 5)

    # ----------------------------------------------------------------
    # SLIDE 10 - METHODOLOGY + LIMITATIONS
    # ----------------------------------------------------------------

    # C.6.3: s10 methodology content now at physical page 11 (divider at 10).
    def s10_methodology(self):
        slide = self._blank()
        self._header(slide, slide_num=11)

        self._category(slide, self.safe, 0.60, "ПОДХОД")

        self._action_title(
            slide,
            "Байесовская MMM с adstock + Hill-насыщением",
            show_lime=True, y=0.80, height=0.80,
        )

        # Two columns
        left_x = self.safe
        left_y = 1.85
        left_w = (self.w - 2 * self.safe) * 0.48

        # LEFT: Formula card
        self._text(
            slide, left_x, left_y, left_w, 0.25, "СПЕЦИФИКАЦИЯ",
            font=self.sans, size=9, bold=True, color=self.gold,
        )
        self._hairline(slide, left_x, left_y + 0.28, 1.0, weight=0.75, color=self.gold)

        self._rect(slide, left_x, left_y + 0.45, left_w, 2.3, fill=self.bg_quiet)
        formulas = [
            "y_t = baseline_t + Σ β_i · sat(adstock(x_i,t)) + ε_t",
            "",
            "adstock(x, θ) = x_t + θ·x_{t-1} + θ²·x_{t-2} + …",
            "   θ_i ∈ [0, 0.95]  (geometric decay)",
            "",
            "sat(z, α, γ) = z^α / (z^α + γ^α)",
            "   Hill function, half-max = γ_i",
            "",
            "β_i ~ HalfNormal(0.5) · CPP-normalized",
            "ε_t ~ Normal(0, σ)",
        ]
        self._paragraphs(
            slide, left_x + 0.25, left_y + 0.6, left_w - 0.5, 2.1,
            [(line, {
                "font": self.mono, "size": 10,
                "color": self.deep_100 if line.strip() else self.deep_60,
            }) for line in formulas],
            line_spacing=1.25,
        )

        # LEFT bottom: diagnostics mini
        diag_y = left_y + 3.0
        self._text(
            slide, left_x, diag_y, left_w, 0.25, "ДИАГНОСТИКА",
            font=self.sans, size=9, bold=True, color=self.gold,
        )
        self._hairline(slide, left_x, diag_y + 0.28, 1.0, weight=0.75, color=self.gold)

        diag = [
            ("R²",                f"{self.r_squared:.3f}"),
            ("MAPE",              f"{self.mape_pct:.1f}%"),
            ("R-hat (max)",       f"{self.r_hat_max:.3f}"),
            ("ESS (min)",         f"{self.ess_min:,}".replace(",", " ")),
        ]
        dy = diag_y + 0.4
        for label, val in diag:
            self._text(
                slide, left_x, dy, left_w * 0.55, 0.25, label,
                font=self.sans, size=10, color=self.deep_60,
            )
            self._text(
                slide, left_x + left_w * 0.55, dy, left_w * 0.45, 0.25, val,
                font=self.sans, size=10, bold=True, color=self.deep_100,
                align=PP_ALIGN.RIGHT,
            )
            self._hairline(slide, left_x, dy + 0.27, left_w, weight=0.25)
            dy += 0.3

        # RIGHT: Limitations (tier-1 differentiator)
        right_x = left_x + left_w + 0.5
        right_w = self.w - self.safe - right_x

        self._text(
            slide, right_x, left_y, right_w, 0.25, "ЧТО МОДЕЛЬ НЕ УЧИТЫВАЕТ",
            font=self.sans, size=9, bold=True, color=self.gold,
        )
        self._hairline(slide, right_x, left_y + 0.28, 1.2, weight=0.75, color=self.gold)

        limits = [
            ("Долгосрочные бренд-эффекты (>26 недель).",
             "Модель учитывает краткосрочный и среднесрочный эффект, но не долгосрочное строительство бренда."),
            ("Каннибализация между категориями.",
             f"Если у клиента несколько SKU - модель считает их единым KPI."),
            ("Вариация качества креативов.",
             "Влияние качества роликов на ROI не моделируется - предполагается постоянным."),
            ("Конкурентная медиа-активность.",
             "Доля голоса (SoV) конкурентов в модели отсутствует - оценка справедлива для стабильной категории."),
            ("Макроэкономические шоки.",
             "Экстремальные события (валютные скачки, регуляторные изменения) вне области анализа."),
        ]
        ly = left_y + 0.5
        for lead, body in limits:
            # Lead (bold) on first line
            self._text(
                slide, right_x + 0.2, ly, right_w - 0.2, 0.22, lead,
                font=self.sans, size=11, bold=True, color=self.deep_100,
            )
            # Body (regular) on next line
            self._text(
                slide, right_x + 0.2, ly + 0.27, right_w - 0.2, 0.45, body,
                font=self.sans, size=10, color=self.deep_60, line_spacing=1.3,
            )
            # Bullet dot (gold square, aligned with lead)
            self._rect(slide, right_x, ly + 0.07, 0.08, 0.08, fill=self.deep_60)
            ly += 0.80

        # Bottom note (concise: ≤100 chars fits 1 line at 7pt in 8.3" column)
        self._source(
            slide, 6.87,
            text="Приоры: 12+ FMCG-проектов Aurora (2024-2026) + индустриальные бенчмарки Bayesian MMM.",
        )

        self._footer(slide, 11)

    # ----------------------------------------------------------------
    # SLIDE 11 - SOURCES + MQS
    # ----------------------------------------------------------------

    # C.6.3: s11 sources content now at physical page 13 (divider at 12).
    def s11_sources(self):
        slide = self._blank()
        self._header(slide, slide_num=13)

        self._category(slide, self.safe, 0.60, "ДАННЫЕ")

        self._text(
            slide, self.safe, 0.70, 10.0, 0.7, "Источники и качество",
            font=self.serif, size=32, color=self.deep_100,
        )
        self._hairline(slide, self.safe, 1.50, 1.2, weight=0.75, color=self.gold)

        # MQS big card (left 40%) - spacious layout
        card_x = self.safe
        card_y = 1.85
        card_w = 4.5
        card_h = 3.9
        self._rect(slide, card_x, card_y, card_w, card_h, fill=self.bg_quiet)
        # Top gold stripe
        self._rect(slide, card_x, card_y, card_w, 0.06, fill=self.gold)

        self._text(
            slide, card_x + 0.35, card_y + 0.3, card_w - 0.7, 0.25,
            "MODEL QUALITY SCORE",
            font=self.sans, size=10, bold=True, color=self.gold,
        )

        # The big MQS score + /100 pair - centered vertically between
        # title (top) and status hairline (bottom). Spacing balanced so
        # "70 → /" gap ≈ "/ → 100" gap (visually symmetric pair).
        self._text(
            slide, card_x + 0.45, card_y + 0.30, 2.0, 1.8, f"{self.mqs_score:.0f}",
            font=self.serif, size=120, color=self.deep_100, align=PP_ALIGN.RIGHT,
        )
        # "/ 100" left-aligned, gap to "70" matches gap "/" → "100"
        self._text(
            slide, card_x + 2.55, card_y + 1.10, 1.5, 0.5, "/ 100",
            font=self.serif, size=32, color=self.deep_60,
        )

        # Status - below number with clear gap
        self._hairline(slide, card_x + 0.35, card_y + 2.55, card_w - 0.7, weight=0.5)
        self._text(
            slide, card_x + 0.35, card_y + 2.7, card_w - 0.7, 0.3,
            self.mqs_tier_label,
            font=self.sans, size=12, italic=True, color=self.deep_100,
        )

        # 4 key metrics inside card (2x2)
        km_y = card_y + 3.1
        km_col_w = (card_w - 0.7) / 2
        mets = [
            ("R²",     f"{self.r_squared:.2f}"),
            ("MAPE",   f"{self.mape_pct:.1f}%"),
            ("R-hat",  f"{self.r_hat_max:.3f}"),
            ("ESS",    f"{self.ess_min:,}".replace(",", " ")),
        ]
        for i, (label, val) in enumerate(mets):
            row, col = divmod(i, 2)
            mx = card_x + 0.35 + col * km_col_w
            my = km_y + row * 0.22
            self._text(
                slide, mx, my, km_col_w * 0.45, 0.22, label,
                font=self.sans, size=9, color=self.deep_60,
            )
            self._text(
                slide, mx + km_col_w * 0.45, my, km_col_w * 0.55, 0.22, val,
                font=self.sans, size=9, bold=True, color=self.deep_100,
            )

        # RIGHT: Data overview
        right_x = card_x + card_w + 0.5
        right_w = self.w - self.safe - right_x

        self._text(
            slide, right_x, card_y, right_w, 0.25,
            "ОХВАТ И ПОЛНОТА",
            font=self.sans, size=9, bold=True, color=self.gold,
        )
        self._hairline(slide, right_x, card_y + 0.28, 1.2, weight=0.75, color=self.gold)

        # Stage C.2: de-hardcode data summary. Period + channel count now
        # derived from self. Frequency/completeness/outliers stay as
        # defensive defaults (will be parametrized via meta when pipeline
        # exposes them; for now document canonical RU phrasing).
        active_count = len(self.channels) if self.channels else 0
        data_info = [
            ("Период",              self.data_window_label),
            ("Наблюдений",          f"{active_count * 13}" if active_count else "-"),
            ("Активных каналов",    f"{active_count}" if active_count else "-"),
            ("Частота",             "Еженедельно (Пн-Вс)"),
            ("Полнота",             "100% (0 пропусков)"),
            ("Аномалии",            "обработаны (праздничные недели)"),
        ]
        dy = card_y + 0.55
        for label, val in data_info:
            self._text(
                slide, right_x, dy, right_w * 0.45, 0.3, label,
                font=self.sans, size=10, color=self.deep_60,
            )
            self._text(
                slide, right_x + right_w * 0.45, dy, right_w * 0.55, 0.3, val,
                font=self.sans, size=10, color=self.deep_100,
                align=PP_ALIGN.RIGHT,
            )
            self._hairline(slide, right_x, dy + 0.32, right_w, weight=0.25)
            dy += 0.34

        # Sources list bottom
        src_y = 6.0
        self._text(
            slide, self.safe, src_y, 2.0, 0.2, "PRIMARY",
            font=self.sans, size=8, bold=True, color=self.gold,
        )
        self._hairline(slide, self.safe, src_y + 0.22, 0.8, weight=0.5, color=self.gold)

        primary = [
            f"Mediascope TV {self.data_window_label} (TRP / Reach / CPP по target W25-54)",
            f"{self.sources_client_label} internal sales ledger (weekly, SKU-aggregated)",
        ]
        py = src_y + 0.32
        for i, s in enumerate(primary, start=1):
            self._rich(
                slide, self.safe, py, 6.0, 0.22,
                runs=[
                    (f"{i}.  ", {"font": self.sans, "size": 8, "bold": True, "color": self.gold}),
                    (s, {"font": self.sans, "size": 9, "color": self.deep_100}),
                ],
            )
            py += 0.23

        sec_x = 7.0
        self._text(
            slide, sec_x, src_y, 2.0, 0.2, "SECONDARY",
            font=self.sans, size=8, bold=True, color=self.deep_60,
        )
        self._hairline(slide, sec_x, src_y + 0.22, 0.8, weight=0.5, color=self.deep_60)

        secondary = [
            "Yandex.Metrica + Google Analytics (digital clicks, conversions)",
            "VK Ads + MyTarget (social impressions / clicks)",
            f"{self.sources_client_label} бренд-трекер (quarterly W25 54)",
        ]
        sy = src_y + 0.32
        for i, s in enumerate(secondary, start=1):
            self._rich(
                slide, sec_x, sy, 6.0, 0.22,
                runs=[
                    (f"{i}.  ", {"font": self.sans, "size": 8, "bold": True, "color": self.deep_60}),
                    (s, {"font": self.sans, "size": 9, "color": self.deep_100}),
                ],
            )
            sy += 0.23

        self._footer(slide, 13)

    # ----------------------------------------------------------------
    # SLIDE 12 - COLOPHON (narrative)
    # ----------------------------------------------------------------

    # ----------------------------------------------------------------
    # SLIDE 12 - GLOSSARY (тезаурус терминов)
    # ----------------------------------------------------------------

    # C.6.3: s12 glossary content now at physical page 15 (appendix divider at 14).
    def s12_glossary(self):
        """Glossary / тезаурус: compact 3-column reference for deck terms."""
        slide = self._blank()
        self._header(slide, slide_num=15)

        self._category(slide, self.safe, 0.60, "ПРИЛОЖЕНИЕ А")

        self._text(
            slide, self.safe, 0.80, self.w - 2 * self.safe, 0.70,
            "Глоссарий терминов",
            font=self.serif, size=36, color=self.deep_100, line_spacing=1.0,
        )
        self._lime_under(slide, self.safe, 1.55, 2.5)

        self._text(
            slide, self.safe, 1.68, self.w - 2 * self.safe, 0.3,
            "Краткие определения ключевых терминов, используемых в отчёте",
            font=self.serif, size=14, italic=True, color=self.deep_60,
        )

        # 3-column layout
        col_gap = 0.4
        col_w = (self.w - 2 * self.safe - 2 * col_gap) / 3
        content_y = 2.30
        entry_h = 0.54

        columns = [
            ("МЕТОДОЛОГИЯ MMM", [
                ("MMM", "Marketing Mix Modeling - статистическая декомпозиция вклада каналов в продажи."),
                ("Байесовский вывод", "Вероятностный подход: апостериорные распределения вместо точечных оценок."),
                ("NUTS", "No-U-Turn Sampler - эффективный метод MCMC для многомерных распределений."),
                ("NumPyro / JAX", "Python-стек для байесовских вычислений с компиляцией JIT."),
                ("Априорное / апостериорное", "Исходные предположения → обновлённая оценка после данных."),
                ("Adstock", "Отложенный эффект медиа: часть воздействия переносится на следующие периоды."),
                ("Насыщение", "Убывающая отдача: кривая Хилла, S-образное насыщение эффекта."),
            ]),
            ("КАЧЕСТВО МОДЕЛИ", [
                ("R²", "Доля объяснённой моделью вариации продаж (0 до 1). Целевое > 0.7."),
                ("MAPE", "Средняя абсолютная процентная ошибка прогноза."),
                ("R-hat", "Диагностика сходимости MCMC-цепей; целевое значение ≤ 1.01."),
                ("ESS", "Effective Sample Size - число независимых выборок из апостериорного распределения."),
                ("CI (95%)", "Байесовский интервал правдоподобия - в нём истинное значение лежит с 95% вероятностью."),
                ("MQS", "Model Quality Score - композитный индекс качества Aurora (0-100)."),
                ("Базовый / инкрементальный", "Органические продажи без медиа и продажи, вызванные медиа-инвестициями."),
            ]),
            ("МЕДИА-МЕТРИКИ", [
                ("mROAS", "Marginal ROAS - возврат с последнего вложенного рубля (×-коэффициент)."),
                ("ROI", "Return on Investment - общая возвратность вложений (инкрементальный вклад / расход)."),
                ("TRP / GRP", "Target / Gross Rating Points - охват целевой аудитории в рейтинг-пунктах."),
                ("CPP", "Cost per Point - стоимость одного рейтингового пункта в рублях."),
                ("Охват (Reach)", "Процент целевой аудитории, встретивших рекламу минимум один раз."),
                ("Доля голоса (SoV)", "Доля рекламного голоса бренда относительно конкурентов в категории."),
                ("Рекомендация", "Вердикт по каналу: Увеличить / Держать / Наблюдать / Сократить / Остановить."),
            ]),
        ]

        for i, (header, terms) in enumerate(columns):
            col_x = self.safe + i * (col_w + col_gap)
            # Column header
            self._text(
                slide, col_x, content_y, col_w, 0.22, header,
                font=self.sans, size=9, bold=True, color=self.gold,
            )
            self._hairline(
                slide, col_x, content_y + 0.25, 1.2, weight=0.75, color=self.gold,
            )

            ey = content_y + 0.45
            for term, defn in terms:
                # Term (bold)
                self._text(
                    slide, col_x, ey, col_w, 0.18, term,
                    font=self.sans, size=9, bold=True, color=self.deep_100,
                )
                # Definition (regular, on next line, may wrap to 2 lines)
                self._text(
                    slide, col_x, ey + 0.20, col_w, 0.32, defn,
                    font=self.sans, size=8, color=self.deep_60, line_spacing=1.15,
                )
                ey += entry_h

        self._footer(slide, 15)

    # ----------------------------------------------------------------
    # SLIDE 13 - COLOPHON (closing)
    # ----------------------------------------------------------------

    # C.6.3: s13 colophon content now at physical page 16 (final slide).
    def s13_colophon(self):
        """Closing slide - inspirational brand statement + forward-looking CTA + narrative.
        Flow: statement → CTA (with lime) → narrative → wordmark → copyright.
        No duplication of metrics from other slides."""
        slide = self._blank()
        self._header(slide, slide_num=16)

        # Big closing statement - starts higher (more top breathing), no category tag
        self._text(
            slide, self.safe, 1.30, self.w - 2 * self.safe, 1.1,
            "Решения, основанные на данных.",
            font=self.serif, size=52, italic=True, color=self.deep_100,
            line_spacing=1.0,
        )
        # Muted gold second line (softer than primary gold - less shouty)
        self._text(
            slide, self.safe, 2.10, self.w - 2 * self.safe, 0.9,
            "Не на интуиции.",
            font=self.serif, size=52, italic=True, color=self.gold_muted,
            line_spacing=1.0,
        )

        # Forward-looking CTA block with lime accent (action-first)
        cta_y = 4.00
        self._hairline(slide, self.safe, cta_y, 3.5, weight=0.75, color=self.gold)
        self._text(
            slide, self.safe, cta_y + 0.08, 4.0, 0.2, "ДАЛЬШЕ",
            font=self.sans, size=9, bold=True, color=self.gold,
        )
        self._text(
            slide, self.safe, cta_y + 0.32, self.w - 2 * self.safe, 0.35,
            "Следующая волна анализа - через 90 дней.",
            font=self.serif, size=18, italic=True, color=self.deep_100,
        )
        # Sacred lime underlines CTA (emphasizes action, not statement)
        self._lime_under(slide, self.safe, cta_y + 0.75, 4.5)

        # Narrative paragraph - platform philosophy (positioned AFTER CTA as rationale footer)
        narrative = (
            "Aurora AI превращает медиабюджет из статьи затрат в управляемый инструмент роста. "
            "Байесовский вывод позволяет не просто измерить эффективность каналов, но понять границы "
            "неопределённости - основу доверия к любым модельным решениям. Методология, откалиброванная "
            "под индустриальные стандарты, даёт результаты уровня ведущих консалтинговых групп без "
            "необходимости содержать собственную команду аналитиков. Платформа масштабируется от "
            "ежеквартального отчёта до ежемесячного пульс-мониторинга, от одной SKU до портфеля брендов."
        )
        self._text(
            slide, self.safe, 5.00, self.w - 2 * self.safe, 1.5,
            narrative,
            font=self.serif, size=11, italic=True, color=self.deep_60,
            line_spacing=1.5,
        )

        # Big centered wordmark
        self._wordmark(slide, (self.w / 2) - 0.9, 6.55, size=18, color=self.deep_100)
        # Copyright compact (no "Подготовлено для Client" - client name not repeated on closing)
        self._text(
            slide, self.safe, 6.90, self.w - 2 * self.safe, 0.18,
            "© 2026 Aurora AI.  Не подлежит распространению без письменного согласия",
            font=self.sans, size=7, italic=True, color=self.deep_60,
            align=PP_ALIGN.CENTER,
        )
        # Post-audit: use the shared footer helper (suppress left wordmark to
        # avoid duplicating the hero wordmark in the colophon body).
        self._footer(slide, self.total_slides, show_wordmark=False)

    # ---------- Build ----------

    def build(self):
        # Stage C.6.3 (Option B): 16-slide layout with 4 section dividers.
        # Cover(1) → TOC(2) → Exec Summary block (3,5,9) with Декомпозиция
        # divider at (4) + chart/table/timeline (6,7,8) → SCQAR (9) →
        # Методология divider (10) + content (11) → Данные divider (12) +
        # sources (13) → Приложение divider (14) + glossary (15) +
        # colophon (16). Symmetric tier-1 structure; TOC 5-section honest.
        self.s01_cover()
        self.s03_toc()
        self.s02_at_a_glance()
        self.s05_key_message()
        self.s09_scqar()
        self.s04_section_divider()
        self.s06_action_chart()
        self.s07_action_table()
        self.s08_action_timeline()
        self.s_divider_methodology()
        self.s10_methodology()
        self.s_divider_data()
        self.s11_sources()
        self.s_divider_appendix()
        self.s12_glossary()
        self.s13_colophon()
        return self.prs


# Module-level — no main() entry. Use AuroraPPTXBuilder().build() or aurora_pptx.build_pptx().
