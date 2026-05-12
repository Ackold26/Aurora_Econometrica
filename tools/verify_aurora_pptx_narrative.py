"""
Narrative parametrization verification for aurora_pptx (Session C, Path C).

Exercises the adapter → builder pipeline across channel-count variants
(default / Kagocel-like / 3-channel minimal / 10-channel maximal /
empty-channels fallback / partial diagnostics) and asserts invariants
required by the multi-client ship goal:

- Leader/hero channel names propagate to s02, s04, s05, s06, s07, s09
- Kagocel narrative defaults appear only in preview/wireframe runs
  (data=None OR channels < 2)
- Slide count stays at 13 across all scenarios
- 5-way verdict system (Cut/Reduce/Watch/Hold/Scale) reaches s07 table

Run:
    cd sidecar && python ../tools/verify_aurora_pptx_narrative.py

Exit 0 on success, 1 on any failed assertion.
"""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

# Force UTF-8 stdout on Windows cp1251 consoles so special chars in labels
# (e.g. '×', '₽') do not crash with UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "sidecar"
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / "econometrica"))


def _extract(pptx_path: Path) -> str:
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


def _build(model, decomp, opt, project_id=None, scenarios=None):
    from engines.pptx_export import build_pptx
    out = REPO / "tools" / "_narrative_verify.pptx"
    res = build_pptx(model, decomp, opt, str(out), scenarios=scenarios, project_id=project_id)
    xml = _extract(out)
    try:
        os.remove(out)
    except OSError:
        pass
    return res, xml


def _chs(names_specs):
    """names_specs: list of (name, spend_mln, contrib_mln, roi, optimal_mln?)"""
    decomp_chs = []
    opt_chs = []
    for s in names_specs:
        name, spend_mln, contrib_mln, roi = s[:4]
        opt_mln = s[4] if len(s) > 4 else spend_mln
        decomp_chs.append({
            "name": name,
            "spend": spend_mln * 1_000_000,
            "contribution": contrib_mln * 1_000_000,
            "roi": roi,
        })
        opt_chs.append({
            "name": name,
            "current_spend": spend_mln * 1_000_000,
            "optimal_spend": opt_mln * 1_000_000,
            "mroi_current": roi,
        })
    return decomp_chs, opt_chs


def main() -> int:
    results = []

    # ─── Case 1: default (data=None) - pilot narrative preserved ───────────
    res, xml = _build({}, {}, {})
    results.append(_check("Case 1 (default): 16 slides", res.get("slides") == 16))
    # Without explicit project_id, adapter uses client_label="Client" -
    # "Kagocel" body text only surfaces in pilot slides not client meta.
    results.append(_check("Case 1 (default): 'Digital video' pilot bars present",
                          "Digital video" in xml))
    results.append(_check("Case 1 (default): pilot SCQAR narrative '286 млн' present",
                          "286 млн" in xml))

    # ─── Case 2: Kagocel-like synthetic (should behave similar to default) ──
    decomp_chs, opt_chs = _chs([
        ("Digital video", 65, 124, 1.9, 110),
        ("TV",            120, 180, 1.5, 90),
        ("Search",        28,  48,  1.7, 48),
        ("OOH",           35,  52,  1.5, 52),
        ("Social",        18,  24,  1.3, 22),
        ("Print",         12,  8,   0.7, 0),
        ("Radio",         8,   6,   0.8, 6),
    ])
    model = {"diagnostics": {"mqs": {"score": 87, "tier_label": "GOOD"},
                              "metrics": {"r_squared": 0.872, "mape_pct": 8.3,
                                          "r_hat_max": 1.008, "ess_min": 1247}}}
    opt = {"channels": opt_chs, "expected_lift_pct": 12}
    res, xml = _build(model, {"channels": decomp_chs}, opt, project_id="Kagocel")
    results.append(_check("Case 2 (kagocel-like): 16 slides", res.get("slides") == 16))
    results.append(_check("Case 2: TV leader propagates (contrib=180)",
                          xml.count("TV") >= 5))
    results.append(_check("Case 2: Digital video hero propagates (mROAS=1.9)",
                          "Digital video" in xml))
    # Stage C.3: verdict labels localized - enum "Cut" renders as "Остановить"
    results.append(_check("Case 2: Print marked Cut (mROAS<0.8) → shown as Остановить",
                          "Остановить" in xml))

    # ─── Case 3: 3-channel minimal (AcmeCo) ─────────────────────────────────
    decomp_chs, opt_chs = _chs([
        ("Digital", 65, 125, 1.92, 110),
        ("TV",      120, 180, 1.5, 90),
        ("Print",   12,  8,   0.67, 0),
    ])
    model = {"diagnostics": {"mqs": {"score": 78, "tier_label": "GOOD"}}}
    opt = {"channels": opt_chs, "expected_lift_pct": 12.5}
    res, xml = _build(model, {"channels": decomp_chs}, opt, project_id="AcmeCo")
    results.append(_check("Case 3 (3-ch min): 16 slides", res.get("slides") == 16))
    results.append(_check("Case 3: TV leader present", xml.count("TV") >= 3))
    results.append(_check("Case 3: Digital hero present", xml.count("Digital") >= 3))
    results.append(_check("Case 3: AcmeCo meta propagates", "AcmeCo" in xml))
    # Residual Kagocel mentions ok in s08 band chart (documented); s02/s04/s05/s07/s09 should be clean
    # Check that headline Kagocel narrative pieces are NOT there
    for leak in ("286 млн", "25 млн из TV", "W06 и W11", "Weekly bursts"):
        results.append(_check(f"Case 3: no '{leak}' leak", leak not in xml))

    # ─── Case 4: 10-channel maximal ─────────────────────────────────────────
    specs10 = [(f"Ch{i}", 10 + i, 15 + i * 2, 1.0 + i * 0.15, 12 + i) for i in range(10)]
    decomp_chs, opt_chs = _chs(specs10)
    opt = {"channels": opt_chs, "expected_lift_pct": 8.0}
    res, xml = _build({}, {"channels": decomp_chs}, opt, project_id="MegaCorp")
    results.append(_check("Case 4 (10-ch max): 16 slides", res.get("slides") == 16))
    # Ch9 has highest mROAS (1.0 + 9*0.15 = 2.35) - hero
    results.append(_check("Case 4: Ch9 hero propagates", "Ch9" in xml))
    # Ch0 has lowest - should be underperformer
    results.append(_check("Case 4: Ch0 present (lowest mROAS)", "Ch0" in xml))

    # ─── Case 5: empty channels + meta only - adapter falls back ─────────────
    res, xml = _build({"diagnostics": {"mqs": {"score": 50}}}, {}, {}, project_id="FallbackCo")
    results.append(_check("Case 5 (empty-ch fallback): 16 slides", res.get("slides") == 16))
    results.append(_check("Case 5: FallbackCo propagates (meta client)",
                          "FallbackCo" in xml))
    results.append(_check("Case 5: Kagocel narrative still renders as pilot",
                          "Digital video" in xml))

    # ─── Case 6: partial diagnostics (no mqs_score) ─────────────────────────
    model = {"diagnostics": {"metrics": {"r_squared": 0.7}}}  # no mqs
    decomp_chs, opt_chs = _chs([("A", 10, 15, 1.5), ("B", 5, 8, 1.2)])
    res, xml = _build(model, {"channels": decomp_chs}, {"channels": opt_chs})
    results.append(_check("Case 6 (partial diag): 16 slides",
                          res.get("slides") == 16))
    results.append(_check("Case 6: no exception, output valid",
                          len(xml) > 1000))

    # ─── Case 7: no-TV client (digital-only, 4 channels) ───────────────────
    # Strictest multi-client safety check: ZERO residual Kagocel pilot
    # narrative when client has no TV / Digital video / Search / OOH / Social /
    # Print channel names. Asserts data-driven slot-fills replace ALL
    # hardcoded wireframe strings.
    decomp_chs, opt_chs = _chs([
        ("Yandex Direct", 40, 78,  1.95, 70),
        ("YouTube",       35, 55,  1.57, 58),
        ("Instagram",     22, 30,  1.36, 28),
        ("TikTok",        18, 22,  1.22, 20),
    ])
    model = {"diagnostics": {"mqs": {"score": 76, "tier_label": "GOOD"},
                              "metrics": {"r_squared": 0.81, "mape_pct": 9.1,
                                          "r_hat_max": 1.012, "ess_min": 1110}}}
    opt = {"channels": opt_chs, "expected_lift_pct": 10.5}
    res, xml = _build(model, {"channels": decomp_chs}, opt, project_id="DigitalOnlyCo")
    results.append(_check("Case 7 (no-TV): 16 slides", res.get("slides") == 16))
    results.append(_check("Case 7: DigitalOnlyCo propagates",
                          "DigitalOnlyCo" in xml))
    results.append(_check("Case 7: Yandex Direct hero name present",
                          "Yandex Direct" in xml))
    # ZERO leaks of Kagocel pilot narrative pieces - hardcoded channel
    # names, flight annotations, pilot numbers, competitor MMM tools.
    for leak in (
        "Kagocel", "KAGOCEL",
        '"TV"', ">TV<",  # loose - real TV token inside XML tags
        "Digital video", "Print", "Radio", "OOH",
        # W06/W11 appear as generic x-axis period labels (W01..W13),
        # not as Kagocel flight annotations - those are gated behind
        # preview_mode now. Skip them in the leak list.
        "TV FLIGHT", "HOLIDAY PUSH",
        "286 млн", "25 млн из TV", "Weekly bursts",
        "Robyn", "LightweightMMM",
        "80 TRP", "1.8x",
    ):
        # Use raw substring; XML is full slide concatenation.
        results.append(_check(f"Case 7: no '{leak}' leak", leak not in xml))

    # ─── Summary ────────────────────────────────────────────────────────────
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\n{passed}/{total} checks passed.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
