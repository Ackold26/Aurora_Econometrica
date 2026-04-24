"""
aurora_html.sections — 14 section renderers.

Each function consumes narrative_adapter facts and returns HTML fragment.
Aligned with PPTX S7 anatomy: section numbers match PPTX slide numbers
(s01→cover, s02→summary, ..., s13→glossary, s14→closing).

Full implementation in M2.
"""
from __future__ import annotations

from typing import Any


def render_cover(data: dict) -> str:
    """Section 1: Hero Cover. Client + period + version + gold vertical rule."""
    return ""  # M2


def render_executive_summary(data: dict) -> str:
    """Section 2: Executive Summary (SCQAR 5 blocks)."""
    return ""  # M2


def render_at_a_glance(data: dict) -> str:
    """Section 3: At-a-Glance 5 key findings."""
    return ""  # M2


def render_section_divider(data: dict) -> str:
    """Section 4: Section divider with big number + takeaway."""
    return ""  # M2


def render_key_message(data: dict) -> str:
    """Section 5: Key message (animated big number + pull quote)."""
    return ""  # M2


def render_mroas(data: dict) -> str:
    """Section 6: mROAS chart (hero bar + commentary)."""
    return ""  # M2


def render_share(data: dict) -> str:
    """Section 7: Share vs Effect (side-by-side bars)."""
    return ""  # M2


def render_action_table(data: dict) -> str:
    """Section 8: Sortable action table (channels + verdicts + footnotes)."""
    return ""  # M2


def render_timeline(data: dict) -> str:
    """Section 9: Timeline stacked area + dataZoom."""
    return ""  # M2


def render_recommendation(data: dict) -> str:
    """Section 10: SCQAR recommendation (3 actions + lift)."""
    return ""  # M2


def render_methodology(data: dict) -> str:
    """Section 11: Methodology + limitations (collapsible)."""
    return ""  # M2


def render_sources(data: dict) -> str:
    """Section 12: Sources + MQS card + methodology badge."""
    return ""  # M2


def render_glossary(data: dict) -> str:
    """Section 13: Glossary 24 terms accordion."""
    return ""  # M2


def render_closing(data: dict) -> str:
    """Section 14: Closing statement + CTA + Report ID + copyright."""
    return ""  # M2


SECTION_RENDERERS = (
    ('cover', render_cover),
    ('summary', render_executive_summary),
    ('findings', render_at_a_glance),
    ('divider', render_section_divider),
    ('key', render_key_message),
    ('mroas', render_mroas),
    ('share', render_share),
    ('table', render_action_table),
    ('timeline', render_timeline),
    ('recommend', render_recommendation),
    ('method', render_methodology),
    ('sources', render_sources),
    ('glossary', render_glossary),
    ('closing', render_closing),
)
