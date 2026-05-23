"""
WCAG AA contrast verification for Aurora HTML tier-1 (M4).

Parses the generated aurora_html.css, extracts color variables per theme,
and verifies key text/background combinations meet WCAG AA thresholds:
  - 4.5:1 for body text
  - 3:1 for large text (>=18pt / 24px bold)
  - 3:1 for UI components (buttons, focus outlines)

Does not need a browser - pure arithmetic on hex values.

Run:
    cd sidecar && python ../tools/verify_aurora_html_a11y.py

Exit 0 on success, 1 on any assertion failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Force UTF-8 stdout on Windows cp1251
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

REPO = Path(__file__).resolve().parents[1]
CSS_PATH = REPO / "sidecar" / "econometrica" / "aurora_html" / "templates" / "aurora_html.css"


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.strip().lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2.x relative luminance (sRGB, 0-1)."""
    def linearise(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = linearise(rgb[0]), linearise(rgb[1]), linearise(rgb[2])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    l1 = relative_luminance(hex_to_rgb(fg))
    l2 = relative_luminance(hex_to_rgb(bg))
    brighter, darker = max(l1, l2), min(l1, l2)
    return (brighter + 0.05) / (darker + 0.05)


def parse_theme_vars(css: str) -> dict[str, dict[str, str]]:
    """Extract variables from each [data-theme=...] block."""
    themes = {}
    # Pattern: [data-theme="X"] { ... }
    for m in re.finditer(
        r'\[data-theme\s*=\s*"([^"]+)"\]\s*\{([^}]+)\}', css, flags=re.DOTALL
    ):
        theme_name = m.group(1)
        body = m.group(2)
        vars_map = {}
        for vm in re.finditer(r'--([a-z0-9\-]+)\s*:\s*([^;]+);', body):
            vars_map[vm.group(1).strip()] = vm.group(2).strip()
        themes[theme_name] = vars_map
    return themes


def check(label: str, ratio: float, min_ratio: float) -> bool:
    ok = ratio >= min_ratio
    status = "[OK]  " if ok else "[FAIL]"
    print(f"{status} {label}: contrast {ratio:.2f}:1 (need >={min_ratio})")
    return ok


def main() -> int:
    if not CSS_PATH.exists():
        print(f"ERROR: {CSS_PATH} not found. Run tokens build first.")
        return 1

    css = CSS_PATH.read_text(encoding='utf-8')
    themes = parse_theme_vars(css)
    if not themes:
        print("ERROR: no [data-theme] selectors found in CSS")
        return 1

    required_pairs = [
        # (fg_var, bg_var, min_ratio, label_suffix)
        ('text',           'bg',      4.5, 'body on background'),
        ('text',           'surface', 4.5, 'body on surface'),
        ('text-secondary', 'bg',      4.5, 'secondary body on bg'),
        ('text-muted',     'bg',      3.0, 'muted on bg (large/UI)'),
        ('accent',         'bg',      3.0, 'accent (gold) UI on bg'),
    ]

    results = []
    for theme_name, vars_map in themes.items():
        print(f"\n── theme: {theme_name} ──")
        for fg_key, bg_key, min_r, suffix in required_pairs:
            fg = vars_map.get(fg_key)
            bg = vars_map.get(bg_key)
            if not fg or not bg or not fg.startswith('#') or not bg.startswith('#'):
                # Skip if variable references another token (CSS var substitution
                # not resolved at this static analysis level).
                print(f"[SKIP] {theme_name}/{fg_key}+{bg_key}: not resolvable ({fg} / {bg})")
                continue
            ratio = contrast_ratio(fg, bg)
            label = f"{theme_name}/{fg_key} on {bg_key} ({suffix})"
            results.append(check(label, ratio, min_r))

    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\n{passed}/{total} WCAG AA pairs passed")
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
