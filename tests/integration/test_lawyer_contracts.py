"""
Integration tests for lawyer-contracts cabinet (5 key tests from 13 commands).
Uses synthetic sample-contract.md with 3 embedded Red Flags.
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

CONTRACT = SYNTHETIC_DIR / "sample-contract.md"
CABINET = "lawyer-contracts"


def test_contract(use_cache=False, verbose=False) -> TestResult:
    """
    /contract: Risk Heatmap, >= 3 risks found, references to ГК РФ.
    This is the main contract review command.
    """
    result = run_command(CABINET, "contract",
                         inbox_files=[f for f in [CONTRACT] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "contract", False,
                          result.error or "Empty output", result.duration_sec, "contract")
    text = result.text

    # Expect risk-related content
    risk_keywords = ["риск", "red flag", "heatmap", "ГК РФ", "статья", "ответственност"]
    found = sum(1 for kw in risk_keywords if kw.lower() in text.lower())
    if found < 3:
        issues.append(f"Missing risk analysis keywords (found {found}/6)")

    # Check that the 3 embedded red flags were found
    red_flags = ["одностороннее изменение", "неограниченная ответственность", "автопролонгация",
                 "односторонн", "безлимит", "90 дн"]
    found_flags = sum(1 for flag in red_flags if flag.lower() in text.lower())
    if found_flags < 2:
        warnings.append(f"Only {found_flags}/3 planted Red Flags detected")

    # Framework detection
    frameworks = detect_frameworks(text, CABINET)
    found_fw = [f.framework for f in frameworks if f.found]
    if not found_fw:
        warnings.append("No legal frameworks detected (IACCM, Severity, etc.)")

    length_ok = output_length_ok(text, 400)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found_flags} flags, {len(found_fw)} frameworks"
    return TestResult("integration", CABINET, "contract", passed, msg,
                      result.duration_sec, "contract", result.char_count, warnings)


def test_contract_checklist(use_cache=False, verbose=False) -> TestResult:
    """
    /contract-checklist: Checklist with pass/fail items, Critical/Important weights.
    """
    result = run_command(CABINET, "contract-checklist",
                         inbox_files=[f for f in [CONTRACT] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "contract_checklist", False,
                          result.error or "Empty output", result.duration_sec, "contract-checklist")
    text = result.text

    # Expect checklist structure (checkboxes or pass/fail)
    checklist_markers = re.findall(r'(?:✅|❌|\[x\]|\[ \]|PASS|FAIL|Да|Нет)', text, re.IGNORECASE)
    if len(checklist_markers) < 3:
        issues.append(f"No checklist structure found ({len(checklist_markers)} markers)")

    severity_keywords = ["critical", "important", "критич", "важн", "высок", "низк"]
    found = sum(1 for kw in severity_keywords if kw.lower() in text.lower())
    if found < 1:
        warnings.append("No severity/priority levels found")

    length_ok = output_length_ok(text, 300)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {len(checklist_markers)} checklist items"
    return TestResult("integration", CABINET, "contract_checklist", passed, msg,
                      result.duration_sec, "contract-checklist", result.char_count, warnings)


def test_contract_counter(use_cache=False, verbose=False) -> TestResult:
    """
    /contract-counter: BATNA, 2-3 redline variants.
    """
    result = run_command(CABINET, "contract-counter",
                         inbox_files=[f for f in [CONTRACT] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "contract_counter", False,
                          result.error or "Empty output", result.duration_sec, "contract-counter")
    text = result.text

    counter_keywords = ["BATNA", "редакц", "вариант", "контрпредложени", "альтернатив"]
    found = sum(1 for kw in counter_keywords if kw.lower() in text.lower())
    if found < 2:
        issues.append(f"Missing counter-proposal content (found {found}/5)")

    length_ok = output_length_ok(text, 300)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: BATNA and counter-proposals found"
    return TestResult("integration", CABINET, "contract_counter", passed, msg,
                      result.duration_sec, "contract-counter", result.char_count, warnings)


def test_contract_risks(use_cache=False, verbose=False) -> TestResult:
    """
    /contract-риски: Red flags prioritization.
    """
    result = run_command(CABINET, "contract-риски",
                         inbox_files=[f for f in [CONTRACT] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "contract_risks", False,
                          result.error or "Empty output", result.duration_sec, "contract-риски")
    text = result.text

    risk_keywords = ["риск", "красный флаг", "red flag", "приоритет", "критич", "опасн"]
    found = sum(1 for kw in risk_keywords if kw.lower() in text.lower())
    if found < 2:
        issues.append(f"Missing risk keywords (found {found}/6)")

    # Should find the 3 planted red flags
    planted = ["одностороннее", "ответственности", "пролонгац"]
    found_planted = sum(1 for p in planted if p.lower() in text.lower())
    if found_planted < 2:
        warnings.append(f"Only {found_planted}/3 planted risks detected")

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found_planted}/3 risks detected"
    return TestResult("integration", CABINET, "contract_risks", passed, msg,
                      result.duration_sec, "contract-риски", result.char_count, warnings)


def test_contract_template(use_cache=False, verbose=False) -> TestResult:
    """
    /contract-услуги: Template generation for services contract.
    Expects contract structure with ГК РФ references.
    """
    result = run_command(CABINET, "contract-услуги",
                         inbox_files=[],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "contract_template", False,
                          result.error or "Empty output", result.duration_sec, "contract-услуги")
    text = result.text

    template_keywords = ["предмет", "стороны", "оплата", "ответственность", "расторжение",
                         "договор", "услуг", "исполнитель", "заказчик"]
    found = sum(1 for kw in template_keywords if kw.lower() in text.lower())
    if found < 2:
        issues.append(f"Missing contract sections (found {found}/9)")

    gk_keywords = ["ГК РФ", "гражданский кодекс", "статья"]
    found_gk = sum(1 for kw in gk_keywords if kw.lower() in text.lower())
    if found_gk < 1:
        warnings.append("No ГК РФ references found")

    length_ok = output_length_ok(text, 200)  # Template may be concise
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found} sections, ГК РФ={'yes' if found_gk else 'no'}"
    return TestResult("integration", CABINET, "contract_template", passed, msg,
                      result.duration_sec, "contract-услуги", result.char_count, warnings)


ALL_TESTS = [
    ("contract",           test_contract,          False, True),
    ("contract_checklist", test_contract_checklist, False, False),
    ("contract_counter",   test_contract_counter,   False, False),
    ("contract_risks",     test_contract_risks,     False, False),
    ("contract_template",  test_contract_template,  False, False),
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
            if verbose:
                print(f"    [SKIP] {name} (expensive)")
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
    print("=== Lawyer-Contracts Integration Tests ===\n")
    results = run_all("lawyer-contracts", verbose=True)
    passed = sum(1 for r in results if r.passed)
    print(f"\nResult: {passed}/{len(results)} pass")
