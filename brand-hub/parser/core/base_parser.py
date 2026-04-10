"""Base platform parser — abstract class for all platform implementations."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


class NormalizedItem(BaseModel):
    """Unified schema for parsed data from any platform."""

    id: str                                          # sha256(platform + url + text[:200])
    platform: str                                    # "vk", "telegram", "youtube", "wb", "rss"
    brand_target: str                                # Brand this item relates to
    type: str                                        # "review", "comment", "post", "article"
    author_id: str                                   # sha256 of original author ID (depersonalized)
    text: str
    rating: Optional[int] = None                     # 1-5 if available
    sentiment: Optional[str] = None                  # "positive", "negative", "neutral"
    metrics: dict = Field(default_factory=dict)      # likes, views, reposts, comments
    media: List[str] = Field(default_factory=list)   # URLs to images/videos
    timestamp: Optional[datetime] = None             # Original publication time
    url: Optional[str] = None                        # Source URL
    is_verified_purchase: bool = False
    company_reply: Optional[str] = None
    metadata: dict = Field(default_factory=dict)     # Platform-specific extra data
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BasePlatformParser(ABC):
    """Abstract base for platform-specific parsers."""

    def __init__(self, brand_config: dict):
        self.brand_config = brand_config
        self.keywords: List[str] = brand_config.get("keywords", [])
        self.brand_id: str = brand_config.get("brand_id", "")

    @abstractmethod
    async def fetch_new(self, since: Optional[datetime] = None) -> List[NormalizedItem]:
        """Collect new items from the platform since given date."""

    @abstractmethod
    def platform_name(self) -> str:
        """Return platform identifier (e.g. 'vk', 'telegram')."""

    def platform_config(self) -> dict:
        """Get platform-specific config from brand config."""
        sources = self.brand_config.get("parser_sources", {})
        return sources.get(self.platform_name(), {})

    def is_enabled(self) -> bool:
        """Check if this platform is enabled for the brand."""
        return self.platform_config().get("enabled", False)

    async def health_check(self) -> bool:
        """Check if the platform API is accessible."""
        return True
