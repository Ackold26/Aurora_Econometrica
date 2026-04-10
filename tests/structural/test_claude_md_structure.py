"""
Structural Test 2: CLAUDE.md content validation for all 7 cabinets.
Checks that each cabinet's CLAUDE.md has required sections and key framework keywords.
No Claude CLI calls — runs instantly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CABINETS_ROOT, CABINETS

sys.path.insert(0, str(Path(__file__).parent.parent / "validators"))
from markdown_validator import has_required_sections, has_keywords


# Required H2 sections and keywords for each cabinet CLAUDE.md
CABINET_REQUIREMENTS: dict[str, dict] = {
    "creative-director": {
        "required_sections": ["Роль и границы", "Slash-команды", "Стандарт качества"],
        "required_keywords": ["Score", "HumanKind", "AIDA", "ELM", "Cannes"],
        "min_keywords": 4,
    },
    "communication-strategist": {
        "required_sections": ["Роль и границы", "Slash-команды"],
        "required_keywords": ["Ehrenberg-Bass", "CEP", "Binet", "60/40", "JTBD"],
        "min_keywords": 4,
    },
    "lawyer-contracts": {
        "required_sections": ["Роль и границы", "Slash-команды"],
        "required_keywords": ["IACCM", "Severity", "ГК РФ", "Red Flags", "BATNA"],
        "min_keywords": 4,
    },
    "lawyer-claims": {
        "required_sections": ["Роль и границы", "Slash-команды"],
        "required_keywords": ["IRAC", "Пленум", "333", "Decision Tree"],
        "min_keywords": 3,
    },
    "lawyer-advertising": {
        "required_sections": ["Роль и границы", "Slash-команды"],
        "required_keywords": ["38-ФЗ", "ОРД", "erid", "ФАС", "14.3"],
        "min_keywords": 4,
    },
    "media-analyst": {
        "required_sections": ["Роль и границы", "Slash-команды"],
        "required_keywords": ["Tier-1", "Action Title", "Pyramid", "Верификация", "McKinsey"],
        "min_keywords": 3,
    },
    "communication-analyst": {
        "required_sections": ["Роль и границы", "Slash-команды"],
        "required_keywords": ["AMEC", "PESO", "Barcelona", "AVE"],
        "min_keywords": 3,
    },
}


def test_required_sections(cabinet_id: str) -> tuple[bool, str]:
    path = CABINETS_ROOT / cabinet_id / "CLAUDE.md"
    if not path.exists():
        return False, "CLAUDE.md not found"
    text = path.read_text(encoding="utf-8")
    reqs = CABINET_REQUIREMENTS[cabinet_id]["required_sections"]
    result = has_required_sections(text, reqs, level=2)
    return result.passed, result.message + (f" | {result.detail}" if result.detail else "")


def test_required_keywords(cabinet_id: str) -> tuple[bool, str]:
    path = CABINETS_ROOT / cabinet_id / "CLAUDE.md"
    if not path.exists():
        return False, "CLAUDE.md not found"
    text = path.read_text(encoding="utf-8")
    reqs = CABINET_REQUIREMENTS[cabinet_id]
    result = has_keywords(text, reqs["required_keywords"], min_count=reqs["min_keywords"])
    return result.passed, result.message + (f" | {result.detail}" if result.detail else "")


def test_has_slash_commands_section(cabinet_id: str) -> tuple[bool, str]:
    """Verify that CLAUDE.md contains actual slash command definitions."""
    path = CABINETS_ROOT / cabinet_id / "CLAUDE.md"
    if not path.exists():
        return False, "CLAUDE.md not found"
    text = path.read_text(encoding="utf-8")
    import re
    slash_cmds = re.findall(r'`/\w', text)
    count = len(slash_cmds)
    if count == 0:
        return False, "No slash command references found in CLAUDE.md"
    return True, f"Found {count} slash command references"


def test_minimum_word_count(cabinet_id: str) -> tuple[bool, str]:
    """CLAUDE.md must have meaningful content (min word count)."""
    path = CABINETS_ROOT / cabinet_id / "CLAUDE.md"
    if not path.exists():
        return False, "CLAUDE.md not found"
    text = path.read_text(encoding="utf-8")
    words = len(text.split())
    if words < 300:
        return False, f"CLAUDE.md too short: {words} words (min 300)"
    return True, f"CLAUDE.md word count OK: {words} words"


def run_all(cabinet_id: str) -> list[tuple[str, bool, str]]:
    tests = [
        ("required_sections", test_required_sections),
        ("required_keywords", test_required_keywords),
        ("slash_commands_defined", test_has_slash_commands_section),
        ("minimum_word_count", test_minimum_word_count),
    ]
    results = []
    for name, fn in tests:
        passed, msg = fn(cabinet_id)
        results.append((name, passed, msg))
    return results


if __name__ == "__main__":
    print("=== CLAUDE.md Structure Tests ===\n")
    total_pass = total_fail = 0
    for cabinet_id in CABINETS:
        print(f"  [{cabinet_id}]")
        results = run_all(cabinet_id)
        for name, passed, msg in results:
            status = "PASS" if passed else "FAIL"
            print(f"    [{status}] {name}: {msg}")
            if passed:
                total_pass += 1
            else:
                total_fail += 1
        print()
    print(f"Result: {total_pass} pass, {total_fail} fail")
