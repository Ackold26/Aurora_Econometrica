"""
Validate confidence markers in focus-group output.
"""
import re
from dataclasses import dataclass


@dataclass
class ConfidenceResult:
    passed: bool
    high_count: int
    medium_count: int
    low_count: int
    validate_count: int
    total_markers: int
    has_limitations_section: bool
    message: str


def validate_confidence_markers(text: str, min_markers: int = 3) -> ConfidenceResult:
    """
    Check that output contains proper confidence markers.
    Expected: [HIGH], [MEDIUM], [LOW], [VALIDATE]
    """
    high = len(re.findall(r'\[HIGH\]', text, re.IGNORECASE))
    medium = len(re.findall(r'\[MEDIUM\]', text, re.IGNORECASE))
    low = len(re.findall(r'\[LOW\]', text, re.IGNORECASE))
    validate = len(re.findall(r'\[VALIDATE\]', text, re.IGNORECASE))
    total = high + medium + low + validate

    has_limitations = bool(re.search(
        r'(Ограничени|Оговорки|генератор гипотез|не замен[аяет]\s+реальн)',
        text, re.IGNORECASE
    ))

    passed = total >= min_markers and has_limitations
    msg_parts = [f"{total} markers (HIGH:{high} MED:{medium} LOW:{low} VAL:{validate})"]
    if not has_limitations:
        msg_parts.append("MISSING limitations disclaimer")
    if total < min_markers:
        msg_parts.append(f"need >= {min_markers}")

    return ConfidenceResult(
        passed=passed,
        high_count=high,
        medium_count=medium,
        low_count=low,
        validate_count=validate,
        total_markers=total,
        has_limitations_section=has_limitations,
        message="; ".join(msg_parts),
    )
