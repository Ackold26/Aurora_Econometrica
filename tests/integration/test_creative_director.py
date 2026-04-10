"""
Integration tests for creative-director cabinet (8 commands).
Uses real Exponenta brand materials from EXPONENTA_DIR.
Each test calls Claude CLI and validates the output structure.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import EXPONENTA_DIR, MIN_CONFIDENCE_MARKERS, MIN_CREATIVE_CONCEPTS, MIN_AD_VARIANTS
from claude_runner import run_command, RunResult
from report_generator import TestResult
from validators.markdown_validator import has_required_sections, output_length_ok
from validators.framework_detector import detect_frameworks
from validators.brand_mention_validator import validate_brand_mentions
from validators.confidence_marker_validator import validate_confidence_markers
from validators.char_limit_validator import validate_ad_variants, count_hook_types

# ---------------------------------------------------------------------------
# Inbox file references
# ---------------------------------------------------------------------------

EXPO_DOCX = EXPONENTA_DIR / "Экспонента.docx"
EXPO_THOUGHTS = EXPONENTA_DIR / "Exponenta_Мысли о развитии бренда.txt"
BRAND_MEMORY = EXPONENTA_DIR / "brand-memory.md"
CREATIVE_BRIEF = EXPONENTA_DIR / "creative-brief.md"
CREATIVE_CONCEPTS = EXPONENTA_DIR / "creative-concepts.md"
COMM_AUDIT = EXPONENTA_DIR / "communication-audit.md"

CABINET = "creative-director"


# ---------------------------------------------------------------------------
# Individual test functions
# ---------------------------------------------------------------------------

def test_brand_memory(use_cache=False, verbose=False) -> TestResult:
    """
    /brand-memory: expects sections Personality, Voice & Tone, Positioning/Values.
    Must mention the brand name Экспонента.
    """
    result = run_command(
        CABINET, "brand-memory",
        inbox_files=[f for f in [EXPO_DOCX, EXPO_THOUGHTS] if f.exists()],
        use_cache=use_cache, verbose=verbose,
    )
    issues = []
    warnings = []

    if not result.passed_basic:
        return TestResult("integration", CABINET, "brand_memory", False,
                          result.error or "Empty output", result.duration_sec, "brand-memory")

    text = result.text
    # brand-memory produces H3 sections — check for keywords at any level
    sections = has_required_sections(text, ["Personality", "Voice"], level=3)
    if not sections.passed:
        # Fallback: just search for keywords in text (command may use any heading level)
        found_kw = sum(1 for kw in ["Personality", "Voice", "Positioning", "Values"]
                       if kw.lower() in text.lower())
        if found_kw < 2:
            issues.append(f"Missing brand-memory sections (found {found_kw}/4 keywords)")

    # Brand mentions — Exponenta appears in Latin or Cyrillic
    brand = validate_brand_mentions(text)
    # Also accept Latin "Exponenta" directly
    if not brand.passed and "exponenta" in text.lower():
        pass  # Latin form accepted
    elif not brand.passed:
        issues.append(brand.message)

    if len(text) < 500:
        issues.append(f"Output too short: {len(text)} chars")

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK ({len(text)} chars, brand OK)"
    return TestResult("integration", CABINET, "brand_memory", passed, msg,
                      result.duration_sec, "brand-memory", result.char_count, warnings)


def test_comm_audit(use_cache=False, verbose=False) -> TestResult:
    """
    /comm-audit: expects analysis sections about what brand communicates,
    gaps, and recommendations. Must mention brand.
    """
    result = run_command(
        CABINET, "comm-audit",
        inbox_files=[f for f in [EXPO_DOCX, EXPO_THOUGHTS] if f.exists()],
        use_cache=use_cache, verbose=verbose,
    )
    issues = []

    if not result.passed_basic:
        return TestResult("integration", CABINET, "comm_audit", False,
                          result.error or "Empty output", result.duration_sec, "comm-audit")

    text = result.text
    # Expect some analysis structure
    length_ok = output_length_ok(text, 400)
    if not length_ok.passed:
        issues.append(length_ok.message)

    brand = validate_brand_mentions(text)
    if not brand.passed:
        issues.append(brand.message)

    # Check for audit-relevant keywords
    audit_keywords = ["анализ", "аудит", "коммуникаци", "рекомендац", "разрыв"]
    found_keywords = sum(1 for kw in audit_keywords if kw.lower() in text.lower())
    if found_keywords < 2:
        issues.append(f"Missing audit keywords (found {found_keywords}/5)")

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK ({len(text)} chars)"
    return TestResult("integration", CABINET, "comm_audit", passed, msg,
                      result.duration_sec, "comm-audit", result.char_count)


def test_creative(use_cache=False, verbose=False) -> TestResult:
    """
    /creative: expects >= 3 creative concepts with Score and HumanKind ratings.
    Must mention brand.
    """
    result = run_command(
        CABINET, "creative",
        inbox_files=[f for f in [CREATIVE_BRIEF] if f.exists()],
        use_cache=use_cache, verbose=verbose,
    )
    issues = []
    warnings = []

    if not result.passed_basic:
        return TestResult("integration", CABINET, "creative", False,
                          result.error or "Empty output", result.duration_sec, "creative")

    text = result.text

    # Count concepts
    import re
    concept_count = len(re.findall(r'(?:Концепция|Concept|Идея)\s*[№#]?\s*\d+', text, re.IGNORECASE))
    if concept_count < MIN_CREATIVE_CONCEPTS:
        # Alternative: count H2/H3 headers with concept-like names
        h_count = len(re.findall(r'^#{1,3}\s+.{5,}', text, re.MULTILINE))
        if h_count >= MIN_CREATIVE_CONCEPTS:
            concept_count = h_count
        else:
            issues.append(f"Too few concepts: {concept_count} (need {MIN_CREATIVE_CONCEPTS}+)")

    # Check for Score / HumanKind framework mentions
    frameworks = detect_frameworks(text, CABINET)
    found_names = [f.framework for f in frameworks if f.found]
    if "Score" not in found_names and "score" not in text.lower():
        warnings.append("Score rating not found in output")
    if "HumanKind" not in found_names and "human" not in text.lower():
        warnings.append("HumanKind rating not found in output")

    brand = validate_brand_mentions(text)
    if not brand.passed:
        issues.append(brand.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {concept_count} concepts, frameworks detected"
    return TestResult("integration", CABINET, "creative", passed, msg,
                      result.duration_sec, "creative", result.char_count, warnings)


def test_ad_variants(use_cache=False, verbose=False) -> TestResult:
    """
    /ad-variants: expects >= 10 ad variants for VK platform.
    Headlines <= 33 chars. Multiple hook types.
    """
    result = run_command(
        CABINET, "ad-variants",
        inbox_files=[f for f in [CREATIVE_BRIEF] if f.exists()],
        use_cache=use_cache, verbose=verbose,
        timeout=600,  # ad-variants generates 10+ variants — needs extra time
    )
    issues = []
    warnings = []

    if not result.passed_basic:
        return TestResult("integration", CABINET, "ad_variants", False,
                          result.error or "Empty output", result.duration_sec, "ad-variants")

    text = result.text
    char_result = validate_ad_variants(text, "vk")

    if char_result.total_variants < MIN_AD_VARIANTS:
        warnings.append(f"Only {char_result.total_variants} variants (expected {MIN_AD_VARIANTS}+)")

    if char_result.violations:
        issues.append(f"{len(char_result.violations)} char limit violations: {char_result.message}")

    hooks = count_hook_types(text)
    if len(hooks) < 2:
        warnings.append(f"Only {len(hooks)} hook types detected (expected 3+)")

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {char_result.total_variants} variants, {len(hooks)} hook types"
    return TestResult("integration", CABINET, "ad_variants", passed, msg,
                      result.duration_sec, "ad-variants", result.char_count, warnings)


def test_focus_group(use_cache=False, verbose=False) -> TestResult:
    """
    /focus-group: expects confidence markers [HIGH/MEDIUM/LOW],
    AIDA scoring table, and a limitations section.
    """
    result = run_command(
        CABINET, "focus-group",
        inbox_files=[f for f in [CREATIVE_CONCEPTS] if f.exists()],
        use_cache=use_cache, verbose=verbose,
    )
    issues = []
    warnings = []

    if not result.passed_basic:
        return TestResult("integration", CABINET, "focus_group", False,
                          result.error or "Empty output", result.duration_sec, "focus-group")

    text = result.text
    conf = validate_confidence_markers(text, MIN_CONFIDENCE_MARKERS)
    if not conf.passed:
        fg_keywords = ["персона", "участник", "реакция", "мнение", "потребитель",
                       "концепция", "оценка", "восприятие", "аудитори"]
        found_fg = sum(1 for kw in fg_keywords if kw.lower() in text.lower())
        if found_fg < 2:
            issues.append(conf.message)
        else:
            warnings.append(f"No [HIGH/MED/LOW] but FG content found ({found_fg}/9)")

    # Check for AIDA or scoring table
    import re
    has_table = bool(re.search(r'\|.+\|.+\|', text))
    if not has_table:
        warnings.append("No markdown table found (expected AIDA scoring)")

    has_limitation = any(kw in text.lower() for kw in ["ограничени", "limitation", "валидац"])
    if not has_limitation:
        warnings.append("No limitations/validation disclaimer found")

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {conf.total_markers} markers, tables={'yes' if has_table else 'no'}"
    return TestResult("integration", CABINET, "focus_group", passed, msg,
                      result.duration_sec, "focus-group", result.char_count, warnings)


def test_format_creative(use_cache=False, verbose=False) -> TestResult:
    """
    /format-creative: expects creative adapted for TV/OOH/Digital/Print.
    Should describe hooks for each format.
    """
    result = run_command(
        CABINET, "format-creative",
        inbox_files=[f for f in [CREATIVE_BRIEF] if f.exists()],
        use_cache=use_cache, verbose=verbose,
    )
    issues = []

    if not result.passed_basic:
        return TestResult("integration", CABINET, "format_creative", False,
                          result.error or "Empty output", result.duration_sec, "format-creative")

    text = result.text
    format_keywords = ["TV", "OOH", "Digital", "Print", "видео", "наружн", "диджитал"]
    found = sum(1 for kw in format_keywords if kw.lower() in text.lower())
    if found < 2:
        issues.append(f"Missing format types (found {found}, need 2+)")

    length_ok = output_length_ok(text, 400)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found} formats found"
    return TestResult("integration", CABINET, "format_creative", passed, msg,
                      result.duration_sec, "format-creative", result.char_count)


def test_strategy(use_cache=False, verbose=False) -> TestResult:
    """
    /strategy: expects strategic conclusions mentioning brand.
    Expensive — often skipped.
    """
    result = run_command(
        CABINET, "strategy",
        inbox_files=[f for f in [EXPO_DOCX] if f.exists()],
        use_cache=use_cache, verbose=verbose,
    )
    issues = []

    if not result.passed_basic:
        return TestResult("integration", CABINET, "strategy", False,
                          result.error or "Empty output", result.duration_sec, "strategy")

    text = result.text
    brand = validate_brand_mentions(text)
    if not brand.passed:
        issues.append(brand.message)

    length_ok = output_length_ok(text, 600)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK ({len(text)} chars, brand OK)"
    return TestResult("integration", CABINET, "strategy", passed, msg,
                      result.duration_sec, "strategy", result.char_count)


def test_cycle(use_cache=False, verbose=False) -> TestResult:
    """
    /cycle: full creative cycle. Expects 5 phases, Score >= 7, top-3 concepts.
    Very expensive (~5 min).
    """
    result = run_command(
        CABINET, "cycle",
        inbox_files=[f for f in [EXPO_DOCX, EXPO_THOUGHTS] if f.exists()],
        use_cache=use_cache, verbose=verbose,
        timeout=600,  # 10 min for cycle
    )
    issues = []
    warnings = []

    if not result.passed_basic:
        return TestResult("integration", CABINET, "cycle", False,
                          result.error or "Empty output", result.duration_sec, "cycle")

    text = result.text
    brand = validate_brand_mentions(text)
    if not brand.passed:
        issues.append(brand.message)

    # Check for phase markers
    import re
    phases = len(re.findall(r'(?:Фаза|Phase|INTAKE|INSIGHT|IDEATION|EVALUATE|ART\s*DIRECT)', text, re.IGNORECASE))
    if phases < 3:
        warnings.append(f"Only {phases} phase markers found (expected 5)")

    # Check for Score mentions
    scores = re.findall(r'Score[:\s]+(\d+)', text, re.IGNORECASE)
    if scores:
        try:
            max_score = max(int(s) for s in scores)
            if max_score < 7:
                warnings.append(f"Max Score {max_score} < 7")
        except ValueError:
            pass
    else:
        warnings.append("No Score ratings found")

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {phases} phases, {len(text)} chars"
    return TestResult("integration", CABINET, "cycle", passed, msg,
                      result.duration_sec, "cycle", result.char_count, warnings)


# ---------------------------------------------------------------------------
# run_all — entry point called by runner.py
# ---------------------------------------------------------------------------

# All tests: (name, function, is_expensive, is_smoke)
ALL_TESTS = [
    ("brand_memory",    test_brand_memory,    False, True),   # smoke
    ("comm_audit",      test_comm_audit,      False, False),
    ("creative",        test_creative,        False, False),
    ("ad_variants",     test_ad_variants,     False, False),
    ("focus_group",     test_focus_group,     False, False),
    ("format_creative", test_format_creative, False, False),
    ("strategy",        test_strategy,        True,  False),  # expensive
    ("cycle",           test_cycle,           True,  False),  # expensive
]


def run_all(
    cabinet_id: str,
    smoke_mode: bool = False,
    skip_expensive: bool = False,
    use_cache: bool = False,
    verbose: bool = False,
    commands_filter: list = None,
    delay_sec: int = 0,
) -> list[TestResult]:
    """Run integration tests for creative-director. Called by runner.py."""
    import time
    results = []

    for name, fn, is_expensive, is_smoke in ALL_TESTS:
        # Apply filters
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

        if delay_sec > 0:
            time.sleep(delay_sec)

    return results


if __name__ == "__main__":
    print("=== Creative Director Integration Tests ===\n")
    results = run_all("creative-director", verbose=True)
    passed = sum(1 for r in results if r.passed)
    print(f"\nResult: {passed}/{len(results)} pass")
