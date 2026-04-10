"""
Structural Test 1: File integrity for all 7 cabinets.
Checks that CLAUDE.md and all command .md files exist and are not empty.
No Claude CLI calls — runs instantly for free.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CABINETS_ROOT, CABINETS, MIN_COMMAND_FILE_BYTES, MIN_CLAUDE_MD_BYTES


def test_cabinet_claude_md_exists(cabinet_id: str) -> tuple[bool, str]:
    """CLAUDE.md must exist and be non-trivial."""
    path = CABINETS_ROOT / cabinet_id / "CLAUDE.md"
    if not path.exists():
        return False, f"CLAUDE.md not found: {path}"
    size = path.stat().st_size
    if size < MIN_CLAUDE_MD_BYTES:
        return False, f"CLAUDE.md too small: {size} bytes (min {MIN_CLAUDE_MD_BYTES})"
    return True, f"CLAUDE.md OK ({size} bytes, {len(path.read_text(encoding='utf-8').splitlines())} lines)"


def test_commands_dir_exists(cabinet_id: str) -> tuple[bool, str]:
    """The .claude/commands/ directory must exist."""
    path = CABINETS_ROOT / cabinet_id / ".claude" / "commands"
    if not path.exists():
        return False, f".claude/commands/ not found: {path}"
    return True, f".claude/commands/ exists"


def test_all_commands_have_md(cabinet_id: str) -> tuple[bool, str]:
    """Every command in config must have a corresponding .md file."""
    commands_dir = CABINETS_ROOT / cabinet_id / ".claude" / "commands"
    config = CABINETS[cabinet_id]
    missing = []
    for cmd in config["commands"]:
        md_file = commands_dir / f"{cmd}.md"
        if not md_file.exists():
            missing.append(f"{cmd}.md")
    if missing:
        return False, f"Missing command files: {missing}"
    return True, f"All {len(config['commands'])} command files found"


def test_no_orphan_commands(cabinet_id: str) -> tuple[bool, str]:
    """No .md files in commands/ without a matching entry in config."""
    commands_dir = CABINETS_ROOT / cabinet_id / ".claude" / "commands"
    if not commands_dir.exists():
        return True, "No commands dir (skipped)"
    config_commands = set(CABINETS[cabinet_id]["commands"])
    orphans = []
    for md_file in commands_dir.glob("*.md"):
        cmd_name = md_file.stem
        if cmd_name not in config_commands:
            orphans.append(md_file.name)
    if orphans:
        return False, f"Orphan .md files (not in config): {orphans}"
    return True, "No orphan command files"


def test_command_files_not_empty(cabinet_id: str) -> tuple[bool, str]:
    """Every command .md file must contain meaningful content."""
    commands_dir = CABINETS_ROOT / cabinet_id / ".claude" / "commands"
    config = CABINETS[cabinet_id]
    small_files = []
    for cmd in config["commands"]:
        md_file = commands_dir / f"{cmd}.md"
        if md_file.exists():
            size = md_file.stat().st_size
            if size < MIN_COMMAND_FILE_BYTES:
                small_files.append(f"{cmd}.md ({size}B)")
    if small_files:
        return False, f"Suspiciously small command files: {small_files}"
    return True, f"All {len(config['commands'])} command files have content"


def run_all(cabinet_id: str) -> list[tuple[str, bool, str]]:
    """Run all integrity tests for a single cabinet. Returns [(test_name, passed, message)]."""
    tests = [
        ("claude_md_exists", test_cabinet_claude_md_exists),
        ("commands_dir_exists", test_commands_dir_exists),
        ("all_commands_have_md", test_all_commands_have_md),
        ("no_orphan_commands", test_no_orphan_commands),
        ("command_files_not_empty", test_command_files_not_empty),
    ]
    results = []
    for name, fn in tests:
        passed, msg = fn(cabinet_id)
        results.append((name, passed, msg))
    return results


if __name__ == "__main__":
    print("=== File Integrity Tests ===\n")
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
