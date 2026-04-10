"""YouTube platform parser — comments and video metadata via YouTube Data API v3."""

from datetime import datetime, timezone
from typing import List, Optional

from ..core.base_parser import BasePlatformParser, NormalizedItem
from ..core.normalizer import hash_id, hash_author, clean_text, parse_timestamp

_yt_available = None


def _check_youtube_api():
    global _yt_available
    if _yt_available is None:
        try:
            from googleapiclient.discovery import build  # noqa: F401
            _yt_available = True
        except ImportError:
            _yt_available = False
    return _yt_available


class YouTubeParser(BasePlatformParser):
    """Parses YouTube comments and video metadata."""

    def platform_name(self) -> str:
        return "youtube"

    def _get_api_key(self) -> str:
        return self.platform_config().get("api_key", "")

    async def fetch_new(self, since: Optional[datetime] = None) -> List[NormalizedItem]:
        if not _check_youtube_api():
            return []

        api_key = self._get_api_key()
        if not api_key:
            return []

        from googleapiclient.discovery import build

        youtube = build("youtube", "v3", developerKey=api_key)
        items: List[NormalizedItem] = []
        config = self.platform_config()

        # Search by keywords
        if config.get("search_keywords", False) and self.keywords:
            for keyword in self.keywords[:3]:  # Conserve quota
                video_ids = self._search_videos(youtube, keyword, since)
                for vid_id in video_ids[:10]:
                    comments = self._get_comments(youtube, vid_id)
                    items.extend(comments)

        # Specific video IDs
        for vid_id in config.get("video_ids", [])[:20]:
            comments = self._get_comments(youtube, vid_id)
            items.extend(comments)

        return items

    def _search_videos(self, youtube, query: str, since: Optional[datetime]) -> List[str]:
        """Search for videos matching keywords."""
        try:
            params = {
                "q": query,
                "part": "id",
                "type": "video",
                "maxResults": 10,
                "order": "date",
            }
            if since:
                params["publishedAfter"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")

            response = youtube.search().list(**params).execute()
            return [item["id"]["videoId"] for item in response.get("items", [])
                    if item.get("id", {}).get("videoId")]
        except Exception:
            return []

    def _get_comments(self, youtube, video_id: str) -> List[NormalizedItem]:
        """Fetch comments for a video."""
        items = []
        try:
            response = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=100,
                order="time",
                textFormat="plainText",
            ).execute()

            for thread in response.get("items", []):
                snippet = thread["snippet"]["topLevelComment"]["snippet"]
                text = clean_text(snippet.get("textDisplay", ""))
                if not text:
                    continue

                items.append(NormalizedItem(
                    id=hash_id("youtube", f"youtube.com/watch?v={video_id}", text),
                    platform="youtube",
                    brand_target=self.brand_id,
                    type="comment",
                    author_id=hash_author(snippet.get("authorChannelId", {}).get("value", "")),
                    text=text,
                    metrics={
                        "likes": snippet.get("likeCount", 0),
                    },
                    timestamp=parse_timestamp(snippet.get("publishedAt", "")),
                    url=f"https://youtube.com/watch?v={video_id}",
                    metadata={"video_id": video_id},
                ))
        except Exception:
            pass
        return items

    async def health_check(self) -> bool:
        return _check_youtube_api() and bool(self._get_api_key())
