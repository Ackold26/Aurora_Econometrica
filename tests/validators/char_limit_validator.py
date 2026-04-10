"""
Validate character limits in ad-variants output.
Limits from creative-director/.claude/commands/ad-variants.md
"""
import re
from dataclasses import dataclass, field


PLATFORM_LIMITS = {
    "google": {"headline": 30, "description": 90},
    "meta": {"headline": 40, "text": 125},
    "vk": {"headline": 33, "text": 220},
    "telegram": {"text": 160},
}


@dataclass
class AdVariantIssue:
    variant_num: int
    platform: str
    field: str
    actual_len: int
    max_len: int
    text_preview: str


@dataclass
class CharLimitResult:
    passed: bool
    total_variants: int
    violations: list[AdVariantIssue] = field(default_factory=list)
    message: str = ""


def validate_ad_variants(text: str, expected_platform: str = "vk") -> CharLimitResult:
    """
    Parse ad variants from markdown output and check character limits.
    Looks for numbered variants or heading-separated variants.
    """
    limits = PLATFORM_LIMITS.get(expected_platform.lower(), PLATFORM_LIMITS["vk"])
    violations = []

    # Extract headline candidates (bold text or lines after "Заголовок:")
    headline_patterns = [
        r'(?:Заголовок|Headline|Title)[:\s]+\*{0,2}(.+?)\*{0,2}$',
        r'^\*{1,2}([^*\n]{5,60})\*{1,2}$',
        r'(?:^|\n)#+\s+Вариант\s+\d+[:\s]*(.+?)$',
    ]
    description_patterns = [
        r'(?:Описание|Description|Текст)[:\s]+(.+?)$',
        r'(?:Тело|Body)[:\s]+(.+?)$',
    ]

    # Simple approach: find all lines that look like ad headlines/descriptions
    lines = text.splitlines()
    variant_count = 0
    headline_limit = limits.get("headline", 33)
    text_limit = limits.get("text", limits.get("description", 220))

    for i, line in enumerate(lines):
        line = line.strip()
        # Detect headline markers
        if re.match(r'(?:Заголовок|Headline|Title)\s*:', line, re.IGNORECASE):
            content = re.sub(r'^(?:Заголовок|Headline|Title)\s*:\s*', '', line, flags=re.IGNORECASE)
            content = content.strip('*_ ')
            if content and len(content) > 3:
                variant_count += 1
                if len(content) > headline_limit:
                    violations.append(AdVariantIssue(
                        variant_num=variant_count,
                        platform=expected_platform,
                        field="headline",
                        actual_len=len(content),
                        max_len=headline_limit,
                        text_preview=content[:50],
                    ))
        # Detect description/text markers
        elif re.match(r'(?:Описание|Description|Текст объявления|Текст)\s*:', line, re.IGNORECASE):
            content = re.sub(r'^[^:]+:\s*', '', line).strip('*_ ')
            if content and len(content) > 3:
                if len(content) > text_limit:
                    violations.append(AdVariantIssue(
                        variant_num=variant_count,
                        platform=expected_platform,
                        field="text",
                        actual_len=len(content),
                        max_len=text_limit,
                        text_preview=content[:50],
                    ))

    # Count variants (look for "Вариант N" or "## N")
    v_count = len(re.findall(r'(?:Вариант\s+\d+|^\d+\.\s+)', text, re.MULTILINE))
    if v_count > variant_count:
        variant_count = v_count

    passed = len(violations) == 0
    msg = f"{variant_count} variants found, {len(violations)} violations"
    if violations:
        msg += f": {[(v.field, v.actual_len, f'>{v.max_len}') for v in violations[:3]]}"

    return CharLimitResult(
        passed=passed,
        total_variants=variant_count,
        violations=violations,
        message=msg,
    )


def count_hook_types(text: str) -> dict[str, int]:
    """Count how many different hook types are present in ad variants output."""
    hooks = {
        "Проблема": r'(?:Проблема|Боль|Pain)',
        "Решение": r'(?:Решение|Solution)',
        "Выгода": r'(?:Выгода|Бенефит|Benefit)',
        "FOMO": r'FOMO',
        "Страх": r'(?:Страх|Fear)',
        "Любопытство": r'(?:Любопытство|Curiosity)',
        "Соц.доказательство": r'(?:Социальн|Social\s+proof|Доверие)',
    }
    found = {}
    for name, pattern in hooks.items():
        if re.search(pattern, text, re.IGNORECASE):
            found[name] = 1
    return found
