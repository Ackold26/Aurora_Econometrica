"""
10 layout render functions — one per slide type from CLIENT_READY_ANATOMY.md §2.

Each function:
  1. Takes (prs, ctx: SlideContext, data: dict, lang: str)
  2. Adds a blank slide to prs
  3. Renders layout-specific content (title, chart, body, table, ...)
  4. Calls master.apply_master_elements(slide, ctx) at end

All 10 stubs in this file — M3 Session 3 will implement bodies. Stubs raise
NotImplementedError with clear message so M4 pptx_export.py refactor surfaces
missing work early.
"""

from __future__ import annotations

from typing import Any

from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from .master import SlideContext, apply_master_elements, add_signature_lime
from .tokens import COLOR, FONT, SIZE
from .typography import add_styled_text, apply_style
from .i18n import t


# Blank layout = index 6 in python-pptx default template
_BLANK_LAYOUT_IDX = 6


def _add_blank(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[_BLANK_LAYOUT_IDX])


def _action_title_block(slide, text: str, *, show_lime: bool = True):
    """Standard action title block at top (0.8"), optional lime underneath."""
    safe = 0.4
    slide_w = 13.333
    left = safe
    top = 0.8
    width = slide_w - 2 * safe
    add_styled_text(slide, left, top, width, 0.8, text, style="action_title")
    if show_lime:
        add_signature_lime(slide, left, top + 0.85, width)


# ---------- Layout 01: Cover ----------

def render_cover(prs: Presentation, ctx: SlideContext, data: dict, lang: str = "ru"):
    ctx.is_cover = True
    slide = _add_blank(prs)
    apply_master_elements(slide, ctx)  # will add big logo top-left since is_cover=True

    # Title (center)
    add_styled_text(
        slide, 1.0, 2.8, 11.333, 1.2,
        data.get("title", t("product.name", lang)),
        style="cover_title", align=PP_ALIGN.CENTER,
    )
    # Subtitle
    subtitle = data.get("subtitle", t("product.subtitle", lang))
    if subtitle:
        add_styled_text(
            slide, 1.0, 4.0, 11.333, 0.6,
            subtitle, style="cover_subtitle", align=PP_ALIGN.CENTER,
        )
    # Date + version
    date_str = ctx.generated_at.isoformat()
    add_styled_text(
        slide, 1.0, 5.5, 11.333, 0.4,
        f"{date_str}  ·  v{ctx.version}",
        style="subtitle", align=PP_ALIGN.CENTER,
    )
    # Confidentiality bottom
    if ctx.confidential:
        add_styled_text(
            slide, 0.4, 7.5 - 0.7, 12.533, 0.3,
            t("cover.confidentiality", lang, client=ctx.client_name),
            style="footnote",
            align=PP_ALIGN.CENTER,
            override={"italic": True},
        )
    return slide


# ---------- Layout 02: TOC ----------

def render_toc(prs: Presentation, ctx: SlideContext, data: dict, lang: str = "ru"):
    slide = _add_blank(prs)
    _action_title_block(slide, t("toc.title", lang), show_lime=False)
    sections = data.get("sections") or t("toc.sections", lang)
    if isinstance(sections, list):
        for i, s in enumerate(sections):
            add_styled_text(
                slide, 1.5, 2.0 + i * 0.5, 10.333, 0.45,
                f"{i+1}. {s}", style="body_km",
            )
    apply_master_elements(slide, ctx)
    return slide


# ---------- Layout 03: Section divider ----------

def render_section_divider(prs: Presentation, ctx: SlideContext, data: dict, lang: str = "ru"):
    slide = _add_blank(prs)
    num = data.get("number", "01")
    name = data.get("name", "Section")
    add_styled_text(slide, 1.0, 1.5, 4.0, 3.0, num, style="section_number")
    add_styled_text(slide, 5.0, 2.8, 7.333, 1.0, name, style="section_name")
    add_signature_lime(slide, 5.0, 3.85, 2.5)
    apply_master_elements(slide, ctx)
    return slide


# ---------- Layout 04: Action title + chart + commentary ----------

def render_action_title_chart(prs: Presentation, ctx: SlideContext, data: dict, lang: str = "ru"):
    """M3 Session 3 implementation pending. Takes data.action_title + data.chart_type + data.commentary."""
    raise NotImplementedError("render_action_title_chart — M3 Session 3")


# ---------- Layout 05: Action title + table ----------

def render_action_title_table(prs: Presentation, ctx: SlideContext, data: dict, lang: str = "ru"):
    raise NotImplementedError("render_action_title_table — M3 Session 3")


# ---------- Layout 06: Action title + full-width visual ----------

def render_action_title_full(prs: Presentation, ctx: SlideContext, data: dict, lang: str = "ru"):
    raise NotImplementedError("render_action_title_full — M3 Session 3")


# ---------- Layout 07: Executive summary (SCR) ----------

def render_executive_summary(prs: Presentation, ctx: SlideContext, data: dict, lang: str = "ru"):
    raise NotImplementedError("render_executive_summary — M3 Session 3")


# ---------- Layout 08: Methodology ----------

def render_methodology(prs: Presentation, ctx: SlideContext, data: dict, lang: str = "ru"):
    raise NotImplementedError("render_methodology — M3 Session 3")


# ---------- Layout 09: Sources + MQS ----------

def render_sources(prs: Presentation, ctx: SlideContext, data: dict, lang: str = "ru"):
    raise NotImplementedError("render_sources — M3 Session 3")


# ---------- Layout 10: Colophon ----------

def render_colophon(prs: Presentation, ctx: SlideContext, data: dict, lang: str = "ru"):
    raise NotImplementedError("render_colophon — M3 Session 3")


# Export registry (for build_pptx dispatch table)
LAYOUTS = {
    "cover": render_cover,
    "toc": render_toc,
    "section_divider": render_section_divider,
    "action_title_chart": render_action_title_chart,
    "action_title_table": render_action_title_table,
    "action_title_full": render_action_title_full,
    "executive_summary": render_executive_summary,
    "methodology": render_methodology,
    "sources": render_sources,
    "colophon": render_colophon,
}
