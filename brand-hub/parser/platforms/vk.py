"""VK platform parser — wall.get, wall.getComments via VK API."""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional

import aiohttp

from ..core.base_parser import BasePlatformParser, NormalizedItem
from ..core.normalizer import hash_id, hash_author, clean_text, parse_timestamp


VK_API_BASE = "https://api.vk.com/method"
VK_API_VERSION = "5.199"


class VKParser(BasePlatformParser):
    """Parses VK groups: posts, comments, search by keywords."""

    def platform_name(self) -> str:
        return "vk"

    def _get_token(self) -> str:
        return self.platform_config().get("access_token", "")

    async def fetch_new(self, since: Optional[datetime] = None) -> List[NormalizedItem]:
        token = self._get_token()
        if not token:
            return []

        items: List[NormalizedItem] = []
        config = self.platform_config()

        async with aiohttp.ClientSession() as session:
            # Fetch from group walls
            for group_id in config.get("group_ids", []):
                posts = await self._fetch_wall(session, token, group_id, since)
                items.extend(posts)

                # Fetch comments for recent posts
                for post in posts[:20]:  # limit comment fetching
                    post_id = post.metadata.get("post_id")
                    owner_id = post.metadata.get("owner_id")
                    if post_id and owner_id:
                        comments = await self._fetch_comments(
                            session, token, owner_id, post_id
                        )
                        items.extend(comments)
                    await asyncio.sleep(0.35)  # respect rate limits

            # Search by keywords
            if config.get("search_keywords", False) and self.keywords:
                for keyword in self.keywords[:5]:
                    found = await self._search_wall(session, token, keyword, since)
                    items.extend(found)
                    await asyncio.sleep(0.35)

        return items

    async def _fetch_wall(
        self, session: aiohttp.ClientSession, token: str,
        group_id: str, since: Optional[datetime],
    ) -> List[NormalizedItem]:
        params = {
            "owner_id": group_id,
            "count": 100,
            "access_token": token,
            "v": VK_API_VERSION,
        }
        items = []
        try:
            async with session.get(f"{VK_API_BASE}/wall.get", params=params) as resp:
                data = await resp.json()
                for post in data.get("response", {}).get("items", []):
                    ts = parse_timestamp(post.get("date", 0))
                    if since and ts < since:
                        continue
                    text = clean_text(post.get("text", ""))
                    if not text:
                        continue
                    items.append(NormalizedItem(
                        id=hash_id("vk", f"vk.com/wall{group_id}_{post['id']}", text),
                        platform="vk",
                        brand_target=self.brand_id,
                        type="post",
                        author_id=hash_author(str(post.get("from_id", ""))),
                        text=text,
                        metrics={
                            "likes": post.get("likes", {}).get("count", 0),
                            "reposts": post.get("reposts", {}).get("count", 0),
                            "comments": post.get("comments", {}).get("count", 0),
                            "views": post.get("views", {}).get("count", 0),
                        },
                        timestamp=ts,
                        url=f"https://vk.com/wall{group_id}_{post['id']}",
                        metadata={"post_id": post["id"], "owner_id": group_id},
                    ))
        except Exception:
            pass
        return items

    async def _fetch_comments(
        self, session: aiohttp.ClientSession, token: str,
        owner_id: str, post_id: int,
    ) -> List[NormalizedItem]:
        params = {
            "owner_id": owner_id,
            "post_id": post_id,
            "count": 100,
            "sort": "desc",
            "access_token": token,
            "v": VK_API_VERSION,
        }
        items = []
        try:
            async with session.get(f"{VK_API_BASE}/wall.getComments", params=params) as resp:
                data = await resp.json()
                for comment in data.get("response", {}).get("items", []):
                    text = clean_text(comment.get("text", ""))
                    if not text:
                        continue
                    items.append(NormalizedItem(
                        id=hash_id("vk", f"vk.com/comment_{owner_id}_{post_id}_{comment['id']}", text),
                        platform="vk",
                        brand_target=self.brand_id,
                        type="comment",
                        author_id=hash_author(str(comment.get("from_id", ""))),
                        text=text,
                        metrics={"likes": comment.get("likes", {}).get("count", 0)},
                        timestamp=parse_timestamp(comment.get("date", 0)),
                        url=f"https://vk.com/wall{owner_id}_{post_id}?reply={comment['id']}",
                        metadata={"post_id": post_id, "owner_id": owner_id},
                    ))
        except Exception:
            pass
        return items

    async def _search_wall(
        self, session: aiohttp.ClientSession, token: str,
        query: str, since: Optional[datetime],
    ) -> List[NormalizedItem]:
        params = {
            "query": query,
            "count": 100,
            "access_token": token,
            "v": VK_API_VERSION,
        }
        items = []
        try:
            async with session.get(f"{VK_API_BASE}/newsfeed.search", params=params) as resp:
                data = await resp.json()
                for post in data.get("response", {}).get("items", []):
                    ts = parse_timestamp(post.get("date", 0))
                    if since and ts < since:
                        continue
                    text = clean_text(post.get("text", ""))
                    if not text:
                        continue
                    items.append(NormalizedItem(
                        id=hash_id("vk", f"vk.com/wall{post.get('owner_id')}_{post['id']}", text),
                        platform="vk",
                        brand_target=self.brand_id,
                        type="post",
                        author_id=hash_author(str(post.get("from_id", ""))),
                        text=text,
                        timestamp=ts,
                        metadata={"search_query": query},
                    ))
        except Exception:
            pass
        return items

    async def health_check(self) -> bool:
        token = self._get_token()
        if not token:
            return False
        try:
            async with aiohttp.ClientSession() as session:
                params = {"access_token": token, "v": VK_API_VERSION}
                async with session.get(f"{VK_API_BASE}/users.get", params=params) as resp:
                    data = await resp.json()
                    return "response" in data
        except Exception:
            return False
