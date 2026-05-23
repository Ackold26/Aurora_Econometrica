"""
PPTX-native wrapper over aurora_tokens - provides RGBColor / Pt / Inches types.

Import pattern in aurora_pptx modules:

    from .tokens import COLOR, FONT, SIZE, SIG_LIME
    shape.fill.fore_color.rgb = COLOR.brand.deep_100
    run.font.size = FONT.size.action_title
    slide.width = SIZE.safe_area
"""

from __future__ import annotations

from types import SimpleNamespace

from pptx.dml.color import RGBColor
from pptx.util import Emu, Inches, Pt

try:
    # aurora_tokens is generated from Standards/tokens/tokens.json via build.py
    from aurora_tokens import (
        COLORS,
        TYPOGRAPHY,
        SIZING,
        BORDER,
        SIGNATURE_LIME,
        AURORA_DEEP_100,
        AURORA_DEEP_80,
        AURORA_DEEP_60,
        AURORA_GOLD,
        AURORA_BG_WHITE,
        CHANNEL_COLORS,
    )
except ImportError:
    # v2.1.0 (пилот 2026-05-17 audit C-1): nested fallback matching expected
    # access patterns COLORS["brand"]["deep"]["100"] etc. Раньше выбрасывался
    # RuntimeError с devops-сообщением которое попадало в красный banner
    # на frontend Отчёта.
    AURORA_DEEP_100 = '#0A1628'
    AURORA_DEEP_80 = '#1E293B'
    AURORA_DEEP_60 = '#475569'
    AURORA_GOLD = '#C5A46D'
    AURORA_BG_WHITE = '#F7F7F7'
    SIGNATURE_LIME = '#CCFF00'
    COLORS = {
        'brand': {
            'deep':  {'100': '#0A1628', '80': '#1E293B', '60': '#475569', '40': '#94A3B8', '20': '#CBD5E1'},
            'gold':  {'primary': '#C5A46D', 'muted': '#B8975D'},
            'bg':    {'white': '#FFFFFF', 'quiet': '#F7F7F7'},
            'rule':  '#E5E7EB',
            # v2.1.0 (пилот 2026-05-17 audit): builder.py:169 ожидает brand.sig.lime
            # для accent-tag. Без этого ключа PPTX export падал KeyError 'sig'.
            'sig':   {'lime': '#CCFF00'},
        },
        'data': {
            'ocean': '#3B82F6', 'jade': '#22C55E',
            'berry': '#DC2626', 'tangerine': '#F59E0B',
        },
        'semantic': {
            'stop': '#DC2626', 'caution': '#F59E0B', 'go': '#22C55E',
        },
    }
    TYPOGRAPHY = {
        'fontFamily': {'sans': 'Arial', 'serif': 'Georgia', 'mono': 'Consolas'},
        'fontSize': {
            'pptx': {
                'coverTitle': 44, 'coverSubtitle': 22, 'sectionNumber': 28,
                'sectionName': 18, 'actionTitle': 28, 'subtitle': 16,
                'bodyKM': 14, 'bodyDetail': 12, 'caption': 10,
                'footnote': 9, 'mono': 11,
            },
        },
    }
    SIZING = {
        'pptx': {
            'safeArea': 12.333, 'gridGutter': 0.25, 'logoCover': 2.0,
            'logoSmall': 0.6, 'signatureLimeOffset': 6,
        },
    }
    BORDER = {'thin': 0.5, 'medium': 1.0, 'thick': 1.5}
    CHANNEL_COLORS = [
        '#C5A46D', '#3B82F6', '#22C55E', '#DC2626',
        '#F59E0B', '#8B5CF6', '#06B6D4', '#84CC16',
    ]


def _rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color.lstrip("#").upper())


# Brand colors as pptx RGBColor
COLOR = SimpleNamespace(
    brand=SimpleNamespace(
        deep_100=_rgb(COLORS["brand"]["deep"]["100"]),
        deep_80=_rgb(COLORS["brand"]["deep"]["80"]),
        deep_60=_rgb(COLORS["brand"]["deep"]["60"]),
        deep_40=_rgb(COLORS["brand"]["deep"]["40"]),
        deep_20=_rgb(COLORS["brand"]["deep"]["20"]),
        gold=_rgb(COLORS["brand"]["gold"]["primary"]),
        gold_muted=_rgb(COLORS["brand"]["gold"]["muted"]),
        bg_white=_rgb(COLORS["brand"]["bg"]["white"]),
        bg_quiet=_rgb(COLORS["brand"]["bg"]["quiet"]),
        rule=_rgb(COLORS["brand"]["rule"]),
        sig_lime=_rgb(SIGNATURE_LIME),
    ),
    data=SimpleNamespace(
        channel_colors=tuple(_rgb(h) for h in CHANNEL_COLORS),
        ocean=_rgb(COLORS["data"]["ocean"]),
        jade=_rgb(COLORS["data"]["jade"]),
        berry=_rgb(COLORS["data"]["berry"]),
        tangerine=_rgb(COLORS["data"]["tangerine"]),
    ),
    semantic=SimpleNamespace(
        stop=_rgb(COLORS["semantic"]["stop"]),
        caution=_rgb(COLORS["semantic"]["caution"]),
        go=_rgb(COLORS["semantic"]["go"]),
    ),
)

# Typography - wrapped in pptx Pt
_pptx_sizes = TYPOGRAPHY["fontSize"]["pptx"]
FONT = SimpleNamespace(
    family=SimpleNamespace(
        serif=TYPOGRAPHY["fontFamily"]["serif"],     # "Georgia"
        sans=TYPOGRAPHY["fontFamily"]["sans"],        # "Arial"
        mono=TYPOGRAPHY["fontFamily"]["mono"],        # "Consolas"
    ),
    size=SimpleNamespace(
        cover_title=Pt(_pptx_sizes["coverTitle"]),
        cover_subtitle=Pt(_pptx_sizes["coverSubtitle"]),
        section_number=Pt(_pptx_sizes["sectionNumber"]),
        section_name=Pt(_pptx_sizes["sectionName"]),
        action_title=Pt(_pptx_sizes["actionTitle"]),
        subtitle=Pt(_pptx_sizes["subtitle"]),
        body_km=Pt(_pptx_sizes["bodyKM"]),
        body_detail=Pt(_pptx_sizes["bodyDetail"]),
        caption=Pt(_pptx_sizes["caption"]),
        footnote=Pt(_pptx_sizes["footnote"]),
        mono=Pt(_pptx_sizes["mono"]),
    ),
)

# Sizing - pptx native units
_pptx_sizing = SIZING["pptx"]
SIZE = SimpleNamespace(
    slide_w=Inches(13.333),
    slide_h=Inches(7.5),
    safe_area=Inches(_pptx_sizing["safeArea"]),
    grid_gutter=Inches(_pptx_sizing["gridGutter"]),
    logo_cover=Inches(_pptx_sizing["logoCover"]),
    logo_small=Inches(_pptx_sizing["logoSmall"]),
    signature_lime_width=Pt(2),
    signature_lime_offset=Pt(_pptx_sizing["signatureLimeOffset"]),
)

# Convenience direct exports
SIG_LIME = COLOR.brand.sig_lime
