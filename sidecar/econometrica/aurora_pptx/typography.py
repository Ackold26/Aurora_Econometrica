"""
Typography helpers - apply_paragraph_style + action-title helper.

Styles map to TYPOGRAPHY["fontSize"]["pptx"].* keys from tokens.json:
  cover_title / cover_subtitle / section_number / section_name /
  action_title / subtitle / body_km / body_detail / caption / footnote / mono
"""

from __future__ import annotations

from pptx.util import Inches, Pt

from .tokens import COLOR, FONT


STYLE_MAP = {
    "cover_title":    dict(font=FONT.family.serif, size=FONT.size.cover_title,   bold=True,  color=COLOR.brand.deep_100),
    "cover_subtitle": dict(font=FONT.family.sans,  size=FONT.size.cover_subtitle, bold=False, color=COLOR.brand.deep_80),
    "section_number": dict(font=FONT.family.serif, size=FONT.size.section_number, bold=False, color=COLOR.brand.deep_20),
    "section_name":   dict(font=FONT.family.serif, size=FONT.size.section_name,   bold=True,  color=COLOR.brand.deep_100),
    "action_title":   dict(font=FONT.family.serif, size=FONT.size.action_title,   bold=True,  color=COLOR.brand.deep_100),
    "subtitle":       dict(font=FONT.family.sans,  size=FONT.size.subtitle,       bold=False, color=COLOR.brand.deep_60),
    "body_km":        dict(font=FONT.family.sans,  size=FONT.size.body_km,        bold=False, color=COLOR.brand.deep_100),
    "body_detail":    dict(font=FONT.family.sans,  size=FONT.size.body_detail,    bold=False, color=COLOR.brand.deep_100),
    "caption":        dict(font=FONT.family.sans,  size=FONT.size.caption,        bold=False, color=COLOR.brand.deep_60),
    "footnote":       dict(font=FONT.family.sans,  size=FONT.size.footnote,       bold=False, color=COLOR.brand.deep_60),
    "mono":           dict(font=FONT.family.mono,  size=FONT.size.mono,           bold=False, color=COLOR.brand.deep_100),
}


def apply_style(run, style: str) -> None:
    """Apply style preset to a python-pptx text Run."""
    spec = STYLE_MAP.get(style)
    if spec is None:
        raise ValueError(f"Unknown style: {style}. Valid: {list(STYLE_MAP)}")
    run.font.name = spec["font"]
    run.font.size = spec["size"]
    run.font.bold = spec["bold"]
    run.font.color.rgb = spec["color"]


def add_styled_text(slide, left_in, top_in, width_in, height_in, text, *,
                    style: str, align=None, override=None):
    """Add a text box with a style preset applied."""
    tb = slide.shapes.add_textbox(
        Inches(left_in), Inches(top_in), Inches(width_in), Inches(height_in)
    )
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0); tf.margin_right = Inches(0)
    tf.margin_top = Inches(0); tf.margin_bottom = Inches(0)
    p = tf.paragraphs[0]
    if align is not None:
        p.alignment = align
    r = p.add_run()
    r.text = text
    apply_style(r, style)
    if override:
        for k, v in override.items():
            setattr(r.font, k, v)
    return tb
