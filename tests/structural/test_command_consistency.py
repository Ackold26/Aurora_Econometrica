"""
Structural Test 3: Cross-validate cabinet.rs ↔ .claude/commands/*.md.
Parses the Rust source to extract hardcoded commands, then checks that
each command in Rust has a matching .md file, and vice versa.
No Claude CLI calls — runs instantly.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CABINETS_ROOT, CABINET_RS, CABINETS


def parse_commands_from_rust() -> dict[str, list[str]]:
    """
    Parse cabinet.rs to extract the hardcoded command lists.
    Looks for patterns like: ("/command", "Label", "Group"),
    grouped by cabinet match arm.
    """
    if not CABINET_RS.exists():
        return {}

    text = CABINET_RS.read_text(encoding="utf-8")
    result: dict[str, list[str]] = {}

    # Find each match arm: "cabinet-id" => vec![...]
    cabinet_blocks = re.findall(
        r'"([\w-]+)"\s*=>\s*vec!\[(.*?)\]',
        text,
        re.DOTALL,
    )

    for cabinet_id, block in cabinet_blocks:
        # Extract all ("/command", ...) tuples
        commands = re.findall(r'"\s*(/[\w\-а-яёА-ЯЁ]+)\s*"', block)
        # Strip leading slash for comparison with file names
        result[cabinet_id] = [cmd.lstrip("/") for cmd in commands]

    return result


def test_rust_matches_config(cabinet_id: str) -> tuple[bool, str]:
    """Commands in cabinet.rs must match commands in config.py."""
    rust_cmds = parse_commands_from_rust()
    if cabinet_id not in rust_cmds:
        return False, f"Cabinet '{cabinet_id}' not found in cabinet.rs"

    rust_set = set(rust_cmds[cabinet_id])
    config_set = set(CABINETS[cabinet_id]["commands"])

    in_rust_not_config = rust_set - config_set
    in_config_not_rust = config_set - rust_set

    issues = []
    if in_rust_not_config:
        issues.append(f"In Rust but not config: {sorted(in_rust_not_config)}")
    if in_config_not_rust:
        issues.append(f"In config but not Rust: {sorted(in_config_not_rust)}")

    if issues:
        return False, "; ".join(issues)
    return True, f"{len(rust_set)} commands match between Rust and config"


def test_rust_commands_have_md_files(cabinet_id: str) -> tuple[bool, str]:
    """Every command in cabinet.rs must have a .md file."""
    rust_cmds = parse_commands_from_rust()
    if cabinet_id not in rust_cmds:
        return False, f"Cabinet '{cabinet_id}' not found in cabinet.rs"

    commands_dir = CABINETS_ROOT / cabinet_id / ".claude" / "commands"
    missing = []
    for cmd in rust_cmds[cabinet_id]:
        if not (commands_dir / f"{cmd}.md").exists():
            missing.append(f"{cmd}.md")

    if missing:
        return False, f"Rust commands without .md: {missing}"
    return True, f"All {len(rust_cmds[cabinet_id])} Rust commands have .md files"


def test_md_files_have_rust_commands(cabinet_id: str) -> tuple[bool, str]:
    """Every .md file must have a corresponding command in cabinet.rs."""
    rust_cmds = parse_commands_from_rust()
    if cabinet_id not in rust_cmds:
        return False, f"Cabinet '{cabinet_id}' not found in cabinet.rs"

    commands_dir = CABINETS_ROOT / cabinet_id / ".claude" / "commands"
    if not commands_dir.exists():
        return True, "No commands dir (skipped)"

    rust_set = set(rust_cmds[cabinet_id])
    orphans = []
    for md_file in commands_dir.glob("*.md"):
        if md_file.stem not in rust_set:
            orphans.append(md_file.name)

    if orphans:
        return False, f"Orphan .md files (not in Rust): {orphans}"
    return True, "All .md files have matching Rust commands"


def test_all_commands_start_with_slash_in_rust() -> tuple[bool, str]:
    """All command strings in cabinet.rs must start with '/'."""
    if not CABINET_RS.exists():
        return False, "cabinet.rs not found"

    text = CABINET_RS.read_text(encoding="utf-8")
    # Find all ("...") in vec! blocks — should start with /
    in_vec_blocks = re.findall(
        r'"([\w-]+)"\s*=>\s*vec!\[(.*?)\]',
        text, re.DOTALL
    )

    bad = []
    for _, block in in_vec_blocks:
        # All first-position strings in tuples
        candidates = re.findall(r'\("([^"]+)"', block)
        for c in candidates:
            if not c.startswith("/"):
                bad.append(c)

    if bad:
        return False, f"Commands not starting with '/': {bad[:5]}"
    return True, "All Rust commands start with '/'"


def run_all(cabinet_id: str) -> list[tuple[str, bool, str]]:
    tests = [
        ("rust_matches_config", lambda: test_rust_matches_config(cabinet_id)),
        ("rust_commands_have_md", lambda: test_rust_commands_have_md_files(cabinet_id)),
        ("md_files_have_rust", lambda: test_md_files_have_rust_commands(cabinet_id)),
    ]
    results = []
    for name, fn in tests:
        passed, msg = fn()
        results.append((name, passed, msg))
    return results


if __name__ == "__main__":
    print("=== Command Consistency Tests (cabinet.rs ↔ .md files) ===\n")

    # Global test
    passed, msg = test_all_commands_start_with_slash_in_rust()
    status = "PASS" if passed else "FAIL"
    print(f"  [GLOBAL] [{status}] all_commands_start_with_slash: {msg}\n")

    total_pass = 1 if passed else 0
    total_fail = 0 if passed else 1

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
