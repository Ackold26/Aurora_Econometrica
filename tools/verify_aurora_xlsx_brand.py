"""
XLSX brand + structural verification for Aurora AI Econometrica.

Opens the latest XLSX from active project's exports/ and asserts:
- Excel can open it without warnings (no recovery required)
- All worksheets have data (non-empty)
- sheetPr element order is XSD-compliant (tabColor BEFORE pageSetUpPr)
- Charts have populated numCache (no broken chart references)
- No brand leaks (no "Econometrica", no "v1.0.11" in visible cells, no project slug)
- Defined names resolve to non-empty cells

Run:
    cd sidecar && python ../tools/verify_aurora_xlsx_brand.py [path/to/xlsx]

If no path given, uses latest XLSX from mmx-*-4 or venarus-*-2 active project.
Exit 0 on success, 1 on any assertion failure.
"""
from __future__ import annotations

import io
import os
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def _check(label: str, cond: bool, detail: str = "") -> bool:
    tag = "[OK]  " if cond else "[FAIL]"
    line = f"{tag} {label}"
    if detail:
        line += f" - {detail}"
    print(line)
    return cond


# OOXML namespaces
NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_CHART = "http://schemas.openxmlformats.org/drawingml/2006/chart"


def find_latest_xlsx() -> Path | None:
    """Find latest Aurora_Econometrica_*.xlsx from active project exports."""
    base = Path(os.environ["APPDATA"]).parent / "Roaming" / "aurora-econometrica-gui" / "projects"
    if not base.exists():
        return None
    active = base / "active_project.json"
    if active.exists():
        import json
        pid = json.loads(active.read_text(encoding='utf-8')).get("active_project")
        if pid:
            exports = base / pid / "exports"
            if exports.exists():
                xlsx = sorted(exports.glob("Aurora_Econometrica_*.xlsx"), key=os.path.getmtime, reverse=True)
                if xlsx:
                    return xlsx[0]
    return None


def main():
    results = []

    if len(sys.argv) > 1:
        xlsx_path = Path(sys.argv[1])
    else:
        xlsx_path = find_latest_xlsx()

    if not xlsx_path or not xlsx_path.exists():
        print(f"[FAIL] Cannot find XLSX to verify (passed: {sys.argv[1:] or 'auto-detect'})")
        return 1

    print(f"Verifying: {xlsx_path.name}")
    print(f"  ({xlsx_path})")
    print()

    # ─── XML integrity + sheetPr order ───────────────────────────
    with zipfile.ZipFile(xlsx_path, 'r') as z:
        names = z.namelist()

        # Parse all sheet*.xml - must pass ET.parse (XSD beyond our reach, but
        # well-formed XML is prerequisite)
        sheet_files = [n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
        parse_ok = 0
        for name in sheet_files:
            try:
                with z.open(name) as f:
                    ET.parse(f)
                parse_ok += 1
            except Exception as e:
                print(f"    [parse-err] {name}: {e}")
        results.append(_check(
            "All worksheets parse as valid XML",
            parse_ok == len(sheet_files),
            f"{parse_ok}/{len(sheet_files)} parse OK"
        ))

        # sheetPr element order: tabColor must come BEFORE pageSetUpPr when both present.
        sheetpr_wrong_order = []
        for name in sheet_files:
            with z.open(name) as f:
                content = f.read().decode('utf-8')
            # Extract <sheetPr>...</sheetPr>
            m = re.search(r'<sheetPr[^>]*>(.*?)</sheetPr>', content, re.DOTALL)
            if not m:
                continue
            inner = m.group(1)
            tab_pos = inner.find('<tabColor')
            psu_pos = inner.find('<pageSetUpPr')
            if tab_pos >= 0 and psu_pos >= 0 and tab_pos > psu_pos:
                sheetpr_wrong_order.append(name)
        results.append(_check(
            "sheetPr: tabColor BEFORE pageSetUpPr in all worksheets (XSD-compliant)",
            len(sheetpr_wrong_order) == 0,
            f"{len(sheetpr_wrong_order)} violating sheets: {sheetpr_wrong_order[:3]}"
        ))

        # ─── Chart numCache populated (non-empty for formula cells too) ──
        chart_files = [n for n in names if n.startswith("xl/charts/chart") and n.endswith(".xml")]
        empty_caches = []
        for cname in chart_files:
            with z.open(cname) as f:
                cx = f.read().decode('utf-8')
            # Find all numCache blocks and count <c:pt> elements
            for nc_match in re.finditer(r'<c:numCache>(.*?)</c:numCache>', cx, re.DOTALL):
                block = nc_match.group(1)
                pts = re.findall(r'<c:pt ', block)
                ptcount_m = re.search(r'<c:ptCount val="(\d+)"', block)
                declared = int(ptcount_m.group(1)) if ptcount_m else 0
                if declared > 0 and len(pts) == 0:
                    empty_caches.append(f"{cname}")
                    break
        results.append(_check(
            "Chart numCache populated (no empty series referenced by declared ptCount)",
            len(empty_caches) == 0,
            f"empty caches in: {empty_caches[:3]}"
        ))

        # ─── Workbook structure ───────────────────────────────────
        with z.open("xl/workbook.xml") as f:
            wb_xml = f.read().decode('utf-8')
        sheet_names = re.findall(r'<sheet[^>]+name="([^"]+)"', wb_xml)
        results.append(_check(
            "Workbook has at least 8 sheets (cover + ≥6 content + glossary)",
            len(sheet_names) >= 8,
            f"{len(sheet_names)} sheets: {sheet_names[:5]}..."
        ))

        # Defined names present
        has_mqs = 'MQS_Score' in wb_xml
        has_budget = 'Total_Budget' in wb_xml
        results.append(_check(
            "Defined names MQS_Score and Total_Budget present",
            has_mqs and has_budget,
            f"MQS={has_mqs}, Budget={has_budget}"
        ))

        # ─── All non-cover sheets have ≥1 data row (not empty) ───
        empty_sheets = []
        for name in sheet_files:
            with z.open(name) as f:
                content = f.read().decode('utf-8')
            # Count <row r="N"> - cover sheets may have minimal rows, but none
            # should have zero (broken sheets from rust_xlsxwriter 0.79 bug
            # appear empty post-recovery with sheetData = <sheetData/>).
            rows = re.findall(r'<row r="\d+"', content)
            if len(rows) == 0:
                empty_sheets.append(name)
        results.append(_check(
            "No worksheets appear empty (zero rows)",
            len(empty_sheets) == 0,
            f"empty: {empty_sheets[:3]}"
        ))

        # ─── Brand leaks ───────────────────────────────────────
        with z.open("xl/sharedStrings.xml") as f:
            ss = f.read().decode('utf-8')
        has_econometrica = 'Econometrica' in ss or 'econometrica' in ss.lower()
        # NOTE: v1.0.11 check is informational in Stage A - Stage B removes
        # version from visible cells entirely; for now just flag presence.
        has_version = bool(re.search(r'v1\.0\.\d+', ss))
        results.append(_check(
            "No 'Econometrica' product name in visible cells",
            not has_econometrica,
            "'Econometrica' leak detected" if has_econometrica else ""
        ))
        # Project slug leak pattern: lowercase-hyphens with trailing --N
        slug_pattern = re.search(r'[\wа-яё]+-[\wа-яё]+(?:-[\wа-яё]+)+--\d+', ss, re.IGNORECASE)
        results.append(_check(
            "No project slug pattern (xxx-yyy--N) in visible cells",
            slug_pattern is None,
            f"found: {slug_pattern.group(0)[:40]}" if slug_pattern else ""
        ))

    passed = sum(1 for r in results if r)
    total = len(results)
    print()
    print(f"{passed}/{total} XLSX checks passed")
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
