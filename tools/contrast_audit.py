#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WCAG AA Contrast Audit for Aurora MMM Optimizer
Audits light and warm (fun) themes from src/app.css

Usage:
    python tools/contrast_audit.py

Outputs:
    - Console report with all pairs and their ratios
    - docs/CONTRAST_AUDIT_v2_1_0.md (markdown table)
"""

import sys
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# ────────────────────────────────────────────────────────────────────────────
# WCAG helpers
# ────────────────────────────────────────────────────────────────────────────

def hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color (#RRGGBB or #RGB) to (r, g, b) ints 0-255."""
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def linearize(c: float) -> float:
    """sRGB channel -> linear light (WCAG formula)."""
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(r: int, g: int, b: int) -> float:
    """WCAG 2.1 relative luminance, range [0, 1]."""
    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)


def contrast_ratio(hex1: str, hex2: str) -> float:
    """WCAG contrast ratio between two hex colors."""
    l1 = relative_luminance(*hex_to_rgb(hex1))
    l2 = relative_luminance(*hex_to_rgb(hex2))
    lighter = max(l1, l2)
    darker  = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def wcag_grade(ratio: float, large_text: bool = False) -> str:
    """Return WCAG grade: AAA / AA / AA-Large / AA-UI / FAIL."""
    if ratio >= 7.0:
        return "AAA"
    if ratio >= 4.5:
        return "AA"
    if large_text and ratio >= 3.0:
        return "AA-Large"
    if ratio >= 3.0:
        return "AA-UI"
    return "FAIL"


# ────────────────────────────────────────────────────────────────────────────
# Color tokens extracted from src/app.css
# ────────────────────────────────────────────────────────────────────────────
# NOTE: Only SOLID hex values are listed here. rgba() tokens (borders, glows,
# glass) are flagged separately as they depend on actual backing color.

LIGHT_THEME = {
    "bg-primary":       "#F5F5F7",
    "bg-secondary":     "#EEEEF0",
    "bg-tertiary":      "#E4E4E8",
    "bg-card":          "#FFFFFF",
    "bg-card-hover":    "#F0F0F4",
    "input-bg":         "#FFFFFF",
    "text-primary":     "#1A1A1E",
    "text-secondary":   "#4A4A58",
    # Fixed v2.1.0 p.5.4: was #74748A (failed on bg-primary 4.19, bg-secondary 3.93)
    "text-muted":       "#6A6A7E",
    "accent-primary":   "#2E5BFF",
    "accent-secondary": "#4A4A55",
    "accent-hover":     "#4A76FF",
    # Fixed v2.1.0 p.5.4: was #dc2626 (failed on bg-primary 4.44)
    "danger":           "#D92323",
    # Fixed v2.1.0 p.5.4: was #16a34a (failed on bg-card 3.30, bg-primary 3.03)
    "success":          "#11813B",
    # Fixed v2.1.0 p.5.4: was #d97706 (failed on bg-card 3.19, bg-primary 2.93)
    "warning":          "#AA5D05",
    "color-info":       "#0891B2",
    "color-completion": "#059669",
}

FUN_THEME = {
    "bg-primary":       "#F5F0D0",
    "bg-secondary":     "#EDE8C8",
    "bg-tertiary":      "#E5DFB8",
    "bg-card":          "#FFFEF5",
    "bg-card-hover":    "#F9F4DC",
    "input-bg":         "#FFFEF5",
    "text-primary":     "#2D2D1F",
    "text-secondary":   "#5A5A42",
    # Fixed v2.1.0 p.5.5: was #8A8A6E (failed everywhere: 3.49/3.07/2.86)
    "text-muted":       "#696954",
    # Fixed v2.1.0 p.5.5: was #7C6BC4 (button text 4.36 < 4.5)
    "accent-primary":   "#7967C3",
    "accent-secondary": "#90C67C",
    "accent-hover":     "#9585D0",
    # Fixed v2.1.0 p.5.5: was #D94E4E (4.03 < 4.5 on bg-card)
    "danger":           "#D53D3D",
    # Fixed v2.1.0 p.5.5: was #5DAA5D (2.81 < 4.5 on bg-card)
    "success":          "#448244",
    # Fixed v2.1.0 p.5.5: was #D4A844 (2.19 < 4.5 on bg-card)
    "warning":          "#937022",
    # Fixed v2.1.0 p.5.5: was #5B9BD5 (2.92 < 3.0 UI component)
    "color-info":       "#5799D4",
    # Fixed v2.1.0 p.5.5: was #5DAA5D (2.81 < 3.0 UI component)
    "color-completion": "#56A456",
    # Fixed v2.1.0 p.5.5: was #D4C93A (1.70 < 3.0 UI component)
    "card-accent-lemon":    "#948C20",
    "card-accent-lavender": "#8A7DC7",
    # Fixed v2.1.0 p.5.5: was #7FA868 (2.69 < 3.0 UI component)
    "card-accent-sage":     "#739E5B",
    # Fixed v2.1.0 p.5.5: was #D49A5E (2.42 < 3.0 UI component)
    "card-accent-peach":    "#CA833A",
    "card-accent-coral":    "#D47A7A",
}

# ────────────────────────────────────────────────────────────────────────────
# Pairs to audit: (fg_token, bg_token, label, large_text, ui_component)
# large_text: heading >= 18.66px regular OR >= 14px bold
# ui_component: icon, border, control — min 3:1
# normal text: min 4.5:1
# ────────────────────────────────────────────────────────────────────────────

LIGHT_PAIRS = [
    # Body text
    ("text-primary",   "bg-card",        "Body text on card",                  False, False),
    ("text-primary",   "bg-primary",     "Body text on page bg",               False, False),
    ("text-primary",   "bg-secondary",   "Body text on secondary bg",          False, False),
    # Secondary text
    ("text-secondary", "bg-card",        "Secondary text on card",             False, False),
    ("text-secondary", "bg-primary",     "Secondary text on page bg",          False, False),
    ("text-secondary", "bg-secondary",   "Secondary text on secondary bg",     False, False),
    # Muted text (labels, hints)
    ("text-muted",     "bg-card",        "Muted text on card",                 False, False),
    ("text-muted",     "bg-primary",     "Muted text on page bg",              False, False),
    ("text-muted",     "bg-secondary",   "Muted text on secondary bg",         False, False),
    ("text-muted",     "input-bg",       "Muted text on input bg",             False, False),
    # Headings (large text)
    ("text-primary",   "bg-card",        "Heading on card (large)",            True,  False),
    ("text-secondary", "bg-card",        "Subheading on card (large)",         True,  False),
    # Accent / links
    ("accent-primary", "bg-card",        "Link/accent on card",                False, True),
    ("accent-primary", "bg-primary",     "Link/accent on page bg",             False, True),
    ("accent-primary", "input-bg",       "Accent on input bg",                 False, True),
    # Button text (white text on accent-primary button)
    ("bg-card",        "accent-primary", "White text on primary button",       False, False),
    # Status colors on backgrounds
    ("danger",         "bg-card",        "Danger text on card",                False, False),
    ("danger",         "bg-primary",     "Danger on page bg",                  False, False),
    ("success",        "bg-card",        "Success text on card",               False, False),
    ("success",        "bg-primary",     "Success on page bg",                 False, False),
    ("warning",        "bg-card",        "Warning text on card",               False, False),
    ("warning",        "bg-primary",     "Warning on page bg",                 False, False),
    # Info / completion
    ("color-info",     "bg-card",        "Info color on card (UI)",            False, True),
    ("color-info",     "bg-primary",     "Info color on page bg (UI)",         False, True),
    ("color-completion", "bg-card",      "Completion color on card (UI)",      False, True),
    # Icon color (text-secondary is --icon-color)
    ("text-secondary", "bg-card",        "Icon on card (UI comp)",             False, True),
    ("text-secondary", "bg-secondary",   "Icon on secondary bg (UI comp)",     False, True),
]

FUN_PAIRS = [
    # Body text
    ("text-primary",   "bg-card",        "Body text on card",                  False, False),
    ("text-primary",   "bg-primary",     "Body text on page bg",               False, False),
    ("text-primary",   "bg-secondary",   "Body text on secondary bg",          False, False),
    # Secondary text
    ("text-secondary", "bg-card",        "Secondary text on card",             False, False),
    ("text-secondary", "bg-primary",     "Secondary text on page bg",          False, False),
    ("text-secondary", "bg-secondary",   "Secondary text on secondary bg",     False, False),
    # Muted text
    ("text-muted",     "bg-card",        "Muted text on card",                 False, False),
    ("text-muted",     "bg-primary",     "Muted text on page bg",              False, False),
    ("text-muted",     "bg-secondary",   "Muted text on secondary bg",         False, False),
    ("text-muted",     "input-bg",       "Muted text on input bg",             False, False),
    # Headings
    ("text-primary",   "bg-card",        "Heading on card (large)",            True,  False),
    ("text-secondary", "bg-card",        "Subheading on card (large)",         True,  False),
    # Accent / links
    ("accent-primary", "bg-card",        "Link/accent on card",                False, True),
    ("accent-primary", "bg-primary",     "Link/accent on page bg",             False, True),
    ("accent-primary", "input-bg",       "Accent on input bg",                 False, True),
    # Button
    ("bg-card",        "accent-primary", "White text on primary button",       False, False),
    # Status
    ("danger",         "bg-card",        "Danger text on card",                False, False),
    ("success",        "bg-card",        "Success text on card",               False, False),
    ("warning",        "bg-card",        "Warning text on card",               False, False),
    # Info
    ("color-info",     "bg-card",        "Info color on card (UI)",            False, True),
    ("color-completion", "bg-card",      "Completion color on card (UI)",      False, True),
    # Icon color
    ("text-secondary", "bg-card",        "Icon on card (UI comp)",             False, True),
    ("text-secondary", "bg-secondary",   "Icon on secondary bg (UI comp)",     False, True),
    # Card accent colors used as decorative borders (UI component: >= 3:1)
    ("card-accent-lemon",    "bg-card",  "Lemon accent on card (UI)",          False, True),
    ("card-accent-lavender", "bg-card",  "Lavender accent on card (UI)",       False, True),
    ("card-accent-sage",     "bg-card",  "Sage accent on card (UI)",           False, True),
    ("card-accent-peach",    "bg-card",  "Peach accent on card (UI)",          False, True),
    ("card-accent-coral",    "bg-card",  "Coral accent on card (UI)",          False, True),
    ("card-accent-lemon",    "bg-primary","Lemon accent on warm bg (UI)",      False, True),
]

# ────────────────────────────────────────────────────────────────────────────
# Audit runner
# ────────────────────────────────────────────────────────────────────────────

def audit_pairs(theme_tokens: dict, pairs: list, theme_name: str) -> list:
    results = []
    for fg_token, bg_token, label, large_text, ui_component in pairs:
        fg = theme_tokens.get(fg_token)
        bg = theme_tokens.get(bg_token)
        if not fg or not bg:
            results.append({
                "theme": theme_name,
                "label": label,
                "fg_token": fg_token,
                "bg_token": bg_token,
                "fg": fg or "MISSING",
                "bg": bg or "MISSING",
                "ratio": 0.0,
                "grade": "SKIP",
                "min_required": "-",
                "min_val": 0.0,
                "pass": None,
                "action": "TOKEN MISSING",
            })
            continue

        try:
            ratio = contrast_ratio(fg, bg)
        except Exception as e:
            results.append({
                "theme": theme_name,
                "label": label,
                "fg_token": fg_token,
                "bg_token": bg_token,
                "fg": fg,
                "bg": bg,
                "ratio": 0.0,
                "grade": "ERROR",
                "min_required": "-",
                "min_val": 0.0,
                "pass": False,
                "action": f"ERROR: {e}",
            })
            continue

        # Determine minimum required ratio
        if large_text:
            min_ratio = 3.0
            req_label = "3.0 (large text)"
        elif ui_component:
            min_ratio = 3.0
            req_label = "3.0 (UI component)"
        else:
            min_ratio = 4.5
            req_label = "4.5 (normal text)"

        passes = ratio >= min_ratio
        grade = wcag_grade(ratio, large_text)

        results.append({
            "theme": theme_name,
            "label": label,
            "fg_token": fg_token,
            "bg_token": bg_token,
            "fg": fg,
            "bg": bg,
            "ratio": round(ratio, 2),
            "grade": grade,
            "min_required": req_label,
            "min_val": min_ratio,
            "pass": passes,
            "action": "OK" if passes else f"FIX NEEDED ({ratio:.2f} < {min_ratio})",
        })
    return results


def print_results(results: list) -> None:
    fails = [r for r in results if r["pass"] is False]
    passes = [r for r in results if r["pass"] is True]

    print("=" * 80)
    print("WCAG AA CONTRAST AUDIT - Aurora MMM Optimizer")
    print("=" * 80)
    print()

    for r in results:
        icon = "[OK  ]" if r["pass"] else ("[FAIL]" if r["pass"] is False else "[SKIP]")
        print(f"{icon} [{r['theme']}] {r['label']}")
        print(f"       {r['fg_token']} ({r['fg']}) on {r['bg_token']} ({r['bg']})")
        print(f"       Ratio: {r['ratio']}:1  Grade: {r['grade']}  Min: {r['min_required']}")
        if r["pass"] is False:
            print(f"       !! ACTION: {r['action']}")
        print()

    print("=" * 80)
    print(f"SUMMARY: {len(passes)} PASS / {len(fails)} FAIL / {len(results) - len(passes) - len(fails)} SKIP")
    print("=" * 80)
    print()

    if fails:
        print("FAILING PAIRS:")
        for r in fails:
            print(f"  [{r['theme']}] {r['fg_token']} on {r['bg_token']}  ->  {r['ratio']}:1 (need {r['min_required']})")


def generate_markdown(light_results: list, fun_results: list) -> str:
    """Generate markdown audit table for docs/CONTRAST_AUDIT_v2_1_0.md"""
    lines = [
        "# WCAG AA Contrast Audit - v2.1.0",
        "",
        "> Auto-generated by `tools/contrast_audit.py`",
        "> Date: 2026-05-16",
        "> Coverage: light theme (`[data-theme=\"light\"]`) + warm/fun theme (`[data-theme=\"fun\"]`)",
        "> Source: `src/app.css`",
        "",
        "## WCAG AA minimum requirements",
        "",
        "| Text type | Min contrast ratio |",
        "|---|---|",
        "| Normal text (< 18.66px regular, < 14px bold) | **4.5:1** |",
        "| Large text (>= 18.66px regular or >= 14px bold) | **3:1** |",
        "| UI components (icons, borders, buttons) | **3:1** |",
        "",
    ]

    def theme_section(results: list, theme_label: str) -> list:
        section = [
            f"## {theme_label}",
            "",
            "| Pair | FG Token | BG Token | FG Hex | BG Hex | Ratio | Grade | Min | Status |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in results:
            if r["pass"] is True:
                status = "OK"
            elif r["pass"] is False:
                status = "**FIX**"
            else:
                status = "SKIP"
            section.append(
                f"| {r['label']} "
                f"| `{r['fg_token']}` "
                f"| `{r['bg_token']}` "
                f"| `{r['fg']}` "
                f"| `{r['bg']}` "
                f"| {r['ratio']} "
                f"| {r['grade']} "
                f"| {r['min_required']} "
                f"| {status} |"
            )
        fails = [r for r in results if r["pass"] is False]
        ok_count = len([r for r in results if r["pass"] is True])
        skip_count = len(results) - ok_count - len(fails)
        section += [
            "",
            f"**Total:** {ok_count} OK / {len(fails)} FAIL / {skip_count} SKIP",
            "",
        ]
        return section

    lines += theme_section(light_results, "Light Theme (`[data-theme=\"light\"]`)")
    lines += theme_section(fun_results, "Warm/Fun Theme (`[data-theme=\"fun\"]`)")

    all_fails = [r for r in light_results + fun_results if r["pass"] is False]
    lines += [
        "## Recommended Fixes",
        "",
    ]
    if all_fails:
        lines += [
            "| Theme | Token | Current value | Current ratio | Needed | Action |",
            "|---|---|---|---|---|---|",
        ]
        for r in all_fails:
            lines.append(
                f"| {r['theme']} "
                f"| `{r['fg_token']}` "
                f"| `{r['fg']}` on `{r['bg']}` "
                f"| {r['ratio']}:1 "
                f"| >= {r['min_val']}:1 "
                f"| Darken/lighten fg to increase contrast |"
            )
    else:
        lines.append("All pairs comply with WCAG AA - no fixes required.")

    lines += [
        "",
        "## Notes (not covered by this audit)",
        "",
        "- `rgba()` border/glow tokens (`--border`, `--border-subtle`) - used as UI dividers, not text containers. WCAG 1.4.11 non-text contrast requires 3:1 against adjacent colors - not audited here.",
        "- `--bg-glass` / `--bg-surface-quiet` - depend on backing color; specific pairs need to be verified in UI.",
        "- Disabled states (opacity 0.32-0.5) - excluded from WCAG AA per SC 1.4.3 (inactive UI components).",
        "- JS-side color tokens (if any) - not changed, flagged for manual review.",
        "- Dark theme - not audited here (already has comment in app.css re: H-15 fix for text-muted).",
        "",
    ]
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────

def main() -> int:
    light_results = audit_pairs(LIGHT_THEME, LIGHT_PAIRS, "light")
    fun_results   = audit_pairs(FUN_THEME,   FUN_PAIRS,   "warm/fun")

    print_results(light_results + fun_results)

    md = generate_markdown(light_results, fun_results)

    out_path = Path(__file__).parent.parent / "docs" / "CONTRAST_AUDIT_v2_1_0.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"\nMarkdown audit saved -> {out_path}")

    all_fails = [r for r in light_results + fun_results if r["pass"] is False]
    return 1 if all_fails else 0


if __name__ == "__main__":
    sys.exit(main())
