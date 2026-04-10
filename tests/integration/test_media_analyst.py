"""
Integration tests for media-analyst cabinet (4 key tests from 6 commands).
Uses synthetic data and prompt-based commands.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SYNTHETIC_DIR
from claude_runner import run_command
from report_generator import TestResult
from validators.markdown_validator import output_length_ok

MENTIONS = SYNTHETIC_DIR / "sample-mentions.md"
SLIDES = SYNTHETIC_DIR / "sample-slides.md"
CABINET = "media-analyst"


def test_action_title(use_cache=False, verbose=False) -> TestResult:
    """
    /action-title: WHAT+WHERE+WHY structure, 3 SO WHAT levels.
    Uses sample-slides.md (Q4 sales data with +34.9% YoY growth).
    """
    result = run_command(CABINET, "action-title",
                         inbox_files=[f for f in [SLIDES] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "action_title", False,
                          result.error or "Empty output", result.duration_sec, "action-title")
    text = result.text

    action_keywords = ["ЧТО", "КУДА", "ПОЧЕМУ", "SO WHAT", "вывод", "действие", "рост", "снижение"]
    found = sum(1 for kw in action_keywords if kw.lower() in text.lower())
    if found < 2:
        issues.append(f"Action Title structure missing (found {found}/8)")

    # Expect tiered analysis
    tier_keywords = ["Tier", "уровень", "первый", "второй", "третий", "1.", "2.", "3."]
    found_tiers = sum(1 for kw in tier_keywords if kw.lower() in text.lower())
    if found_tiers < 2:
        warnings.append(f"Multi-level SO WHAT missing (found {found_tiers}/8)")

    length_ok = output_length_ok(text, 200)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found}/8 action elements"
    return TestResult("integration", CABINET, "action_title", passed, msg,
                      result.duration_sec, "action-title", result.char_count, warnings)


def test_executive_summary(use_cache=False, verbose=False) -> TestResult:
    """
    /executive-summary: Pyramid/SCR structure, audience labels [CEO]/[CMO]/[BM].
    """
    result = run_command(CABINET, "executive-summary",
                         inbox_files=[f for f in [MENTIONS] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "executive_summary", False,
                          result.error or "Empty output", result.duration_sec, "executive-summary")
    text = result.text

    pyramid_keywords = ["Pyramid", "SCR", "Situation", "Complication", "Resolution",
                        "ситуация", "проблема", "решение"]
    found_pyramid = sum(1 for kw in pyramid_keywords if kw.lower() in text.lower())
    if found_pyramid < 2:
        warnings.append(f"Pyramid/SCR structure weak (found {found_pyramid}/8)")

    # Audience labels
    audience_labels = re.findall(r'\[(CEO|CMO|BM|CFO|COO)\]', text)
    if len(audience_labels) < 1:
        warnings.append("No audience labels [CEO]/[CMO]/[BM] found")

    length_ok = output_length_ok(text, 300)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found_pyramid} pyramid elements, {len(audience_labels)} labels"
    return TestResult("integration", CABINET, "executive_summary", passed, msg,
                      result.duration_sec, "executive-summary", result.char_count, warnings)


def test_bridges(use_cache=False, verbose=False) -> TestResult:
    """
    /bridges: >= 3 logical bridges/transitions between blocks.
    """
    result = run_command(CABINET, "bridges",
                         inbox_files=[f for f in [MENTIONS] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "bridges", False,
                          result.error or "Empty output", result.duration_sec, "bridges")
    text = result.text

    bridge_keywords = ["следовательно", "поэтому", "в результате", "причина", "следует",
                       "Causal", "bridge", "мост", "связка", "переход"]
    found = sum(1 for kw in bridge_keywords if kw.lower() in text.lower())
    if found < 2:
        issues.append(f"Bridge/logic chain keywords missing (found {found}/10)")

    length_ok = output_length_ok(text, 200)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found}/10 bridge elements"
    return TestResult("integration", CABINET, "bridges", passed, msg,
                      result.duration_sec, "bridges", result.char_count, warnings)


def test_analytics(use_cache=False, verbose=False) -> TestResult:
    """
    /analytics: Slide analysis with verification, data quality, sources.
    """
    result = run_command(CABINET, "analytics",
                         inbox_files=[f for f in [MENTIONS] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "analytics", False,
                          result.error or "Empty output", result.duration_sec, "analytics")
    text = result.text

    analytics_keywords = ["верификац", "источник", "данные", "анализ", "тренд", "инсайт"]
    found = sum(1 for kw in analytics_keywords if kw.lower() in text.lower())
    if found < 2:
        issues.append(f"Analytics keywords missing (found {found}/6)")

    length_ok = output_length_ok(text, 300)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK ({len(text)} chars)"
    return TestResult("integration", CABINET, "analytics", passed, msg,
                      result.duration_sec, "analytics", result.char_count, warnings)


ALL_TESTS = [
    ("action_title",      test_action_title,      False, True),
    ("executive_summary", test_executive_summary,  False, False),
    ("bridges",           test_bridges,            False, False),
    ("analytics",         test_analytics,          False, False),
]


def run_all(cabinet_id, smoke_mode=False, skip_expensive=False,
            use_cache=False, verbose=False, commands_filter=None, delay_sec=0) -> list[TestResult]:
    results = []
    for name, fn, is_expensive, is_smoke in ALL_TESTS:
        if commands_filter and name not in commands_filter:
            continue
        if smoke_mode and not is_smoke:
            continue
        if verbose:
            print(f"    [RUN] {name}...", end=" ", flush=True)
        result = fn(use_cache=use_cache, verbose=False)
        results.append(result)
        if verbose:
            status = "PASS" if result.passed else "FAIL"
            print(f"[{status}] {result.duration_sec:.1f}s — {result.message[:60]}")
        if delay_sec > 0 and len(results) < sum(1 for n, f, e, s in ALL_TESTS if not (smoke_mode and not s) and not (skip_expensive and e)):
            import time; time.sleep(delay_sec)
    return results


if __name__ == "__main__":
    print("=== Media Analyst Integration Tests ===\n")
    results = run_all("media-analyst", verbose=True)
    passed = sum(1 for r in results if r.passed)
    print(f"\nResult: {passed}/{len(results)} pass")
