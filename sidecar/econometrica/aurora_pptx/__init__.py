"""
aurora_pptx — client-ready PPTX deliverable helpers for Aurora AI Econometrica.

Template-equivalent via code (python-pptx limitation: cannot create slide
masters programmatically, so we render each slide from scratch with
centralized style helpers driven by tokens.json).

Primary API:

    from aurora_pptx import build_pptx
    prs = build_pptx(data, lang='ru')
    prs.save(output_path)

Internal structure:
  - tokens        : re-export aurora_tokens with pptx-native types (RGBColor/Pt/Inches)
  - master        : apply_master_elements(slide, ctx) — sacred DNA на каждый слайд
  - typography    : apply_paragraph_style(para, style_name) — font/size/color из tokens
  - i18n          : loader strings_ru.json/strings_en.json + t(key, lang)
  - charts        : make_* helpers for native PPTX chart types
  - layouts       : 10 render_* functions per layout type
  - build         : build_pptx(data, lang) entry point

Template container: aurora_pptx/templates/blank_with_theme.pptx — bundled .pptx
with brand theme XML (colors from tokens.json). Each render_* opens a copy and
adds slides via blank_layout. Theme colors propagate to native PPTX charts.
"""

from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"

TEMPLATE_PATH = Path(__file__).parent / "templates" / "blank_with_theme.pptx"


def build_pptx(data, lang: str = "ru"):
    """Build a full client-ready PPTX deliverable from Econometrica pipeline data.

    Args:
        data: dict with model_data, decompose_data, optimize_data, project_meta
        lang: 'ru' (default) | 'en' (v1.0.12)

    Returns:
        pptx.Presentation instance. Caller does .save(path).

    Stub: M3 Session 3 will implement. Currently raises NotImplementedError.
    """
    raise NotImplementedError(
        "aurora_pptx.build_pptx is a stub — M3 layout implementation in next session"
    )
