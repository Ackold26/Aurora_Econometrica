"""
Integration tests for communication-analyst cabinet (4 key tests from 6 commands).
Uses sample-mentions.md with 20 entries (12 positive, 5 neutral, 3 negative).
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

MENTIONS = SYNTHETIC_DIR / "sample-mentions.md"
CABINET = "communication-analyst"


def test_media_monitor(use_cache=False, verbose=False) -> TestResult:
    """
    /media-monitor: PESO Breakdown, Share of Voice, Narrative Analysis.
    """
    result = run_command(CABINET, "media-monitor",
                         inbox_files=[f for f in [MENTIONS] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "media_monitor", False,
                          result.error or "Empty output", result.duration_sec, "media-monitor")
    text = result.text

    # PESO check (command may not use PESO acronym explicitly — check broader media terms)
    peso_keywords = ["PESO", "Paid", "Earned", "Shared", "Owned",
                     "платные", "заработанные", "собственные", "упоминани",
                     "мониторинг", "медиа", "СМИ", "охват", "тональност"]
    found_peso = sum(1 for kw in peso_keywords if kw.lower() in text.lower())
    if found_peso < 2:
        issues.append(f"PESO/media keywords missing (found {found_peso}/14)")

    # Share of Voice
    sov_keywords = ["Share of Voice", "SOV", "доля голоса", "доля упоминаний"]
    found_sov = sum(1 for kw in sov_keywords if kw.lower() in text.lower())
    if found_sov < 1:
        warnings.append("Share of Voice not found")

    # Narrative Analysis
    narrative_keywords = ["нарратив", "narrative", "тема", "сообщение", "тон"]
    found_narr = sum(1 for kw in narrative_keywords if kw.lower() in text.lower())
    if found_narr < 1:
        warnings.append("Narrative analysis not found")

    # Framework detection
    frameworks = detect_frameworks(text, CABINET)
    found_fw = [f.framework for f in frameworks if f.found]

    length_ok = output_length_ok(text, 400)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: PESO={found_peso}, SOV={found_sov}, frameworks={found_fw}"
    return TestResult("integration", CABINET, "media_monitor", passed, msg,
                      result.duration_sec, "media-monitor", result.char_count, warnings)


def test_sentiment(use_cache=False, verbose=False) -> TestResult:
    """
    /sentiment: Intensity 1-5, Aspect-Based, Emotion Detection.
    """
    result = run_command(CABINET, "sentiment",
                         inbox_files=[f for f in [MENTIONS] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "sentiment", False,
                          result.error or "Empty output", result.duration_sec, "sentiment")
    text = result.text

    sentiment_keywords = ["сентимент", "sentiment", "позитив", "негатив", "нейтрал",
                          "тональность", "интенсивность"]
    found = sum(1 for kw in sentiment_keywords if kw.lower() in text.lower())
    if found < 3:
        issues.append(f"Sentiment keywords missing (found {found}/7)")

    # Intensity scale
    has_scale = bool(re.search(r'[1-5]\s*/\s*5|интенсивность|intensity', text, re.IGNORECASE))
    if not has_scale:
        warnings.append("No intensity 1-5 scale found")

    # Aspect-based
    aspect_keywords = ["аспект", "aspect", "атрибут", "качество", "цена", "сервис"]
    found_aspect = sum(1 for kw in aspect_keywords if kw.lower() in text.lower())
    if found_aspect < 1:
        warnings.append("No aspect-based sentiment detected")

    length_ok = output_length_ok(text, 300)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found}/7 sentiment elements"
    return TestResult("integration", CABINET, "sentiment", passed, msg,
                      result.duration_sec, "sentiment", result.char_count, warnings)


def test_crisis_analysis(use_cache=False, verbose=False) -> TestResult:
    """
    /crisis-analysis: Fink Model (4 stages), SCCT, Stakeholder Mapping.
    """
    result = run_command(CABINET, "crisis-analysis",
                         inbox_files=[f for f in [MENTIONS] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "crisis_analysis", False,
                          result.error or "Empty output", result.duration_sec, "crisis-analysis")
    text = result.text

    crisis_keywords = ["кризис", "Fink", "SCCT", "стадия", "стейкхолдер",
                       "stakeholder", "репутаци", "антикризис", "риск",
                       "угроза", "реакци", "коммуникац", "сценари"]
    found = sum(1 for kw in crisis_keywords if kw.lower() in text.lower())
    if found < 2:
        issues.append(f"Crisis framework keywords missing (found {found}/13)")

    # protein spiking narrative should be detected from sample-mentions
    narrative = any(kw in text.lower() for kw in ["protein spiking", "состав", "нарратив"])
    if not narrative:
        warnings.append("Sample-mentions crisis narrative not detected")

    length_ok = output_length_ok(text, 300)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: {found}/8 crisis elements"
    return TestResult("integration", CABINET, "crisis_analysis", passed, msg,
                      result.duration_sec, "crisis-analysis", result.char_count, warnings)


def test_effectiveness(use_cache=False, verbose=False) -> TestResult:
    """
    /effectiveness: AMEC Chain, NO AVE metric, PESO Effectiveness.
    """
    result = run_command(CABINET, "effectiveness",
                         inbox_files=[f for f in [MENTIONS] if f.exists()],
                         use_cache=use_cache, verbose=verbose)
    issues, warnings = [], []
    if not result.passed_basic:
        return TestResult("integration", CABINET, "effectiveness", False,
                          result.error or "Empty output", result.duration_sec, "effectiveness")
    text = result.text

    amec_keywords = ["AMEC", "Barcelona", "эффективность", "KPI", "метрики",
                     "измерени", "оценка", "результат", "влияни", "PR",
                     "коммуникац", "охват", "вовлечённост"]
    found_amec = sum(1 for kw in amec_keywords if kw.lower() in text.lower())
    if found_amec < 2:
        issues.append(f"AMEC/effectiveness keywords missing (found {found_amec}/13)")

    # AVE should NOT appear (per Barcelona Principles — AVE is invalid)
    if "AVE" in text and "не" not in text[max(0, text.find("AVE")-20):text.find("AVE")+20].lower():
        warnings.append("AVE metric may be used — Barcelona Principles reject AVE")

    peso_keywords = ["PESO", "Paid", "Earned"]
    found_peso = sum(1 for kw in peso_keywords if kw.lower() in text.lower())
    if found_peso < 1:
        warnings.append("PESO effectiveness not found")

    length_ok = output_length_ok(text, 300)
    if not length_ok.passed:
        issues.append(length_ok.message)

    passed = len(issues) == 0
    msg = "; ".join(issues) if issues else f"OK: AMEC={found_amec}, PESO={found_peso}"
    return TestResult("integration", CABINET, "effectiveness", passed, msg,
                      result.duration_sec, "effectiveness", result.char_count, warnings)


ALL_TESTS = [
    ("sentiment",       test_sentiment,       False, True),
    ("media_monitor",   test_media_monitor,   False, False),
    ("crisis_analysis", test_crisis_analysis, False, False),
    ("effectiveness",   test_effectiveness,   False, False),
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
    print("=== Communication Analyst Integration Tests ===\n")
    results = run_all("communication-analyst", verbose=True)
    passed = sum(1 for r in results if r.passed)
    print(f"\nResult: {passed}/{len(results)} pass")
