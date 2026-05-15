#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper: find minimum-change hex to reach a target WCAG contrast ratio.

Usage:
    python tools/find_wcag_color.py
"""

import sys
import colorsys

def linearize(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def relative_luminance(r, g, b):
    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)

def contrast_ratio(hex1, hex2):
    def parse(h):
        h = h.lstrip('#')
        if len(h) == 3:
            h = ''.join(c*2 for c in h)
        return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
    r1,g1,b1 = parse(hex1)
    r2,g2,b2 = parse(hex2)
    l1 = relative_luminance(r1,g1,b1)
    l2 = relative_luminance(r2,g2,b2)
    light = max(l1,l2)
    dark = min(l1,l2)
    return (light+0.05)/(dark+0.05)

def hex_to_hsl(hex_color):
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = ''.join(c*2 for c in h)
    r,g,b = int(h[0:2],16)/255, int(h[2:4],16)/255, int(h[4:6],16)/255
    hue, lum, sat = colorsys.rgb_to_hls(r, g, b)
    return hue*360, sat*100, lum*100

def hsl_to_hex(h_deg, s_pct, l_pct):
    h = h_deg / 360.0
    s = s_pct / 100.0
    l = l_pct / 100.0
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return '#{:02X}{:02X}{:02X}'.format(int(r*255+0.5), int(g*255+0.5), int(b*255+0.5))

def find_min_change(original_hex, background_hex, target_ratio, lighten=False):
    """Find minimum L change to reach target_ratio. Returns new hex."""
    h, s, l_orig = hex_to_hsl(original_hex)

    # Try darkening (decreasing L) or lightening (increasing L)
    step = 0.5
    if lighten:
        rng = range(int(l_orig*10), 1000, int(step*10))
    else:
        rng = range(int(l_orig*10), -1, -int(step*10))

    for l_10 in rng:
        l_try = l_10 / 10.0
        candidate = hsl_to_hex(h, s, l_try)
        r = contrast_ratio(candidate, background_hex)
        if r >= target_ratio:
            return candidate, r, l_orig, l_try
    return None, 0.0, l_orig, l_orig


if __name__ == "__main__":
    print("FINDING OPTIMAL WCAG AA COMPLIANT COLORS")
    print("=" * 70)
    print()

    # ── Light theme fixes ──
    print("=== LIGHT THEME ===")
    print()

    cases_light = [
        # (token_name, original, background, target_ratio, lighten, description)
        ("text-muted",  "#74748A", "#F5F5F7", 4.5, False, "text-muted on bg-primary"),
        ("text-muted",  "#74748A", "#EEEEF0", 4.5, False, "text-muted on bg-secondary (harder)"),
        ("danger",      "#dc2626", "#F5F5F7", 4.5, False, "danger on bg-primary"),
        ("success",     "#16a34a", "#FFFFFF", 4.5, False, "success on bg-card"),
        ("success",     "#16a34a", "#F5F5F7", 4.5, False, "success on bg-primary"),
        ("warning",     "#d97706", "#FFFFFF", 4.5, False, "warning on bg-card"),
        ("warning",     "#d97706", "#F5F5F7", 4.5, False, "warning on bg-primary"),
    ]

    seen_light = {}
    for token, orig, bg, target, lighten, desc in cases_light:
        new_hex, ratio, l_orig, l_new = find_min_change(orig, bg, target, lighten)
        h, s, _ = hex_to_hsl(orig)
        key = (token, orig)
        if new_hex:
            # Keep track of most restrictive (darkest)
            if key not in seen_light or l_new < hex_to_hsl(seen_light[key][0])[2]:
                seen_light[key] = (new_hex, ratio, l_orig, l_new)
            print(f"  [{desc}]")
            print(f"    {orig} -> {new_hex}  (L: {l_orig:.1f}% -> {l_new:.1f}%, ratio: {ratio:.2f}:1)")
        else:
            print(f"  [{desc}] COULD NOT FIND (orig {orig})")
        print()

    print()
    print("  >> CONSOLIDATED light theme fixes (most restrictive):")
    for (token, orig), (new_hex, ratio, l_orig, l_new) in seen_light.items():
        all_ratios = []
        for tok2, orig2, bg2, target2, lighten2, desc2 in cases_light:
            if tok2 == token:
                r = contrast_ratio(new_hex, bg2)
                all_ratios.append(f"{bg2}={r:.2f}")
        print(f"    {token}: {orig} -> {new_hex}  (L: {l_orig:.1f}% -> {l_new:.1f}%)")
        print(f"      Ratios: {', '.join(all_ratios)}")
    print()

    # ── Fun/warm theme fixes ──
    print()
    print("=== FUN/WARM THEME ===")
    print()

    cases_fun = [
        # text-muted needs to work on card (#FFFEF5), bg-primary (#F5F0D0), bg-secondary (#EDE8C8), input-bg (#FFFEF5)
        ("text-muted",       "#8A8A6E", "#FFFEF5", 4.5, False, "text-muted on bg-card"),
        ("text-muted",       "#8A8A6E", "#F5F0D0", 4.5, False, "text-muted on bg-primary"),
        ("text-muted",       "#8A8A6E", "#EDE8C8", 4.5, False, "text-muted on bg-secondary (hardest)"),
        # danger on card
        ("danger",           "#D94E4E", "#FFFEF5", 4.5, False, "danger on bg-card"),
        # success on card
        ("success",          "#5DAA5D", "#FFFEF5", 4.5, False, "success on bg-card"),
        # warning on card
        ("warning",          "#D4A844", "#FFFEF5", 4.5, False, "warning on bg-card"),
        # color-info on card (UI, min 3.0)
        ("color-info",       "#5B9BD5", "#FFFEF5", 3.0, False, "color-info on bg-card (UI)"),
        # color-completion on card (UI, min 3.0)
        ("color-completion", "#5DAA5D", "#FFFEF5", 3.0, False, "color-completion on bg-card (UI)"),
        # accent-primary: white text needs 4.5 on button
        # bg-card (#FFFEF5) on accent-primary (#7C6BC4): 4.36 < 4.5
        ("accent-primary",   "#7C6BC4", "#FFFEF5", 4.5, False, "bg-card on accent-primary (darken accent)"),
        # card-accent-lemon on bg-card (UI 3.0)
        ("card-accent-lemon","#D4C93A", "#FFFEF5", 3.0, False, "lemon on bg-card (UI)"),
        # card-accent-lemon on bg-primary (UI 3.0)
        ("card-accent-lemon","#D4C93A", "#F5F0D0", 3.0, False, "lemon on bg-primary (UI, harder)"),
        # card-accent-sage on bg-card (UI 3.0)
        ("card-accent-sage", "#7FA868", "#FFFEF5", 3.0, False, "sage on bg-card (UI)"),
        # card-accent-peach on bg-card (UI 3.0)
        ("card-accent-peach","#D49A5E", "#FFFEF5", 3.0, False, "peach on bg-card (UI)"),
    ]

    seen_fun = {}
    for token, orig, bg, target, lighten, desc in cases_fun:
        new_hex, ratio, l_orig, l_new = find_min_change(orig, bg, target, lighten)
        key = (token, orig)
        if new_hex:
            if key not in seen_fun or hex_to_hsl(new_hex)[2] < hex_to_hsl(seen_fun[key][0])[2]:
                seen_fun[key] = (new_hex, ratio, l_orig, l_new)
            print(f"  [{desc}]")
            print(f"    {orig} -> {new_hex}  (L: {l_orig:.1f}% -> {l_new:.1f}%, ratio: {ratio:.2f}:1)")
        else:
            print(f"  [{desc}] COULD NOT FIND")
        print()

    print()
    print("  >> CONSOLIDATED fun/warm theme fixes (most restrictive):")
    for (token, orig), (new_hex, ratio, l_orig, l_new) in seen_fun.items():
        all_ratios = []
        for tok2, orig2, bg2, target2, lighten2, desc2 in cases_fun:
            if tok2 == token:
                r = contrast_ratio(new_hex, bg2)
                all_ratios.append(f"{bg2}={r:.2f}")
        print(f"    {token}: {orig} -> {new_hex}  (L: {l_orig:.1f}% -> {l_new:.1f}%)")
        print(f"      Ratios: {', '.join(all_ratios)}")
