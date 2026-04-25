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
        "default deck has 16 slides",
        len(prs.slides) == 16,
        f"got {len(prs.slides)}",
    ))
    results.append(_check(
        "custom deck has 16 slides",
        len(prs2.slides) == 16,
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
    # Stage B.2: center header removed, so ACME CORP uppercase no longer
    # required. Client name only needs to appear in cover metadata.
    results.append(_check(
        "custom client name reaches output (cover metadata)",
        "Acme Corp" in xml_custom,
        "'Acme Corp' present in cover metadata tiles",
    ))
    # Stage B.4: internal product version replaced by deterministic Report ID
    # (aurora-mmm-{12hex}) as client-facing trace. No more "v2.0.0" leaking.
    import re as _re
    report_id_match = _re.search(r'aurora-mmm-[a-f0-9]{12}', xml_custom)
    results.append(_check(
        "Report ID (aurora-mmm-XX) present in sources instead of product version",
        report_id_match is not None,
        f"found: {report_id_match.group(0) if report_id_match else 'none'}",
    ))
    # Affirmatively ensure product version pattern is NOT present anywhere
    results.append(_check(
        "no 'v1.0.X' / 'v2.0.X' product version leak in slides",
        _re.search(r'\bv\d+\.\d+\.\d+\b', xml_custom) is None,
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

    # ─── C.6.4: English ban-list in user-visible text ──────────────────────
    # Enum keys (Scale/Hold/Cut/Reduce/Watch) are RU-localized in the table
    # column; they must NEVER surface as literal English in slide bodies.
    # Methodology terms (saturation, baseline, breakeven) were Russified in
    # Stage C.3 — regression-catch any new additions.
    # Extract *visible text* only (content between <a:t>...</a:t>), so
    # attribute values like 'Segoe UI' don't trigger false positives.
    import re as _re2
    visible_default = " ".join(_re2.findall(r'<a:t>([^<]*)</a:t>', xml_default))
    visible_custom = " ".join(_re2.findall(r'<a:t>([^<]*)</a:t>', xml_custom))
    english_banlist = [
        "saturation", "baseline",
        "breakeven", "break-even",
        "reallocate", "reallocation",
        "portfolio",
    ]
    # Strip math formula variables (e.g. "baseline_t", "x_i", "beta_0") before
    # the ban-list sweep. Formulas on the Methodology slide use standard
    # Bayesian MMM notation that intentionally keeps English variable names.
    def _strip_formula_vars(text: str) -> str:
        return _re2.sub(r'\b[a-z_]+_\{?[a-z0-9,]+\}?\b', ' ', text)

    vd_clean = _strip_formula_vars(visible_default)
    vc_clean = _strip_formula_vars(visible_custom)
    for term in english_banlist:
        pattern = _re2.compile(rf'\b{_re2.escape(term)}\b', _re2.IGNORECASE)
        bad_default = pattern.search(vd_clean)
        bad_custom = pattern.search(vc_clean)
        results.append(_check(
            f"English term '{term}' absent from visible text",
            bad_default is None and bad_custom is None,
            "leaked" if (bad_default or bad_custom) else "clean",
        ))
    # Verdict keys — match whole word (Scale/Hold not as substring of other word)
    for verdict_key in ("Scale", "Hold", "Watch", "Reduce", "Cut"):
        pattern = _re2.compile(rf'\b{verdict_key}\b')
        bad_default = pattern.search(visible_default)
        bad_custom = pattern.search(visible_custom)
        results.append(_check(
            f"verdict enum key '{verdict_key}' not in visible text (localized?)",
            bad_default is None and bad_custom is None,
        ))

    # ─── C.6.4: Period label consistency cross-slide ───────────────────────
    # data_window_label appears in source notes + timeline subtitle. Verify
    # it propagates consistently (no drift like mixing "W01 W13" and
    # "Q1 2026" for the same concept).
    custom_window = "W14 W26 2026"
    window_count = visible_custom.count(custom_window)
    results.append(_check(
        f"data_window_label '{custom_window}' propagates consistently",
        window_count >= 2,  # at least cover + timeline subtitle
        f"found {window_count} occurrences",
    ))

    # ─── C.6.4: Internal slug pattern must not leak to any slide ───────────
    # Internal markers (исходник, ммх, mmx, tmp, double-hyphens, trailing
    # --N revision) must be cleaned by _sanitize_project_slug before
    # surfacing anywhere. Render with a deliberately dirty project_id.
    from engines.pptx_export import build_pptx as _build_with_adapter
    dirty_out = REPO / "tools" / "_brand_verify_slug.pptx"
    _build_with_adapter(
        {"diagnostics": {"mqs": {"score": 80}}},
        {"channels": [
            {"name": "TV", "spend": 10e6, "contribution": 15e6, "roi": 1.5},
            {"name": "Digital", "spend": 5e6, "contribution": 8e6, "roi": 1.6},
        ]},
        {"channels": [
            {"name": "TV", "current_spend": 10e6, "optimal_spend": 8e6, "mroi_current": 1.2},
            {"name": "Digital", "current_spend": 5e6, "optimal_spend": 7e6, "mroi_current": 1.8},
        ]},
        str(dirty_out),
        project_id="mmx-2021-2025-исходник-ммх-2404-26--4",
    )
    xml_dirty = _extract_slide_xml(dirty_out)
    slug_markers = (
        "исходник", "ммх-2404", "mmx-",
        "--", "-26-", "26--",
    )
    for marker in slug_markers:
        results.append(_check(
            f"slug marker '{marker}' not leaked to any slide",
            marker not in xml_dirty,
        ))
    try:
        os.remove(dirty_out)
    except OSError:
        pass

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
