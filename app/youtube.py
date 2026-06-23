"""YouTube Data API client + URL parsing (PRD §7.1, R2).

All YouTube-specific parsing and HTTP lives here so that any upstream API change
only touches a single file (R2). Phase 1 only needs an API key for public
playlists/videos — no OAuth (R1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from urllib.parse import parse_qs, urlparse

import httpx

from .config import get_settings
from .models import ResourceType

API_BASE = "https://www.googleapis.com/youtube/v3"
_MAX_RESULTS = 50  # API maximum per page (and per videos.list id batch).

# YouTube returns durations as ISO 8601 (e.g. "PT4M13S", "PT1H2M3S", "P0D" for
# live streams). We only ever see days/hours/minutes/seconds in practice.
_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def parse_iso8601_duration(value: str | None) -> int | None:
    """Convert an ISO 8601 duration to whole seconds (``None`` if unparseable)."""
    if not value:
        return None
    match = _DURATION_RE.fullmatch(value)
    if not match:
        return None
    parts = {k: int(v) for k, v in match.groupdict(default="0").items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


class YouTubeError(Exception):
    """Raised for any user-facing import failure (bad URL, API error, …)."""


@dataclass(frozen=True)
class ParsedUrl:
    type: ResourceType
    id: str  # playlist id or video id


@dataclass(frozen=True)
class VideoData:
    video_id: str
    title: str
    thumbnail_url: str | None
    position: int
    duration_seconds: int | None = None


def parse_youtube_url(url: str) -> ParsedUrl:
    """Classify a pasted URL as a playlist or a single video (FR-2.2).

    A ``list=`` query param wins — that's the integrated-import sweet spot the
    product is built around. Otherwise we look for a video id in the usual
    ``watch?v=``, ``youtu.be/``, ``/shorts/`` and ``/embed/`` shapes.
    """
    url = (url or "").strip()
    if not url:
        raise YouTubeError("請輸入 YouTube 網址。")

    parsed = urlparse(url if "//" in url else f"https://{url}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    query = parse_qs(parsed.query)
    path = parsed.path or ""

    if host not in {"youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com"}:
        raise YouTubeError("這看起來不是 YouTube 網址。")

    # Playlist takes precedence (radio/mix lists like "RD..." aren't real
    # playlists and have no stable playlistItems, so we reject them).
    list_ids = query.get("list")
    if list_ids:
        playlist_id = list_ids[0]
        if playlist_id.startswith(("RD", "UL", "LL")):
            raise YouTubeError("不支援自動產生的播放清單(Mix / 個人清單),請改用一般公開清單。")
        return ParsedUrl(ResourceType.playlist, playlist_id)

    # Single video shapes.
    video_id: str | None = None
    if host == "youtu.be":
        video_id = path.lstrip("/").split("/")[0] or None
    elif "v" in query:
        video_id = query["v"][0]
    else:
        for prefix in ("/shorts/", "/embed/", "/live/"):
            if path.startswith(prefix):
                video_id = path[len(prefix):].split("/")[0]
                break

    if video_id:
        return ParsedUrl(ResourceType.video, video_id)

    raise YouTubeError("無法從網址解析出影片或清單 ID。")


def _thumbnail(snippet: dict) -> str | None:
    thumbs = snippet.get("thumbnails") or {}
    for size in ("medium", "high", "standard", "default", "maxres"):
        if size in thumbs and thumbs[size].get("url"):
            return thumbs[size]["url"]
    return None


class YouTubeClient:
    """Thin async wrapper over the YouTube Data API v3."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key if api_key is not None else get_settings().youtube_api_key

    def _require_key(self) -> None:
        if not self.api_key:
            raise YouTubeError(
                "尚未設定 YOUTUBE_API_KEY。請在 .env 中加入金鑰後再匯入。"
            )

    async def _get(self, client: httpx.AsyncClient, endpoint: str, params: dict) -> dict:
        params = {**params, "key": self.api_key}
        try:
            resp = await client.get(f"{API_BASE}/{endpoint}", params=params, timeout=15.0)
        except httpx.HTTPError as exc:  # network-level failure
            raise YouTubeError(f"連線 YouTube API 失敗:{exc}") from exc

        if resp.status_code != 200:
            detail = ""
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except Exception:
                detail = resp.text[:200]
            raise YouTubeError(f"YouTube API 錯誤({resp.status_code}):{detail}")
        return resp.json()

    async def fetch_playlist_title(
        self, client: httpx.AsyncClient, playlist_id: str
    ) -> str:
        data = await self._get(
            client, "playlists", {"part": "snippet", "id": playlist_id, "maxResults": 1}
        )
        items = data.get("items") or []
        if not items:
            raise YouTubeError("找不到這個播放清單(可能是私人或不存在)。")
        return items[0]["snippet"].get("title", playlist_id)

    async def _fetch_durations(
        self, client: httpx.AsyncClient, video_ids: list[str]
    ) -> dict[str, int | None]:
        """Look up each video's length via videos.list, batched 50 ids at a time.

        ``playlistItems`` doesn't carry the video duration, so playlist imports
        need this second call to know how long each video is (used for the
        time-based progress mode).
        """
        durations: dict[str, int | None] = {}
        for start in range(0, len(video_ids), _MAX_RESULTS):
            chunk = video_ids[start : start + _MAX_RESULTS]
            data = await self._get(
                client,
                "videos",
                {"part": "contentDetails", "id": ",".join(chunk), "maxResults": _MAX_RESULTS},
            )
            for entry in data.get("items", []):
                content = entry.get("contentDetails", {}) or {}
                durations[entry["id"]] = parse_iso8601_duration(content.get("duration"))
        return durations

    async def fetch_playlist_items(
        self, client: httpx.AsyncClient, playlist_id: str
    ) -> list[VideoData]:
        """Fetch every video in a playlist, following pagination (FR-2.2)."""
        videos: list[VideoData] = []
        page_token: str | None = None
        position = 0
        while True:
            params = {
                "part": "snippet,contentDetails",
                "playlistId": playlist_id,
                "maxResults": _MAX_RESULTS,
            }
            if page_token:
                params["pageToken"] = page_token
            data = await self._get(client, "playlistItems", params)

            for entry in data.get("items", []):
                snippet = entry.get("snippet", {})
                content = entry.get("contentDetails", {})
                video_id = content.get("videoId") or (
                    snippet.get("resourceId", {}) or {}
                ).get("videoId")
                if not video_id:
                    continue
                title = snippet.get("title", "")
                # Deleted/private videos surface as placeholder titles; skip them.
                if title in ("Deleted video", "Private video", ""):
                    continue
                videos.append(
                    VideoData(
                        video_id=video_id,
                        title=title,
                        thumbnail_url=_thumbnail(snippet),
                        position=snippet.get("position", position),
                    )
                )
                position += 1

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        durations = await self._fetch_durations(client, [v.video_id for v in videos])
        return [
            replace(v, duration_seconds=durations.get(v.video_id))
            for v in videos
        ]

    async def fetch_video(
        self, client: httpx.AsyncClient, video_id: str
    ) -> VideoData:
        data = await self._get(
            client,
            "videos",
            {"part": "snippet,contentDetails", "id": video_id, "maxResults": 1},
        )
        items = data.get("items") or []
        if not items:
            raise YouTubeError("找不到這支影片(可能是私人或不存在)。")
        snippet = items[0]["snippet"]
        content = items[0].get("contentDetails", {}) or {}
        return VideoData(
            video_id=video_id,
            title=snippet.get("title", video_id),
            thumbnail_url=_thumbnail(snippet),
            position=0,
            duration_seconds=parse_iso8601_duration(content.get("duration")),
        )

    async def fetch(self, parsed: ParsedUrl) -> tuple[str, list[VideoData]]:
        """Resolve a parsed URL into (resource_title, videos)."""
        self._require_key()
        async with httpx.AsyncClient() as client:
            if parsed.type is ResourceType.playlist:
                title = await self.fetch_playlist_title(client, parsed.id)
                videos = await self.fetch_playlist_items(client, parsed.id)
                if not videos:
                    raise YouTubeError("這個清單沒有可匯入的公開影片。")
                return title, videos
            video = await self.fetch_video(client, parsed.id)
            return video.title, [video]

    async def fetch_durations(self, video_ids: list[str]) -> dict[str, int | None]:
        """Re-query durations for a set of videos (used by the refresh action).

        Returns a ``video_id -> seconds`` map; ids the API doesn't return (e.g.
        a video gone private) are simply absent so callers can leave them alone.
        """
        self._require_key()
        unique = list(dict.fromkeys(vid for vid in video_ids if vid))
        if not unique:
            return {}
        async with httpx.AsyncClient() as client:
            return await self._fetch_durations(client, unique)
