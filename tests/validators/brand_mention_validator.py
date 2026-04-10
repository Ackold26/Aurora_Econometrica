"""
Validate that output mentions the expected brand/product from test materials.
"""
import re
from dataclasses import dataclass


# Brand names for Exponenta test materials
EXPONENTA_TERMS = [
    "Экспонента", "EXPONENTA", "Exponenta",
    "высокобелков", "белков", "протеин",
    "молоч",  # молочный, молочная
]

# Minimal brand mention check
BRAND_CONFIGS = {
    "exponenta": {
        "primary": ["Экспонента", "EXPONENTA", "Exponenta"],
        "secondary": EXPONENTA_TERMS,
        "min_primary": 1,
        "min_secondary": 2,
    },
}


@dataclass
class BrandMentionResult:
    passed: bool
    primary_count: int
    secondary_count: int
    message: str


def validate_brand_mentions(
    text: str,
    brand_config: str = "exponenta",
) -> BrandMentionResult:
    """Check that output properly references the brand from test materials."""
    config = BRAND_CONFIGS.get(brand_config)
    if not config:
        return BrandMentionResult(passed=True, primary_count=0, secondary_count=0,
                                   message="No brand config defined")

    primary_count = sum(
        len(re.findall(term, text, re.IGNORECASE))
        for term in config["primary"]
    )
    secondary_count = sum(
        len(re.findall(term, text, re.IGNORECASE))
        for term in config["secondary"]
    )

    passed = (
        primary_count >= config["min_primary"]
        and secondary_count >= config["min_secondary"]
    )

    msg = f"Brand mentions: primary={primary_count} (need>={config['min_primary']}), " \
          f"secondary={secondary_count} (need>={config['min_secondary']})"

    return BrandMentionResult(
        passed=passed,
        primary_count=primary_count,
        secondary_count=secondary_count,
        message=msg,
    )
