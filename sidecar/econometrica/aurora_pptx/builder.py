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

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

try:
    from econometrica.aurora_tokens import COLORS, TYPOGRAPHY, SIZING
except ImportError as e:
    raise RuntimeError(
        "aurora_tokens not generated. Run: python Standards/tokens/build.py --target python"
    ) from e


def hex_to_rgb(h):
    return RGBColor.from_string(h.lstrip("#").upper())


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
        self.section_names = meta.get("section_names", [
            "Executive summary",
            "Методология",
            "Данные и качество",
            "Модель и спецификация",
            "Декомпозиция вкладов",
            "Оптимизация бюджета",
            "Рекомендации",
            "Приложение и источники",
        ])
        self.total_sections = len(self.section_names)
        self.total_slides = meta.get("total_slides", 13)
        self.toc_page_refs = meta.get("toc_page_refs", [4, 5, 6, 7, 8, 9, 10, 11])
        # Header center label (shown on every content slide)
        self.header_project_label = meta.get(
            "header_project_label",
            f"{self.client.upper()} . MMM REPORT . {self.period_label}",
        )
        # Copyright footer on cover
        self.copyright_line = meta.get(
            "copyright_line",
            f"© 2026 Aurora AI  .  Prepared exclusively for {self.client}  .  Not for redistribution",
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

    def _header(self, slide, *, section_idx, section_label,
                include_confidential=True, include_project=True):
        """Slim running header: closer to top edge (y=0.25) to reclaim content space."""
        y = 0.25  # compact safe_top zone
        # Left: section tag like "03 / 08 . Methodology"
        self._text(
            slide, self.safe, y, 5.0, 0.2,
            f"{section_idx:02d} / {self.total_sections:02d} . {section_label.upper()}",
            font=self.sans, size=8, bold=True, color=self.deep_100, align=PP_ALIGN.LEFT,
        )
        # Center: project identifier
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

    def _footer(self, slide, page_num, *, show_page=True):
        """Footer: hairline at y=7.05 (fixed safe_bottom boundary).
        Elements (wordmark + page num) visually centered between hairline and slide bottom (7.50).
        Midpoint = 7.275 → element_y = 7.20."""
        self._hairline(slide, self.safe, 7.05, self.w - 2 * self.safe, weight=0.25)
        element_y = 7.20  # visual center of (7.05, 7.50) zone
        # Left: mini wordmark
        self._wordmark(slide, self.safe, element_y, size=8, color=self.deep_60)
        # Center: page num в формате "N\Total"
        if show_page:
            self._text(
                slide, 0, element_y, self.w, 0.18,
                f"{page_num}\\{self.total_slides}",
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

    def _action_title(self, slide, text, *, show_lime=True, y=1.0, height=0.95):
        left = self.safe
        width = self.w - 2 * self.safe
        self._text(
            slide, left, y, width, height,
            text, font=self.serif, size=22, bold=True,
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

    def _build_action_table_rows(self, channels):
        """Format merged channels list into the (name, budget, contrib, mROAS,
        share_pct, verdict, footnote) tuples consumed by s07 action table.
        Auto-generates footnote superscripts only for Reduce/Cut verdicts,
        keyed by order (max 3 footnotes to fit bottom-block layout).
        """
        total_contrib = sum(float(c.get("contribution") or 0) for c in channels) or 1.0
        # Assign footnote numbers to the first 3 flagged channels (Reduce/Cut)
        flagged = [c for c in channels if c.get("verdict") in ("Reduce", "Cut")][:3]
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

            rows.append((name, budget_str, contrib_str, roi_str, share_str, verdict, footnote))
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
            "MARKETING MIX MODEL . QUARTERLY REPORT",
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
            f"и рекомендации по оптимизации на {self.forecast_period_label}",
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
            ("ВЕРСИЯ",            f"v{self.version}"),
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
        self._header(slide, section_idx=1, section_label="Executive summary")

        self._category(slide, self.safe, 0.60, "ОТЧЁТ ЗА 60 СЕКУНД")
        self._text(
            slide, self.safe, 0.70, 10.0, 0.7,
            "Пять находок",
            font=self.serif, size=32, color=self.deep_100,
        )
        self._hairline(slide, self.safe, 1.50, 1.2, weight=0.75, color=self.gold)

        findings = [
            ("01", "TV обеспечивает 42% инкрементальных продаж при 28% доли бюджета",
             "ROI 1.8× выше среднего по каналам"),
            ("02", "Saturation на TV начинается с 80 TRP/нед",
             "Marginal ROI падает на 22% относительно Q4 2025"),
            ("03", "Digital video - самый эффективный канал с mROAS 1.9×",
             "Текущий бюджет на нём меньше 15%"),
            ("04", "Baseline растёт на 8% YoY - кампании работают на долгосроке",
             "Brand building дивиденды видны"),
            ("05", "Recommendation: reallocate 25 млн из TV в digital video",
             "Ожидаемый прирост ROAS: +12 пп к Q3 2026"),
        ]
        y = 1.80
        for i, (num, finding, support) in enumerate(findings):
            # Number
            self._text(
                slide, self.safe, y, 0.7, 0.5, num,
                font=self.serif, size=28, color=self.gold,
            )
            # Finding in Georgia bold
            self._text(
                slide, self.safe + 0.9, y, 9.0, 0.45, finding,
                font=self.serif, size=15, bold=True, color=self.deep_100,
            )
            # Support text
            self._text(
                slide, self.safe + 0.9, y + 0.42, 9.0, 0.3, support,
                font=self.sans, size=10, italic=True, color=self.deep_60,
            )
            # Hairline between items only (not after last - footer has its own rule)
            if i < len(findings) - 1:
                self._hairline(slide, self.safe, y + 0.8, self.w - 2 * self.safe, weight=0.25)
            y += 0.92

        self._footer(slide, 2)

    # ----------------------------------------------------------------
    # SLIDE 03 - TOC
    # ----------------------------------------------------------------

    def s03_toc(self):
        slide = self._blank()
        self._header(slide, section_idx=1, section_label="Executive summary")

        self._category(slide, self.safe, 0.60, "AGENDA")
        self._text(
            slide, self.safe, 0.70, 10.0, 0.7, "Содержание отчёта",
            font=self.serif, size=32, color=self.deep_100,
        )
        self._hairline(slide, self.safe, 1.50, 1.2, weight=0.75, color=self.gold)

        # Main list (8 sections)
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
            ("Страниц",          "12"),
            ("Разделов",         "8"),
            ("Таблиц",           "3"),
            ("Графиков",         "4"),
            ("Слов",             "~2 800"),
            ("MQS модели",       "87 / 100"),
            ("Данные",           "W01-W13"),
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

        self._footer(slide, 3)

    # ----------------------------------------------------------------
    # SLIDE 04 - SECTION DIVIDER WITH TAKEAWAY
    # ----------------------------------------------------------------

    def s04_section_divider(self):
        slide = self._blank()
        self._header(
            slide, section_idx=5, section_label="Декомпозиция вкладов",
            include_project=True, include_confidential=True,
        )

        # Big number
        self._text(
            slide, self.safe, 1.3, 4.5, 3.5,
            "05",
            font=self.serif, size=220, color=self.deep_20,
        )

        # Section label
        self._text(
            slide, self.safe + 4.3, 2.1, 8.0, 0.3, "РАЗДЕЛ 05 / 08",
            font=self.sans, size=9, bold=True, color=self.gold,
        )
        # Section name
        self._text(
            slide, self.safe + 4.3, 2.5, 8.0, 0.8,
            "Декомпозиция вкладов",
            font=self.serif, size=40, color=self.deep_100,
        )
        self._lime_under(slide, self.safe + 4.3, 3.35, 2.5)

        # KEY TAKEAWAY - the value-add of tier-1 section divider
        self._text(
            slide, self.safe + 4.3, 3.7, 8.0, 0.3, "ОСНОВНОЙ ВЫВОД",
            font=self.sans, size=8, bold=True, color=self.gold,
        )
        self._text(
            slide, self.safe + 4.3, 4.05, 8.0, 1.3,
            "TV генерирует 42% продаж при 28% бюджета - основная точка оптимизации портфеля",
            font=self.serif, size=20, italic=True, color=self.deep_80,
            line_spacing=1.3,
        )

        # In this section
        self._text(
            slide, self.safe + 4.3, 5.6, 8.0, 0.25, "В ЭТОМ РАЗДЕЛЕ",
            font=self.sans, size=8, bold=True, color=self.deep_60,
        )
        topics = [
            "Методология декомпозиции и precautionary notes",
            "Индивидуальные вклады каналов и ROI ранжирование",
            "Paneldata: декомпозиция недельной динамики",
        ]
        ty = 5.9
        for topic in topics:
            self._text(
                slide, self.safe + 4.3, ty, 8.0, 0.3, f"·  {topic}",
                font=self.sans, size=11, color=self.deep_100,
            )
            ty += 0.28

        # Progress bar - positioned above footer with clearance
        self._section_progress(slide, self.safe, 6.3, current=5)

        self._footer(slide, 4)

    # ----------------------------------------------------------------
    # SLIDE 05 - KEY MESSAGE (Big Number + Pull Quote)
    # ----------------------------------------------------------------

    def s05_key_message(self):
        slide = self._blank()
        self._header(slide, section_idx=1, section_label="Executive summary")

        self._category(slide, self.safe, 0.60, "КЛЮЧЕВОЙ ВЫВОД")

        self._action_title(
            slide,
            "TV остаётся основным драйвером, но эффективность достигла локального максимума",
            show_lime=True, y=0.80, height=0.90,
        )

        # Left: big number
        self._big_number(
            slide, self.safe, 3.3,
            number="42%",
            label="Доля TV в инкрементальных продажах Q1",
            support="При 28% доли бюджета. ROI 1.8× выше среднего.",
            size=140,
        )

        # Right: pull quote
        quote_x = 6.8
        quote_y = 3.1
        quote_w = self.w - self.safe - quote_x
        self._pull_quote(
            slide, quote_x, quote_y, quote_w, 2.6,
            (
                "Каждый рубль в TV возвращает в 1.8 раза больше, "
                "чем среднее по каналам. Однако начиная с 80 TRP/нед "
                "маржинальный возврат падает - сигнал к reallocate в digital."
            ),
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
                f"Источник: Bayesian MMM v{self.version}; данные {self.sources_client_label} {self.data_window_label}; "
                "модель откалибрована под FMCG-бенчмарки."
            ),
        )

        self._footer(slide, 5)

    # ----------------------------------------------------------------
    # SLIDE 06 - ACTION + CHART + COMMENTARY (with annotation)
    # ----------------------------------------------------------------

    def s06_action_chart(self):
        slide = self._blank()
        self._header(slide, section_idx=5, section_label="Декомпозиция вкладов")

        self._category(slide, self.safe, 0.60, "ROI ПО КАНАЛАМ")

        # Title — slot-fill from facts when present, else Kagocel pilot line
        if self.facts and self.channels:
            by_mroas = sorted(self.channels, key=lambda c: float(c.get("mroas") or 0), reverse=True)
            top_names = [c.get("name") for c in by_mroas[:2] if c.get("name")]
            leader = self.facts.get("leader_channel")
            if len(top_names) >= 2 and leader and leader not in top_names:
                action_title = f"{top_names[0]} и {top_names[1]} опережают {leader} по mROAS - они должны получить приоритет"
            elif len(top_names) >= 2:
                action_title = f"{top_names[0]} и {top_names[1]} делят лидерство по mROAS - портфель под пересмотром"
            elif top_names:
                action_title = f"{top_names[0]} - лидер по mROAS, портфель требует перебалансировки"
            else:
                action_title = "Портфель требует перебалансировки по mROAS"
        else:
            action_title = "Digital video и Search опережают TV по mROAS - они должны получить приоритет"

        self._action_title(
            slide,
            action_title,
            show_lime=True, y=0.80, height=0.80,
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
            "1.0× = breakeven  .  выше = прибыльно",
            font=self.sans, size=7, italic=True, color=self.deep_60,
            align=PP_ALIGN.RIGHT,
        )

        # Source at bottom (unified position max low to footer hairline)
        self._source(
            slide, 6.87,
            text=f"Источник: MMM Aurora AI v{self.version}, posterior means, 95% CI omitted for clarity",
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

        # Commentary — slot-fill from facts+channels when present, else Kagocel
        if self.channels and self.facts:
            by_mroas = sorted(self.channels, key=lambda c: float(c.get("mroas") or 0), reverse=True)
            hero = by_mroas[0] if by_mroas else {}
            second = by_mroas[1] if len(by_mroas) > 1 else {}
            leader = self.facts.get("leader_channel")
            hero_name = hero.get("name") or "Лидер"
            hero_m = float(hero.get("mroas") or 0)
            second_name = second.get("name") or ""
            second_m = float(second.get("mroas") or 0)
            # Underperformers = channels with mROAS < 1.0 (below breakeven)
            underperf = [c.get("name") for c in self.channels if float(c.get("mroas") or 0) < 1.0]
            commentary: list[tuple[str, str]] = []
            # Block 1 — hero vs leader
            if leader and hero_name and leader != hero_name:
                commentary.append((
                    f"{hero_name} обогнал {leader}.",
                    f" mROAS {hero_m:.1f}× означает, что каждый дополнительный рубль в {hero_name.lower()} возвращает в {hero_m:.1f} раза больше. Явный потенциал scale-up.",
                ))
            elif hero_name:
                commentary.append((
                    f"{hero_name} - лидер по mROAS.",
                    f" mROAS {hero_m:.1f}×. Бюджет следует наращивать до признаков saturation.",
                ))
            # Block 2 — stable second
            if second_name and second_m >= 1.0:
                commentary.append((
                    f"{second_name} устойчиво эффективен.",
                    f" mROAS {second_m:.1f}× при текущих расходах - низкая волатильность, потенциал удержания бюджета.",
                ))
            # Block 3 — underperformers (breakeven)
            if underperf:
                names_str = " и ".join(underperf[:2]) if underperf else ""
                if names_str:
                    commentary.append((
                        f"{names_str} под угрозой.",
                        f" mROAS ниже breakeven. Рекомендуется reallocate их бюджеты в топ-2 канала.",
                    ))
        else:
            commentary = [
                ("Digital video обогнал TV.",
                 " mROAS 1.9× означает, что каждый дополнительный рубль в digital video возвращает в 1.9 раза больше. Сейчас канал получает менее 15% бюджета - явный потенциал scale-up."),
                ("Search устойчиво эффективен.",
                 " mROAS 1.7× при текущих расходах. Менее волатилен, чем social, и не подвержен saturation в обозримой перспективе."),
                ("Print и Radio под угрозой.",
                 " mROAS 0.7× и 0.75× - оба ниже breakeven. Рекомендуется reallocate их бюджеты в топ-2 канала."),
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

        self._footer(slide, 6)

    # ----------------------------------------------------------------
    # SLIDE 07 - ACTION + TABLE (with conditional formatting & footnotes)
    # ----------------------------------------------------------------

    def s07_action_table(self):
        slide = self._blank()
        self._header(slide, section_idx=5, section_label="Декомпозиция вкладов")

        self._category(slide, self.safe, 0.60, "ПОРТФЕЛЬ КАНАЛОВ")

        self._action_title(
            slide,
            "Пять каналов генерируют 87% продаж - остальные рекомендованы к консолидации",
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
        row_y = table_y + 0.65
        for row in rows:
            channel, budget, contrib, roi, share, verdict, footnote = row
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
            # mROAS (with footnote if present)
            if footnote:
                self._rich(
                    slide, x, row_y, col_widths[3] - 0.1, 0.3,
                    runs=[
                        (roi, {"font": self.sans, "size": 11, "color": self.deep_100}),
                        (footnote, {"font": self.sans, "size": 7, "color": self.gold}),
                    ],
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
            self._text(
                slide, x + 0.05, row_y, col_widths[5] - 0.1, 0.3, verdict,
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

        # Unified bottom block: ПРИМЕЧАНИЯ label + 3 footnotes + source,
        # packed tight upward from footer hairline (6.85) with 0.03 clearance
        footnotes = [
            ("1", "TV: mROAS считается при текущих 85 TRP/нед; выше 100 TRP/нед ROI падает ниже 1.2×."),
            ("2", "Social volatile - mROAS 1.3× median, но CI 0.8 1.8× (высокая неопределённость)."),
            ("3", "Print: ниже breakeven; рекомендация основана на 3-квартальном тренде."),
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
            text=f"Источник: Bayesian MMM Aurora AI v{self.version}; CI 95%, posterior means reported."
        )

        self._footer(slide, 7)

    # ----------------------------------------------------------------
    # SLIDE 08 - ACTION + FULL TIMELINE (with annotations)
    # ----------------------------------------------------------------

    def s08_action_timeline(self):
        slide = self._blank()
        self._header(slide, section_idx=5, section_label="Декомпозиция вкладов")

        self._category(slide, self.safe, 0.60, "ДИНАМИКА")

        self._action_title(
            slide,
            "TV-всплески W06 и W11 выделяются на устойчивом baseline +8% YoY",
            show_lime=True, y=0.80, height=0.80,
        )

        chart_x = self.safe
        chart_y = 1.95
        chart_w = self.w - 2 * self.safe
        chart_h = 3.7

        self._text(
            slide, chart_x, chart_y, chart_w, 0.25,
            "ПРОДАЖИ ПО НЕДЕЛЯМ / ₽ МЛН . STACKED AREA CHART",
            font=self.sans, size=9, bold=True, color=self.deep_80,
        )
        self._text(
            slide, chart_x, chart_y + 0.27, chart_w, 0.22,
            f"Декомпозиция: baseline + вклад каждого канала, {self.data_window_label}",
            font=self.sans, size=9, italic=True, color=self.deep_60,
        )
        # Hairline removed per brand rule - minimize horizontal lines

        # Area chart (real stacked rects per week)
        weeks = 13
        area_x = chart_x + 0.7  # leave space for y-axis labels
        area_y = chart_y + 0.8
        area_w = chart_w - 2.8  # leave space for legend on right
        area_h = 2.6

        # Band heights scaled so that sum × max seasonal multiplier ≤ area_h (2.6")
        # TV mod 1.6 at peaks; others ≤ 1.1. Sum at peak W06: 0.85+0.55·1.6+0.35+0.17+0.12+0.07 ≈ 2.44 < 2.6 ✓
        bands = [
            ("Baseline",      self.deep_40, 0.85),
            ("TV",            self.gold,    0.55),
            ("Digital video", self.deep_80, 0.35),
            ("Search",        self.deep_60, 0.17),
            ("OOH",           self.deep_20, 0.12),
            ("Social",        self.deep_20, 0.07),
        ]
        seg_w = area_w / weeks

        # Draw stacked with seasonal modulation
        for w_idx in range(weeks):
            week_x = area_x + w_idx * seg_w
            # Flight multiplier: spike on W06 and W11 (TV campaign peaks)
            base_mod = 0.9 + 0.15 * math.sin(w_idx / 13 * 2 * math.pi)
            if w_idx in (5, 10):  # W06, W11 - flights
                tv_mod = 1.6
            else:
                tv_mod = 0.85 if w_idx in (4, 6, 9, 11) else 0.7

            y_top = area_y + area_h
            for name, col, base_h in bands:
                if name == "TV":
                    h_band = base_h * tv_mod
                elif name == "Baseline":
                    h_band = base_h * base_mod
                else:
                    h_band = base_h * (0.95 + 0.1 * math.sin(w_idx / 5))
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

        # Annotations - labels above chart, no arrows (avoid line clutter on chart)
        w06_x = area_x + 5 * seg_w + seg_w / 2
        ann_y_top = area_y - 0.3
        self._text(
            slide, w06_x - 0.9, ann_y_top, 1.8, 0.2,
            "TV FLIGHT . 95 TRP/нед",
            font=self.sans, size=7, bold=True, color=self.gold, align=PP_ALIGN.CENTER,
        )
        # Small gold tick marker на оси X под label (не arrow, а marker)
        self._vline(
            slide, w06_x, area_y, 0.08, weight=1.5, color=self.gold
        )

        w11_x = area_x + 10 * seg_w + seg_w / 2
        self._text(
            slide, w11_x - 0.9, ann_y_top, 1.8, 0.2,
            "HOLIDAY PUSH . DIGITAL",
            font=self.sans, size=7, bold=True, color=self.gold, align=PP_ALIGN.CENTER,
        )
        self._vline(
            slide, w11_x, area_y, 0.08, weight=1.5, color=self.gold
        )

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
            text=f"Источник: {self.sources_client_label} sales ledger {self.data_window_label}; декомпозиция Bayesian MMM v{self.version}",
        )

        self._footer(slide, 8)

    # ----------------------------------------------------------------
    # SLIDE 09 - EXECUTIVE SUMMARY (SCQAR)
    # ----------------------------------------------------------------

    def s09_scqar(self):
        slide = self._blank()
        self._header(slide, section_idx=1, section_label="Executive summary")

        self._category(slide, self.safe, 0.60, "РЕКОМЕНДАЦИЯ")

        self._action_title(
            slide,
            "Aurora рекомендует сократить TV до 60 TRP/нед и удвоить Digital Video",
            show_lime=True, y=0.80, height=0.85,
        )

        # SCQAR blocks - compressed to fit under footer zone (ends ~6.5)
        blocks = [
            {
                "label":  "SITUATION",
                "height": 0.6,
                "body":   f"{self.client} размещает 286 млн ₽ в квартал через 5 активных каналов. Weighted ROI 1.5×, MQS модели {self.mqs_score:.0f}/100.",
            },
            {
                "label":  "COMPLICATION",
                "height": 0.8,
                "body":   "TV достиг saturation: выше 80 TRP/нед marginal ROI падает на 22% YoY. Digital video недоинвестирован (<15% бюджета при mROAS 1.9×). Портфель не оптимизирован.",
            },
            {
                "label":  "QUESTION",
                "height": 0.55,
                "body":   f"Как перераспределить бюджет {self.forecast_period_label}, чтобы поднять ROAS не снижая awareness?",
                "accent": True,
            },
            {
                "label":  "ANSWER",
                "height": 0.6,
                "body":   "Сократить TV с 120 до 90 млн ₽/квартал, увеличить Digital video с 65 до 100 млн, сохранить Search/OOH, остановить Print и Radio.",
            },
            {
                "label":  "RECOMMENDATION",
                "height": 2.0,
                "body":   None,
            },
        ]

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
            # Body
            if b["body"]:
                self._text(
                    slide, self.safe + 2.3, y, 7.5, b["height"] - 0.1,
                    b["body"],
                    font=self.sans, size=12,
                    italic=accent,
                    color=self.deep_100,
                    line_spacing=1.35,
                )
            else:
                # Recommendation - 3 actions
                actions = [
                    ("01",
                     "Перебалансировать бюджет.",
                     " 25 млн ₽ из TV в Digital video. Saving при сохранении incremental sales (adstock компенсирует)."),
                    ("02",
                     "Weekly bursts вместо continuity.",
                     " TV flights 60 TRP × 3 недели + паузы. 18% экономии, awareness устойчив."),
                    ("03",
                     "Targeted retargeting W25 54 через CTV/OLV.",
                     " Segment с prior ROI 2.1×; сейчас недоинвестирован. Потенциал +12 млн ₽ incremental sales."),
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
        self._text(
            slide, impact_x, impact_y + 0.35, 2.5, 0.7, "+12 пп",
            font=self.serif, size=42, color=self.deep_100,
        )
        self._text(
            slide, impact_x, impact_y + 1.1, 2.5, 0.22, "ROAS к Q3 2026",
            font=self.sans, size=10, italic=True, color=self.deep_60,
        )

        self._footer(slide, 9)

    # ----------------------------------------------------------------
    # SLIDE 10 - METHODOLOGY + LIMITATIONS
    # ----------------------------------------------------------------

    def s10_methodology(self):
        slide = self._blank()
        self._header(slide, section_idx=2, section_label="Методология")

        self._category(slide, self.safe, 0.60, "ПОДХОД")

        self._action_title(
            slide,
            "Bayesian MMM с адstock + saturation - NUTS NumPyro, 4 chains × 2 000 iter",
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
             "Модель captures short-to-medium term, но не long-term brand building."),
            ("Cross-category cannibalization.",
             f"Если {self.client} имеет несколько SKU - модель считает их единым KPI."),
            ("Creative quality variation.",
             "Влияние качества роликов на ROI не моделируется - predполагается constant."),
            ("Competitor media pressure.",
             "Share of Voice competitors в модели отсутствует - оценка для стабильной категории."),
            ("Macroeconomic shocks.",
             "Экстремальные события (валютные скачки, регуляторные) вне scope."),
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
            text="Приоры: Robyn, LightweightMMM + 12 FMCG-проектов Aurora (2024-2026).",
        )

        self._footer(slide, 10)

    # ----------------------------------------------------------------
    # SLIDE 11 - SOURCES + MQS
    # ----------------------------------------------------------------

    def s11_sources(self):
        slide = self._blank()
        self._header(slide, section_idx=3, section_label="Данные и качество")

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

        # The big MQS score + /100 pair - centered horizontally in card
        # score box width 2.0 (fits 120pt 2-3 digit glyphs without wrap)
        self._text(
            slide, card_x + 0.95, card_y + 0.50, 2.0, 1.8, f"{self.mqs_score:.0f}",
            font=self.serif, size=120, color=self.deep_100,
        )
        # "/100" baseline-aligned to right of 87
        self._text(
            slide, card_x + 2.70, card_y + 1.35, 1.2, 0.5, "/ 100",
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

        data_info = [
            ("Период",              "2026 W01 - W13"),
            ("Наблюдений",          "91 week-channel"),
            ("Активных каналов",    "5 + 2 legacy"),
            ("Частота",             "Weekly (Пн Вс)"),
            ("Полнота",             "100% (0 пропусков)"),
            ("Outliers",            "2 treated (W12 holiday)"),
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

        self._footer(slide, 11)

    # ----------------------------------------------------------------
    # SLIDE 12 - COLOPHON (narrative)
    # ----------------------------------------------------------------

    # ----------------------------------------------------------------
    # SLIDE 12 - GLOSSARY (тезаурус терминов)
    # ----------------------------------------------------------------

    def s12_glossary(self):
        """Glossary / тезаурус: compact 3-column reference for deck terms."""
        slide = self._blank()
        self._header(slide, section_idx=8, section_label="Приложение и источники")

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
                ("Bayesian inference", "Вероятностный подход: posterior distributions вместо точечных оценок."),
                ("NUTS", "No-U-Turn Sampler - эффективный MCMC для многомерных posteriors."),
                ("NumPyro / JAX", "Python-стек Bayesian computing с compiled-speed acceleration."),
                ("Prior / Posterior", "Априорные предположения → обновлённая оценка после данных."),
                ("Adstock", "Carryover-эффект медиа: часть воздействия переносится на следующие периоды."),
                ("Saturation", "Diminishing returns: кривая Hill-функции, S-образное насыщение эффекта."),
            ]),
            ("КАЧЕСТВО МОДЕЛИ", [
                ("R²", "Доля объяснённой моделью вариации продаж (0 до 1). Целевое > 0.7."),
                ("MAPE", "Mean Absolute Percentage Error - средняя процентная ошибка прогноза."),
                ("R-hat", "Диагностика сходимости MCMC-цепей; целевое значение ≤ 1.01."),
                ("ESS", "Effective Sample Size - число независимых samples из posterior."),
                ("CI (95%)", "Credible Interval - диапазон, содержащий истинное значение с 95% вероятностью."),
                ("MQS", "Model Quality Score - composite индекс качества Aurora (0-100)."),
                ("Baseline / Incremental", "Органические продажи без медиа vs продажи, вызванные медиа-инвестициями."),
            ]),
            ("МЕДИА-МЕТРИКИ", [
                ("mROAS", "Marginal ROAS - возврат с последнего вложенного рубля (×-коэффициент)."),
                ("ROI", "Return on Investment - общая возвратность вложений (incremental / spend)."),
                ("TRP / GRP", "Target / Gross Rating Points - охват целевой аудитории в рейтинг-пунктах."),
                ("CPP", "Cost per Point - стоимость одного рейтингового пункта в рублях."),
                ("Reach", "Охват: % целевой аудитории, встретивших рекламу минимум один раз."),
                ("Share of Voice", "Доля рекламного голоса бренда относительно конкурентов в категории."),
                ("Verdict", "Рекомендация по каналу: Scale (увеличить) / Hold / Watch / Cut (остановить)."),
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

        self._footer(slide, 12)

    # ----------------------------------------------------------------
    # SLIDE 13 - COLOPHON (closing)
    # ----------------------------------------------------------------

    def s13_colophon(self):
        """Closing slide - inspirational brand statement + forward-looking CTA + narrative.
        Flow: statement → CTA (with lime) → narrative → wordmark → copyright.
        No duplication of metrics from other slides."""
        slide = self._blank()
        self._header(slide, section_idx=8, section_label="Приложение и источники")

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
            "Aurora AI Econometrica превращает медиабюджет из статьи затрат в управляемый инструмент роста. "
            "Bayesian inference позволяет не просто измерить эффективность каналов, но понять границы "
            "неопределённости - основу доверия к любым модельным решениям. Методология, откалиброванная "
            "под industry-стандарты, даёт результаты уровня tier-1 консалтинговых групп без необходимости "
            "содержать собственную data science команду. Платформа масштабируется от quarterly report до "
            "ежемесячного pulse-tracking, от одной SKU до портфеля брендов."
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
        # Footer hairline + page num (centered between hairline 7.05 and bottom 7.50)
        self._hairline(slide, self.safe, 7.05, self.w - 2 * self.safe, weight=0.25)
        self._text(
            slide, 0, 7.20, self.w, 0.18,
            f"{self.total_slides}\\{self.total_slides}",
            font=self.sans, size=9, color=self.deep_60,
            align=PP_ALIGN.CENTER,
        )

    # ---------- Build ----------

    def build(self):
        self.s01_cover()
        self.s02_at_a_glance()
        self.s03_toc()
        self.s04_section_divider()
        self.s05_key_message()
        self.s06_action_chart()
        self.s07_action_table()
        self.s08_action_timeline()
        self.s09_scqar()
        self.s10_methodology()
        self.s11_sources()
        self.s12_glossary()
        self.s13_colophon()
        return self.prs


# Module-level — no main() entry. Use AuroraPPTXBuilder().build() or aurora_pptx.build_pptx().
