"""
Brand compliance verification for aurora_pptx builder output.

Renders the default pilot deck + a custom-client deck and asserts that the
tier-1 brand markers required by Standards/CLIENT_READY_ANATOMY.md reach the
generated OOXML. Closes audit finding L4 (SESSION_AUDIT_2026-04-24.md).

Run:
    cd sidecar && python ../tools/verify_aurora_pptx_brand.py

Exit code 0 on success, 1 on any failed assertion.
"""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "sidecar"
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / "econometrica"))  # aurora_tokens top-level

# Aurora rules
FORBIDDEN_EM_DASH = "\u2014"          # "—"
SACRED_LIME_UPPER = "CCFF00"           # hex without leading # in XML attrs
EXPECTED_FONTS = ("Georgia", "Arial")  # Standards/01 typography contract


def _extract_slide_xml(pptx_path: Path) -> str:
    with zipfile.ZipFile(pptx_path) as z:
        return "".join(
            z.read(n).decode("utf-8", errors="ignore")
            for n in z.namelist()
            if n.startswith("ppt/slides/slide") and n.endswith(".xml")
        )


def _check(label: str, cond: bool, detail: str = "") -> bool:
    tag = "[OK]  " if cond else "[FAIL]"
    line = f"{tag} {label}"
    if detail:
        line += f" - {detail}"
    print(line)
    return cond


def main() -> int:
    from econometrica.aurora_pptx import build_pptx

    out = REPO / "tools" / "_brand_verify.pptx"
    out2 = REPO / "tools" / "_brand_verify_custom.pptx"

    # 1. Render defaults (Kagocel pilot).
    prs = build_pptx()
    prs.save(str(out))
    xml_default = _extract_slide_xml(out)

    # 2. Render with custom meta + diagnostics.
    custom = {
        "meta": {
            "client": "Acme Corp",
            "project_id": "ACME-Q2-2026",
            "version": "2.0.0",
            "data_window_label": "W14 W26 2026",
        },
        "diagnostics": {
            "mqs_score": 73,
            "mqs_tier_label": "FAIR",
            "r_squared": 0.654,
            "mape_pct": 12.4,
            "r_hat_max": 1.015,
            "ess_min": 892,
        },
    }
    prs2 = build_pptx(data=custom)
    prs2.save(str(out2))
    xml_custom = _extract_slide_xml(out2)

    results = []

    # Slide count (wireframe v3 = 13).
    results.append(_check(
        "default deck has 13 slides",
        len(prs.slides) == 13,
        f"got {len(prs.slides)}",
    ))
    results.append(_check(
        "custom deck has 13 slides",
        len(prs2.slides) == 13,
        f"got {len(prs2.slides)}",
    ))

    # Sacred lime #CCFF00 on content slides.
    lime_count = xml_default.count(SACRED_LIME_UPPER)
    results.append(_check(
        "sacred lime CCFF00 present (default)",
        lime_count >= 3,
        f"found {lime_count} refs (expect >=3 content slides)",
    ))

    # No em dash leakage in rendered text (Aurora rule feedback_no_em_dash).
    em_count = xml_default.count(FORBIDDEN_EM_DASH)
    results.append(_check(
        "no em dash in default output",
        em_count == 0,
        f"found {em_count} occurrences of U+2014",
    ))
    em_count2 = xml_custom.count(FORBIDDEN_EM_DASH)
    results.append(_check(
        "no em dash in custom output",
        em_count2 == 0,
        f"found {em_count2} occurrences",
    ))

    # Typography: Standards/01 embed fonts (Georgia + Arial referenced by name).
    for font in EXPECTED_FONTS:
        results.append(_check(
            f"font '{font}' referenced",
            font in xml_default,
            "present" if font in xml_default else "MISSING",
        ))

    # Custom meta propagates to output XML.
    results.append(_check(
        "custom client name reaches output",
        "Acme Corp" in xml_custom and "ACME CORP" in xml_custom,
        "Acme Corp and ACME CORP both present in slides",
    ))
    results.append(_check(
        "custom version reaches output",
        "v2.0.0" in xml_custom,
    ))
    results.append(_check(
        "custom diagnostics reach output",
        "0.654" in xml_custom and "12.4%" in xml_custom and "892" in xml_custom,
        "R2, MAPE, ESS propagate",
    ))

    # No Kagocel defaults leak when custom meta provided.
    for leak in ("Kagocel", "KAGOCEL", "v1.0.11", "0.872"):
        results.append(_check(
            f"no leak of default '{leak}' in custom output",
            leak not in xml_custom,
        ))

    # Cleanup.
    try:
        os.remove(out)
        os.remove(out2)
    except OSError:
        pass

    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\n{passed}/{total} checks passed.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
