"""
Integration tests for lawyer-advertising cabinet (4 key tests from 11 commands).
Uses sample-ad-text.md with 5 embedded violations of 38-ФЗ.
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

AD_TEXT = SYNTHETIC_DIR / "sample-ad-text.md"
CABINET = "lawyer-advertising"


def test_qa(use_cache=False, verbose=False) -> TestResult:
    """
    /qa: Compliance Report, >= 3 violations detected, Financial Risk Score, 38-ФЗ references.
    """
    result = run_command(CABINET, "qa",
                         inbox_files=[f for f in [AD_TEXT] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "qa", False,
                          result.error or "Empty output", result.duration_sec, "qa")
    text = result.text

    # Check for 38-ФЗ and compliance references
    law_keywords = ["38-ФЗ", "закон о рекламе", "ФАС", "нарушение", "статья"]
    found_law = sum(1 for kw in law_keywords if kw.lower() in text.lower())
    if found_law < 2:
        issues.append(f"38-ФЗ/compliance references missing (found {found_law}/5)")

    # Count violations found
    violation_keywords = ["суперлатив", "гарантия", "erid", "ОРД", "маркировка",
                          "лучший", "единственный", "медицинск", "№1"]
    found_violations = sum(1 for kw in violation_keywords if kw.lower() in text.lower())
    if found_violations < 3:
        issues.append(f"Too few violations detected (found {found_violations}, expected 3+)")

    # Check for risk score
    risk_keywords = ["Risk Score", "Financial Risk", "штраф", "санкц", "стоимость риска"]
    found_risk = sum(1 for kw in risk_keywords if kw.lower() in text.lower())
    if found_risk < 1:
        warnings.append("No Financial Risk Score found")

    frameworks = detect_frameworks(text, CABINET)
    found_fw = [f.framework for f in frameworks if f.found]
    if not found_fw:
        warnings.append("No advertising law frameworks detected")

    length_ok = output_length_ok(text, 400)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found_violations} violations, law refs={found_law}"
    return TestResult("integration", CABINET, "qa", passed, msg,
                      result.duration_sec, "qa", result.char_count, warnings)


def test_qa_pharma(use_cache=False, verbose=False) -> TestResult:
    """
    /qa-фарма: For BAD/supplement with superlative claims.
    Expects disclaimer requirement and "Лучший" flagged as violation.
    """
    result = run_command(CABINET, "qa-фарма",
                         inbox_files=[f for f in [AD_TEXT] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "qa_pharma", False,
                          result.error or "Empty output", result.duration_sec, "qa-фарма")
    text = result.text

    pharma_keywords = ["БАД", "дисклеймер", "предупреждение", "не является лекарств",
                       "суперлатив", "лучший", "38-ФЗ"]
    found = sum(1 for kw in pharma_keywords if kw.lower() in text.lower())
    if found < 2:
        issues.append(f"Pharma-specific keywords missing (found {found}/7)")

    length_ok = output_length_ok(text, 200)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found}/7 pharma elements"
    return TestResult("integration", CABINET, "qa_pharma", passed, msg,
                      result.duration_sec, "qa-фарма", result.char_count, warnings)


def test_qa_finance(use_cache=False, verbose=False) -> TestResult:
    """
    /qa-финансы: Financial ad compliance. Guaranteed returns flagged, ст. 28.
    """
    result = run_command(CABINET, "qa-финансы",
                         inbox_files=[f for f in [AD_TEXT] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "qa_finance", False,
                          result.error or "Empty output", result.duration_sec, "qa-финансы")
    text = result.text

    finance_keywords = ["гарантия доходности", "ст. 28", "ЦБ РФ", "финанс", "инвестиц", "доход"]
    found = sum(1 for kw in finance_keywords if kw.lower() in text.lower())
    if found < 2:
        issues.append(f"Finance compliance keywords missing (found {found}/6)")

    length_ok = output_length_ok(text, 200)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found}/6 finance elements"
    return TestResult("integration", CABINET, "qa_finance", passed, msg,
                      result.duration_sec, "qa-финансы", result.char_count, warnings)


def test_qa_template(use_cache=False, verbose=False) -> TestResult:
    """
    /qa-template: Template with Dangerous→Safe table.
    """
    result = run_command(CABINET, "qa-template",
                         inbox_files=[],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "qa_template", False,
                          result.error or "Empty output", result.duration_sec, "qa-template")
    text = result.text

    # Expect a table with danger/safe columns
    has_table = bool(re.search(r'\|.+\|.+\|', text))
    if not has_table:
        issues.append("No Dangerous→Safe table found")

    template_keywords = ["опасно", "безопасно", "шаблон", "чек-лист", "пример"]
    found = sum(1 for kw in template_keywords if kw.lower() in text.lower())
    if found < 2:
        warnings.append(f"Template structure weak (found {found}/5)")

    length_ok = output_length_ok(text, 200)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: table found"
    return TestResult("integration", CABINET, "qa_template", passed, msg,
                      result.duration_sec, "qa-template", result.char_count, warnings)


ALL_TESTS = [
    ("qa",          test_qa,          False, True),
    ("qa_pharma",   test_qa_pharma,   False, False),
    ("qa_finance",  test_qa_finance,  False, False),
    ("qa_template", test_qa_template, False, False),
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
    print("=== Lawyer-Advertising Integration Tests ===\n")
    results = run_all("lawyer-advertising", verbose=True)
    passed = sum(1 for r in results if r.passed)
    print(f"\nResult: {passed}/{len(results)} pass")
