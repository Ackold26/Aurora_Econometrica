"""
Brand verification for aurora_html tier-1 (M5).

Asserts 25+ brand + security + structural invariants on a fully rendered
HTML output using realistic test data.

Run:
    cd sidecar && python ../tools/verify_aurora_html_brand.py

Exit 0 on success, 1 on any assertion failure.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "sidecar"
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / "econometrica"))


def _check(label: str, cond: bool, detail: str = "") -> bool:
    tag = "[OK]  " if cond else "[FAIL]"
    line = f"{tag} {label}"
    if detail:
        line += f" - {detail}"
    print(line)
    return cond


def _build_sample_html() -> str:
    from engines.html_export import build_html
    model = {
        'diagnostics': {
            'mqs': {'score': 87, 'tier_label': 'GOOD'},
            'metrics': {'r_squared': 0.872, 'mape_pct': 8.3, 'r_hat_max': 1.008, 'ess_min': 1247},
        },
        'channel_params': {
            'TV': {'beta': 0.42, 'alpha': 1.5, 'gamma': 0.8, 'adstock': 0.6},
            'Digital': {'beta': 0.28, 'alpha': 1.8, 'gamma': 0.5, 'adstock': 0.3},
        },
        'normalization': {'y_mean': 100e6, 'y_std': 25e6,
                          'media_means': {'TV': 20e6, 'Digital': 10e6}},
    }
    decompose = {
        'channels': [
            {'name': 'Digital', 'spend': 65e6, 'contribution': 124e6, 'roi': 1.9},
            {'name': 'TV',      'spend': 120e6, 'contribution': 180e6, 'roi': 1.5},
        ],
        'waterfall': {'labels': ['Base', 'Digital', 'TV'], 'values': [500, 124, 180]},
        'time_series': {'dates': ['W01', 'W02', 'W03'], 'baseline': [38, 40, 42],
                        'channels': {'Digital': [8, 9, 10], 'TV': [12, 14, 16]}},
    }
    optimize = {
        'channels': [
            {'name': 'Digital', 'current_spend': 65e6,  'optimal_spend': 110e6},
            {'name': 'TV',      'current_spend': 120e6, 'optimal_spend': 90e6},
        ],
        'expected_lift_pct': 12.5,
    }
    out = 'tools/_brand_verify.html'
    Path(out).parent.mkdir(exist_ok=True)
    build_html(model, decompose, optimize, out,
               scenarios=[], project_id='Acme-Corp-2026', initial_theme='light')
    html = Path(out).read_text(encoding='utf-8')
    try:
        os.remove(out)
    except OSError:
        pass
    return html


def main() -> int:
    html = _build_sample_html()
    results = []

    # ─── Brand identity ────────────────────────────────────────
    results.append(_check("Aurora AI wordmark present", "Aurora AI" in html))
    results.append(_check("No 'Econometrica' substring in output",
                          "Econometrica" not in html))
    results.append(_check("Sacred lime #CCFF00 in CSS vars",
                          "#CCFF00" in html or "#ccff00" in html))
    results.append(_check("Gold primary #C5A46D present",
                          "#C5A46D" in html or "#c5a46d" in html))
    results.append(_check("Aurora deep navy #0A1628 present",
                          "#0A1628" in html or "#0a1628" in html))

    # ─── Typography & fonts ───────────────────────────────────
    results.append(_check("Lora font family referenced",
                          "'Lora'" in html or '"Lora"' in html))
    results.append(_check("Inter font family referenced",
                          "'Inter'" in html or '"Inter"' in html))
    results.append(_check("WOFF2 data URI (Lora latin) embedded",
                          "data:font/woff2;base64" in html))
    # At least 4 @font-face blocks (Lora latin+cyrillic + Inter latin+cyrillic)
    results.append(_check("4+ @font-face declarations",
                          html.count("@font-face") >= 4,
                          f"found {html.count('@font-face')}"))

    # ─── Theme system ─────────────────────────────────────────
    results.append(_check('data-theme="light" selector present',
                          '[data-theme="light"]' in html))
    results.append(_check('data-theme="dark" selector present',
                          '[data-theme="dark"]' in html))
    results.append(_check('data-theme="fun" selector present',
                          '[data-theme="fun"]' in html))

    # ─── ECharts bundle ───────────────────────────────────────
    # ECharts signature string (present in min.js)
    results.append(_check("ECharts bundle inline (not CDN ref)",
                          "echarts" in html and "cdn.jsdelivr" not in html
                          and "cdn.bootcss" not in html))

    # ─── Security ─────────────────────────────────────────────
    results.append(_check("Content-Security-Policy meta present",
                          "Content-Security-Policy" in html))
    results.append(_check("CSP uses sha256 hashes",
                          "'sha256-" in html))
    results.append(_check("NO 'unsafe-inline' in CSP",
                          "'unsafe-inline'" not in html))
    results.append(_check("NO 'unsafe-eval' in CSP",
                          "'unsafe-eval'" not in html))
    results.append(_check("frame-ancestors 'none' in CSP",
                          "frame-ancestors 'none'" in html))

    # ─── Structural (14 sections) ─────────────────────────────
    section_ids = ['cover', 'summary', 'findings', 'divider', 'key', 'mroas',
                   'share', 'table', 'timeline', 'recommend', 'method',
                   'sources', 'glossary', 'closing']
    present = sum(1 for s in section_ids if f'id="{s}"' in html)
    results.append(_check(f"14 section ids present", present == 14,
                          f"{present}/14"))

    # ─── Accessibility ───────────────────────────────────────
    results.append(_check("Skip-to-content link present",
                          'class="skip-link"' in html))
    results.append(_check("aria-hidden on decorative lime bars",
                          'aria-hidden="true"' in html))
    results.append(_check("lang='ru' on html root", 'lang="ru"' in html))
    results.append(_check("Viewport meta for responsive",
                          'name="viewport"' in html))

    # ─── Trust signals ────────────────────────────────────────
    results.append(_check("Report ID present (aurora-mmm-XX hash)",
                          "aurora-mmm-" in html))
    results.append(_check("Favicon SVG data URI",
                          "data:image/svg+xml;base64" in html))
    results.append(_check("OG meta tags (og:title)",
                          'property="og:title"' in html))
    results.append(_check("Methodology badge link",
                          '#method' in html))
    results.append(_check("Confidentiality watermark",
                          "CONFIDENTIAL" in html))

    # ─── Size budget ─────────────────────────────────────────
    size_kb = len(html) / 1024
    results.append(_check(f"HTML size under 1.2 MB cap",
                          size_kb < 1200, f"{size_kb:.1f} KB"))

    # ─── Em dash (user-visible content only) ─────────────────
    # Exclude bundled ECharts Chinese i18n strings (third-party)
    # Heuristic: find em dashes NOT surrounded by CJK characters
    import re
    non_cjk_em_dashes = 0
    for m in re.finditer(r'.{2}—.{2}', html):
        ctx = m.group()
        # Count only if surrounding is not CJK (U+4E00-U+9FFF)
        if not any(0x4E00 <= ord(c) <= 0x9FFF for c in ctx):
            non_cjk_em_dashes += 1
    results.append(_check(f"No em dashes in user-visible content",
                          non_cjk_em_dashes == 0,
                          f"{non_cjk_em_dashes} found (ECharts CJK excluded)"))

    # ─── Summary ─────────────────────────────────────────────
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\n{passed}/{total} brand invariants passed")
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
