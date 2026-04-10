"""RSS/News platform parser — feed aggregation via feedparser."""

from datetime import datetime, timezone
from typing import List, Optional

import aiohttp

from ..core.base_parser import BasePlatformParser, NormalizedItem
from ..core.normalizer import hash_id, hash_author, clean_text, parse_timestamp

_feedparser_available = None


def _check_feedparser():
    global _feedparser_available
    if _feedparser_available is None:
        try:
            import feedparser  # noqa: F401
            _feedparser_available = True
        except ImportError:
            _feedparser_available = False
    return _feedparser_available


class RSSParser(BasePlatformParser):
    """Parses RSS/Atom feeds for news articles."""

    def platform_name(self) -> str:
        return "rss"

    async def fetch_new(self, since: Optional[datetime] = None) -> List[NormalizedItem]:
        if not _check_feedparser():
            return []

        import feedparser

        config = self.platform_config()
        feeds = config.get("feeds", [])
        if not feeds:
            return []

        items: List[NormalizedItem] = []

        async with aiohttp.ClientSession() as session:
            for feed_url in feeds:
                try:
                    async with session.get(feed_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status != 200:
                            continue
                        content = await resp.text()

                    parsed = feedparser.parse(content)

                    for entry in parsed.entries[:50]:
                        title = clean_text(entry.get("title", ""))
                        summary = clean_text(entry.get("summary", entry.get("description", "")))
                        text = f"{title}. {summary}" if summary else title
                        if not text:
                            continue

                        ts = None
                        if hasattr(entry, "published_parsed") and entry.published_parsed:
                            ts = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                            ts = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

                        if since and ts and ts < since:
                            continue

                        link = entry.get("link", "")

                        # Check if any keyword appears in text
                        text_lower = text.lower()
                        if self.keywords and not any(kw.lower() in text_lower for kw in self.keywords):
                            continue

                        items.append(NormalizedItem(
                            id=hash_id("rss", link, text),
                            platform="rss",
                            brand_target=self.brand_id,
                            type="article",
                            author_id=hash_author(entry.get("author", feed_url)),
                            text=text,
                            timestamp=ts,
                            url=link,
                            metadata={"feed_url": feed_url, "title": title},
                        ))

                except Exception:
                    continue

        return items

    async def health_check(self) -> bool:
        config = self.platform_config()
        feeds = config.get("feeds", [])
        if not feeds:
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(feeds[0], timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status < 400
        except Exception:
            return False
