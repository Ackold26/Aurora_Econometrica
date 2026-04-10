"""
Integration tests for lawyer-claims cabinet (4 key tests from 9 commands).
Uses sample-pretension.md with 500K debt + 0.5%/day penalty.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SYNTHETIC_DIR
from claude_runner import run_command
from report_generator import TestResult
from validators.markdown_validator import output_length_ok
from validators.framework_detector import detect_frameworks

PRETENSION = SYNTHETIC_DIR / "sample-pretension.md"
CABINET = "lawyer-claims"


def test_pretension_analyze(use_cache=False, verbose=False) -> TestResult:
    """
    /pretension-analyze: IRAC structure, Decision Tree with 4 scenarios.
    """
    result = run_command(CABINET, "pretension-analyze",
                         inbox_files=[f for f in [PRETENSION] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "pretension_analyze", False,
                          result.error or "Empty output", result.duration_sec, "pretension-analyze")
    text = result.text

    # IRAC detection
    irac_keywords = ["IRAC", "Issue", "Rule", "Application", "Conclusion",
                     "проблема", "норма", "применение", "вывод"]
    found_irac = sum(1 for kw in irac_keywords if kw.lower() in text.lower())
    if found_irac < 2:
        issues.append(f"IRAC structure missing (found {found_irac}/9 keywords)")

    # Decision Tree
    dt_keywords = ["Decision Tree", "сценарий", "вариант", "если", "ветка"]
    found_dt = sum(1 for kw in dt_keywords if kw.lower() in text.lower())
    if found_dt < 2:
        warnings.append(f"Decision Tree missing (found {found_dt}/5 keywords)")

    # Key facts from the pretension
    fact_keywords = ["500", "333", "неустойка", "просроч", "0,5%"]
    found_facts = sum(1 for kw in fact_keywords if kw in text)
    if found_facts < 2:
        warnings.append(f"Key financial facts missing (found {found_facts}/5)")

    length_ok = output_length_ok(text, 400)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: IRAC={found_irac}, DT={found_dt}"
    return TestResult("integration", CABINET, "pretension_analyze", passed, msg,
                      result.duration_sec, "pretension-analyze", result.char_count, warnings)


def test_pretension_write(use_cache=False, verbose=False) -> TestResult:
    """
    /pretension-write: Generate a pretension with IRAC structure,
    penalty calculation (ст. 333 ГК), demand section.
    """
    result = run_command(CABINET, "pretension-write",
                         inbox_files=[f for f in [PRETENSION] if f.exists()],  # needs inbox materials
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "pretension_write", False,
                          result.error or "Empty output", result.duration_sec, "pretension-write")
    text = result.text

    # Expect pretension document structure (broader keywords)
    pretension_keywords = ["претензия", "требуем", "уведомляем", "неустойка", "статья",
                           "требование", "задолженность", "нарушение", "ГК РФ", "срок"]
    found = sum(1 for kw in pretension_keywords if kw.lower() in text.lower())
    if found < 3:
        issues.append(f"Missing pretension structure (found {found}/10)")

    length_ok = output_length_ok(text, 300)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK ({len(text)} chars)"
    return TestResult("integration", CABINET, "pretension_write", passed, msg,
                      result.duration_sec, "pretension-write", result.char_count, warnings)


def test_nda_draft(use_cache=False, verbose=False) -> TestResult:
    """
    /nda-draft: NDA structure with definition of CI, term, obligations.
    """
    result = run_command(CABINET, "nda-draft",
                         inbox_files=[],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "nda_draft", False,
                          result.error or "Empty output", result.duration_sec, "nda-draft")
    text = result.text

    nda_keywords = ["конфиденциал", "NDA", "раскрытие", "обязательств", "срок", "стороны"]
    found = sum(1 for kw in nda_keywords if kw.lower() in text.lower())
    if found < 3:
        issues.append(f"NDA structure missing (found {found}/6)")

    length_ok = output_length_ok(text, 400)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found}/6 NDA sections"
    return TestResult("integration", CABINET, "nda_draft", passed, msg,
                      result.duration_sec, "nda-draft", result.char_count, warnings)


def test_settlement_plan(use_cache=False, verbose=False) -> TestResult:
    """
    /settlement-plan: BATNA, Timeline Risk, settlement options.
    """
    result = run_command(CABINET, "settlement-plan",
                         inbox_files=[f for f in [PRETENSION] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "settlement_plan", False,
                          result.error or "Empty output", result.duration_sec, "settlement-plan")
    text = result.text

    settlement_keywords = ["BATNA", "урегулирование", "мировое", "риск", "timeline", "сроки"]
    found = sum(1 for kw in settlement_keywords if kw.lower() in text.lower())
    if found < 2:
        issues.append(f"Settlement keywords missing (found {found}/6)")

    # Check for the ст. 333 mention (penalty reduction)
    if "333" not in text:
        warnings.append("ст. 333 ГК РФ not mentioned (penalty reduction)")

    length_ok = output_length_ok(text, 300)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found}/6 settlement elements"
    return TestResult("integration", CABINET, "settlement_plan", passed, msg,
                      result.duration_sec, "settlement-plan", result.char_count, warnings)


ALL_TESTS = [
    ("pretension_analyze", test_pretension_analyze, False, True),
    ("pretension_write",   test_pretension_write,   False, False),
    ("nda_draft",          test_nda_draft,           False, False),
    ("settlement_plan",    test_settlement_plan,     False, False),
]


def run_all(cabinet_id, smoke_mode=False, skip_expensive=False,
            use_cache=False, verbose=False, commands_filter=None, delay_sec=0) -> list[TestResult]:
    results = []
    for name, fn, is_expensive, is_smoke in ALL_TESTS:
        if commands_filter and name not in commands_filter:
            continue
        if smoke_mode and not is_smoke:
            continue
        if skip_expensive and is_expensive:
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
    print("=== Lawyer-Claims Integration Tests ===\n")
    results = run_all("lawyer-claims", verbose=True)
    passed = sum(1 for r in results if r.passed)
    print(f"\nResult: {passed}/{len(results)} pass")
