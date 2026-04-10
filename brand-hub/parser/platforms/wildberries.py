"""Wildberries platform parser — product reviews via internal API."""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional

import aiohttp

from ..core.base_parser import BasePlatformParser, NormalizedItem
from ..core.normalizer import hash_id, hash_author, clean_text, parse_timestamp


# WB internal API for public data (reviews)
WB_FEEDBACKS_URL = "https://feedbacks{shard}.wb.ru/feedbacks/v2/{product_id}"
WB_CARD_URL = "https://card.wb.ru/cards/v2/detail"


class WildberriesParser(BasePlatformParser):
    """Parses Wildberries product reviews."""

    def platform_name(self) -> str:
        return "wildberries"

    async def fetch_new(self, since: Optional[datetime] = None) -> List[NormalizedItem]:
        config = self.platform_config()
        product_ids = config.get("product_ids", [])
        items: List[NormalizedItem] = []

        # Also search by keywords in product names (simplified)
        if config.get("search_keywords", False) and self.keywords:
            for keyword in self.keywords[:3]:
                found_ids = await self._search_products(keyword)
                product_ids.extend(found_ids[:5])

        async with aiohttp.ClientSession() as session:
            for product_id in product_ids[:50]:  # Safety limit
                reviews = await self._fetch_reviews(session, str(product_id), since)
                items.extend(reviews)
                await asyncio.sleep(1.5)  # Be gentle with WB

        return items

    async def _search_products(self, query: str) -> List[int]:
        """Search WB catalog for product IDs matching keywords."""
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://search.wb.ru/exactmatch/ru/common/v7/search"
                params = {"query": query, "resultset": "catalog", "limit": 10}
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                async with session.get(url, params=params, headers=headers) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    products = data.get("data", {}).get("products", [])
                    return [p["id"] for p in products if "id" in p]
        except Exception:
            return []

    async def _fetch_reviews(
        self, session: aiohttp.ClientSession,
        product_id: str, since: Optional[datetime],
    ) -> List[NormalizedItem]:
        """Fetch reviews for a specific product."""
        items = []
        # Determine shard (WB distributes across multiple servers)
        shard = int(product_id) % 10 + 1 if product_id.isdigit() else 1

        url = f"https://feedbacks{shard}.wb.ru/feedbacks/v2/{product_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }

        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

            for fb in data.get("feedbacks", []):
                text = clean_text(fb.get("text", ""))
                if not text:
                    continue

                ts = parse_timestamp(fb.get("createdDate", ""))
                if since and ts < since:
                    continue

                pros = clean_text(fb.get("pros", ""))
                cons = clean_text(fb.get("cons", ""))
                full_text = text
                if pros:
                    full_text = f"Pros: {pros}. {full_text}"
                if cons:
                    full_text = f"{full_text}. Cons: {cons}"

                photos = [p.get("fullSizeUri", "") for p in fb.get("photos", []) if p.get("fullSizeUri")]

                items.append(NormalizedItem(
                    id=hash_id("wb", f"wb.ru/product/{product_id}/review/{fb.get('id', '')}", text),
                    platform="wildberries",
                    brand_target=self.brand_id,
                    type="review",
                    author_id=hash_author(str(fb.get("wbUserId", ""))),
                    text=full_text,
                    rating=fb.get("productValuation"),
                    metrics={"likes": fb.get("votes", {}).get("up", 0)},
                    media=photos,
                    timestamp=ts,
                    url=f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx",
                    is_verified_purchase=fb.get("isVerifiedPurchase", False),
                    company_reply=clean_text(fb.get("answer", {}).get("text", "")) or None,
                    metadata={"product_id": product_id},
                ))
        except Exception:
            pass
        return items

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://www.wildberries.ru", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status == 200
        except Exception:
            return False
