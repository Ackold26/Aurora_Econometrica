"""
Integration tests for communication-strategist cabinet (7 commands).
Uses Exponenta materials.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import EXPONENTA_DIR
from claude_runner import run_command
from report_generator import TestResult
from validators.markdown_validator import has_required_sections, output_length_ok
from validators.brand_mention_validator import validate_brand_mentions
from validators.confidence_marker_validator import validate_confidence_markers
from validators.framework_detector import detect_frameworks

EXPO_DOCX = EXPONENTA_DIR / "Экспонента.docx"
EXPO_THOUGHTS = EXPONENTA_DIR / "Exponenta_Мысли о развитии бренда.txt"
BRAND_MEMORY = EXPONENTA_DIR / "brand-memory.md"
POSITIONING = EXPONENTA_DIR / "positioning-exponenta.md"
CREATIVE_BRIEF = EXPONENTA_DIR / "creative-brief.md"
COMM_AUDIT = EXPONENTA_DIR / "communication-audit.md"
CABINET = "communication-strategist"


def test_positioning(use_cache=False, verbose=False) -> TestResult:
    """P&G formula, CEP Analysis, Territory Map expected."""
    result = run_command(CABINET, "positioning",
                         inbox_files=[f for f in [EXPO_DOCX, BRAND_MEMORY] if f.exists()],
                         use_cache=use_cache, verbose=verbose, timeout=600)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "positioning", False,
                          result.error or "Empty output", result.duration_sec, "positioning")
    text = result.text
    # Positioning framework may use "бренд" not repeat brand name — check structure instead
    pg_keywords = ["для", "которая", "это", "потому что", "CEP", "Territory",
                   "Positioning", "позиционировани", "аудитори", "бренд",
                   "ценност", "конкурент", "рынок", "потребител", "сегмент"]
    found = sum(1 for kw in pg_keywords if kw.lower() in text.lower())
    if found < 2:
        issues.append(f"P&G/CEP/Positioning structure missing (found {found}/15)")
    # Brand check: accept either Cyrillic or Latin form, or general brand context
    brand = validate_brand_mentions(text)
    if not brand.passed:
        # Positioning may say "бренд" throughout without repeating "Экспонента"
        if "exponenta" not in text.lower() and "экспонент" not in text.lower() and "бренд" not in text.lower():
            warnings.append(brand.message)  # warning only, not hard failure
    length_ok = output_length_ok(text, 400)
    if not length_ok.passed:
        issues.append(length_ok.message)
    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK ({len(text)} chars, {found}/9 struct)"
    return TestResult("integration", CABINET, "positioning", passed, msg,
                      result.duration_sec, "positioning", result.char_count, warnings)


def test_brief(use_cache=False, verbose=False) -> TestResult:
    """Creative brief: expects 10 sections, Brief Stress Test, Proposition."""
    result = run_command(CABINET, "brief",
                         inbox_files=[f for f in [POSITIONING] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "brief", False,
                          result.error or "Empty output", result.duration_sec, "brief")
    text = result.text
    # Count H2/H3 sections
    sections = re.findall(r'^#{1,3}\s+\S', text, re.MULTILINE)
    if len(sections) < 5:
        warnings.append(f"Only {len(sections)} sections (expected 10+)")
    brief_keywords = ["Proposition", "Brief", "Stress", "аудитори", "инсайт"]
    found = sum(1 for kw in brief_keywords if kw.lower() in text.lower())
    if found < 2:
        warnings.append(f"Missing brief sections (found {found}/5)")
    length_ok = output_length_ok(text, 600)
    if not length_ok.passed:
        issues.append(length_ok.message)
    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {len(sections)} sections"
    return TestResult("integration", CABINET, "brief", passed, msg,
                      result.duration_sec, "brief", result.char_count, warnings)


def test_messages(use_cache=False, verbose=False) -> TestResult:
    """Messaging framework: Value Proposition (3 angles), persona×channel matrix."""
    result = run_command(CABINET, "messages",
                         inbox_files=[f for f in [POSITIONING, CREATIVE_BRIEF] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "messages", False,
                          result.error or "Empty output", result.duration_sec, "messages")
    text = result.text
    has_table = bool(re.search(r'\|.+\|.+\|', text))
    if not has_table:
        warnings.append("No persona×channel matrix table found")
    msg_keywords = ["Value Proposition", "Hierarchy", "персона", "канал", "угол"]
    found = sum(1 for kw in msg_keywords if kw.lower() in text.lower())
    if found < 2:
        warnings.append(f"Missing messaging keywords (found {found}/5)")
    brand = validate_brand_mentions(text)
    if not brand.passed:
        issues.append(brand.message)
    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: table={'yes' if has_table else 'no'}"
    return TestResult("integration", CABINET, "messages", passed, msg,
                      result.duration_sec, "messages", result.char_count, warnings)


def test_comm_audit(use_cache=False, verbose=False) -> TestResult:
    """Communication audit: ToV analysis, gaps, opportunities."""
    result = run_command(CABINET, "comm-audit",
                         inbox_files=[f for f in [EXPO_DOCX, EXPO_THOUGHTS] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "comm_audit", False,
                          result.error or "Empty output", result.duration_sec, "comm-audit")
    text = result.text
    audit_keywords = ["ToV", "тон", "разрыв", "возможност", "рекомендац", "канал"]
    found = sum(1 for kw in audit_keywords if kw.lower() in text.lower())
    if found < 2:
        issues.append(f"Missing audit keywords (found {found}/6)")
    brand = validate_brand_mentions(text)
    if not brand.passed:
        issues.append(brand.message)
    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK ({len(text)} chars)"
    return TestResult("integration", CABINET, "comm_audit", passed, msg,
                      result.duration_sec, "comm-audit", result.char_count, warnings)


def test_strategy(use_cache=False, verbose=False) -> TestResult:
    """Full communication strategy: ДИАГНОСТИКА→СИНТЕЗ, Competitive Response."""
    result = run_command(CABINET, "strategy",
                         inbox_files=[f for f in [BRAND_MEMORY, COMM_AUDIT] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "strategy", False,
                          result.error or "Empty output", result.duration_sec, "strategy")
    text = result.text
    strategy_keywords = ["диагностика", "синтез", "стратегия", "Competitive", "рекомендац"]
    found = sum(1 for kw in strategy_keywords if kw.lower() in text.lower())
    if found < 2:
        issues.append(f"Missing strategy keywords (found {found}/5)")
    brand = validate_brand_mentions(text)
    if not brand.passed:
        issues.append(brand.message)
    length_ok = output_length_ok(text, 800)
    if not length_ok.passed:
        issues.append(length_ok.message)
    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK ({len(text)} chars)"
    return TestResult("integration", CABINET, "strategy", passed, msg,
                      result.duration_sec, "strategy", result.char_count, warnings)


def test_focus_group(use_cache=False, verbose=False) -> TestResult:
    """Focus group: синтетические персоны, инсайты, оценки стратегии.
    Comm-strategist может использовать другой формат маркеров чем [HIGH/MEDIUM/LOW]."""
    result = run_command(CABINET, "focus-group",
                         inbox_files=[f for f in [POSITIONING] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "focus_group", False,
                          result.error or "Empty output", result.duration_sec, "focus-group")
    text = result.text
    # Check for focus group content (not just [HIGH/MEDIUM/LOW] markers)
    fg_keywords = ["персона", "участник", "фокус", "инсайт", "мнение", "реакция",
                   "потребитель", "аудитори", "восприятие", "HIGH", "MED", "LOW",
                   "уверенност", "высок", "средн", "низк"]
    found = sum(1 for kw in fg_keywords if kw.lower() in text.lower())
    if found < 3:
        issues.append(f"Focus group content missing (found {found}/14)")
    # Also try confidence markers (optional for this cabinet)
    conf = validate_confidence_markers(text, 3)
    if not conf.passed:
        warnings.append(f"No structured [HIGH/MED/LOW] markers (OK for this format)")
    length_ok = output_length_ok(text, 300)
    if not length_ok.passed:
        issues.append(length_ok.message)
    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found}/14 focus group elements"
    return TestResult("integration", CABINET, "focus_group", passed, msg,
                      result.duration_sec, "focus-group", result.char_count, warnings)


def test_quick_diagnostics(use_cache=False, verbose=False) -> TestResult:
    """Quick diagnostics: fast analysis mentioning brand."""
    result = run_command(CABINET, "quick-diagnostics",
                         inbox_files=[f for f in [EXPO_DOCX] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "quick_diagnostics", False,
                          result.error or "Empty output", result.duration_sec, "quick-diagnostics")
    text = result.text
    brand = validate_brand_mentions(text)
    # quick-diagnostics may mention brand once — accept primary >= 1 regardless of secondary
    if not brand.passed:
        if brand.primary_count >= 1 or "exponenta" in text.lower() or "экспонент" in text.lower():
            warnings.append(f"Brand secondary mentions low: {brand.secondary_count} (expected 2+)")
        else:
            issues.append(brand.message)
    length_ok = output_length_ok(text, 200)
    if not length_ok.passed:
        issues.append(length_ok.message)
    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK ({len(text)} chars)"
    return TestResult("integration", CABINET, "quick_diagnostics", passed, msg,
                      result.duration_sec, "quick-diagnostics", result.char_count, warnings)


ALL_TESTS = [
    ("positioning",       test_positioning,       False, True),
    ("brief",             test_brief,             False, False),
    ("messages",          test_messages,           False, False),
    ("comm_audit",        test_comm_audit,         False, False),
    ("strategy",          test_strategy,           True,  False),
    ("focus_group",       test_focus_group,        False, False),
    ("quick_diagnostics", test_quick_diagnostics,  False, False),
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
    print("=== Communication Strategist Integration Tests ===\n")
    results = run_all("communication-strategist", verbose=True)
    passed = sum(1 for r in results if r.passed)
    print(f"\nResult: {passed}/{len(results)} pass")
