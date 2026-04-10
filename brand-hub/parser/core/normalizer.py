"""Data normalization utilities — depersonalization, hashing, text cleanup."""

import hashlib
import html
import re
from datetime import datetime, timezone


def hash_id(platform: str, url: str, text: str) -> str:
    """Generate unique ID from platform + url + text prefix."""
    raw = f"{platform}|{url or ''}|{text[:200]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_author(author_id: str) -> str:
    """Depersonalize author ID per 152-FZ (Russian data protection law)."""
    if not author_id:
        return "anonymous"
    return hashlib.sha256(str(author_id).encode("utf-8")).hexdigest()[:16]


def clean_text(text: str) -> str:
    """Clean HTML tags, normalize whitespace."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)        # strip HTML tags
    text = re.sub(r"\s+", " ", text)            # normalize whitespace
    text = text.strip()
    return text


def parse_timestamp(ts) -> datetime:
    """Parse various timestamp formats to UTC datetime."""
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str):
        for fmt in [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%d.%m.%Y %H:%M",
        ]:
            try:
                dt = datetime.strptime(ts, fmt)
                return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
            except ValueError:
                continue
    return datetime.now(timezone.utc)
