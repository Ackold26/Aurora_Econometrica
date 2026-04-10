"""
Markdown structure validation utilities.
"""
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ValidationResult:
    passed: bool
    message: str
    detail: Optional[str] = None


def extract_headings(text: str) -> dict[int, list[str]]:
    """Extract all headings from markdown text, grouped by level (1-6)."""
    headings: dict[int, list[str]] = {i: [] for i in range(1, 7)}
    for line in text.splitlines():
        m = re.match(r'^(#{1,6})\s+(.+)', line.strip())
        if m:
            level = len(m.group(1))
            headings[level].append(m.group(2).strip())
    return headings


def has_required_sections(text: str, required: list[str], level: int = 2) -> ValidationResult:
    """Check that text contains required H{level} sections (case-insensitive partial match)."""
    headings = extract_headings(text)
    found_headings = [h.lower() for h in headings[level]]
    missing = []
    for req in required:
        if not any(req.lower() in h for h in found_headings):
            missing.append(req)
    if missing:
        return ValidationResult(
            passed=False,
            message=f"Missing H{level} sections: {missing}",
            detail=f"Found: {headings[level]}",
        )
    return ValidationResult(passed=True, message=f"All {len(required)} required sections found")


def count_sections(text: str, level: int) -> int:
    """Count number of headings at given level."""
    return len(extract_headings(text)[level])


def has_keywords(text: str, keywords: list[str], min_count: int = 1) -> ValidationResult:
    """Check that text contains at least min_count of the given keywords."""
    found = [kw for kw in keywords if kw.lower() in text.lower()]
    if len(found) < min_count:
        missing = [kw for kw in keywords if kw not in found]
        return ValidationResult(
            passed=False,
            message=f"Found {len(found)}/{len(keywords)} keywords (need {min_count})",
            detail=f"Missing: {missing[:5]}",
        )
    return ValidationResult(passed=True, message=f"Found {len(found)}/{len(keywords)} keywords")


def count_list_items(text: str) -> int:
    """Count total number of list items (- or numbered)."""
    lines = text.splitlines()
    count = 0
    for line in lines:
        stripped = line.strip()
        if re.match(r'^[-*+]\s', stripped) or re.match(r'^\d+\.\s', stripped):
            count += 1
    return count


def extract_tables(text: str) -> list[str]:
    """Extract all markdown tables as raw strings."""
    tables = []
    lines = text.splitlines()
    current_table = []
    in_table = False
    for line in lines:
        if '|' in line:
            current_table.append(line)
            in_table = True
        else:
            if in_table and len(current_table) >= 2:
                tables.append('\n'.join(current_table))
            current_table = []
            in_table = False
    if in_table and len(current_table) >= 2:
        tables.append('\n'.join(current_table))
    return tables


def output_length_ok(text: str, min_chars: int = 200) -> ValidationResult:
    """Check output is not too short."""
    if len(text) < min_chars:
        return ValidationResult(
            passed=False,
            message=f"Output too short: {len(text)} chars (min {min_chars})",
        )
    return ValidationResult(passed=True, message=f"Output length OK: {len(text)} chars")
