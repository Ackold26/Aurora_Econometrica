"""Telegram platform parser — channel messages via Telethon (MTProto)."""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from ..core.base_parser import BasePlatformParser, NormalizedItem
from ..core.normalizer import hash_id, hash_author, clean_text, parse_timestamp

# Telethon imported lazily to avoid startup cost when not configured
_telethon_available = None


def _check_telethon():
    global _telethon_available
    if _telethon_available is None:
        try:
            import telethon  # noqa: F401
            _telethon_available = True
        except ImportError:
            _telethon_available = False
    return _telethon_available


class TelegramParser(BasePlatformParser):
    """Parses Telegram public channels and groups via Telethon."""

    def platform_name(self) -> str:
        return "telegram"

    async def fetch_new(self, since: Optional[datetime] = None) -> List[NormalizedItem]:
        if not _check_telethon():
            return []

        from telethon import TelegramClient
        from telethon.errors import FloodWaitError

        config = self.platform_config()
        api_id = config.get("api_id")
        api_hash = config.get("api_hash")
        session_name = config.get("session_name", "parser_session")

        if not api_id or not api_hash:
            return []

        channels = config.get("channels", [])
        if not channels:
            return []

        items: List[NormalizedItem] = []
        client = TelegramClient(session_name, api_id, api_hash)

        try:
            await client.start()

            for channel in channels[:200]:  # Limit to avoid shadow ban
                try:
                    entity = await client.get_entity(channel)
                    async for message in client.iter_messages(entity, limit=100):
                        if since and message.date and message.date < since:
                            break
                        text = clean_text(message.text or "")
                        if not text:
                            continue

                        media_urls = []
                        if message.photo:
                            media_urls.append(f"tg://photo/{message.id}")

                        items.append(NormalizedItem(
                            id=hash_id("telegram", f"t.me/{channel}/{message.id}", text),
                            platform="telegram",
                            brand_target=self.brand_id,
                            type="post",
                            author_id=hash_author(str(message.sender_id or channel)),
                            text=text,
                            metrics={
                                "views": message.views or 0,
                                "forwards": message.forwards or 0,
                            },
                            media=media_urls,
                            timestamp=message.date.replace(tzinfo=timezone.utc) if message.date else None,
                            url=f"https://t.me/{channel.lstrip('@')}/{message.id}",
                            metadata={"channel": channel},
                        ))

                    await asyncio.sleep(1.0)  # Rate limit between channels

                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds + 1)
                except Exception:
                    continue

        finally:
            await client.disconnect()

        return items

    async def health_check(self) -> bool:
        return _check_telethon() and bool(self.platform_config().get("api_id"))
