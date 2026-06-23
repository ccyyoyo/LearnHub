"""YouTube transcript fetching (Phase 3).

Isolated here the same way ``youtube.py`` isolates the Data API: if the upstream
library or YouTube's behaviour changes, only this file moves (R2). The Phase 1
metadata path uses the official API key, but captions *content* can't be
downloaded that way for videos you don't own — that needs OAuth + ownership — so
transcripts go through ``youtube-transcript-api`` instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

# Preferred caption languages, best first. If none match we fall back to
# whatever the video does have (the LLM is told to answer in zh-TW regardless).
_LANG_PREFS = ["zh-TW", "zh-Hant", "zh", "zh-Hans", "en"]


class TranscriptError(Exception):
    """Raised for any user-facing transcript failure (no captions, blocked, …)."""


@dataclass(frozen=True)
class TranscriptResult:
    language: str
    text: str


class TranscriptFetcher:
    """Fetches and flattens a video's captions into plain text.

    Stateless, so routes can ``Depends(TranscriptFetcher)`` and tests can swap it
    out via ``app.dependency_overrides`` — the same pattern as ``YouTubeClient``.
    """

    def fetch(self, video_id: str) -> TranscriptResult:
        """Blocking fetch — call via ``asyncio.to_thread`` from async routes."""
        try:
            api = YouTubeTranscriptApi()
            transcripts = api.list(video_id)
            try:
                transcript = transcripts.find_transcript(_LANG_PREFS)
            except NoTranscriptFound:
                # No preferred language — take whatever exists.
                transcript = next(iter(transcripts), None)
            if transcript is None:
                raise TranscriptError("這支影片沒有可用的字幕。")
            fetched = transcript.fetch()
        except TranscriptsDisabled as exc:
            raise TranscriptError("這支影片關閉了字幕功能。") from exc
        except NoTranscriptFound as exc:
            raise TranscriptError("找不到這支影片的字幕。") from exc
        except VideoUnavailable as exc:
            raise TranscriptError("無法存取這支影片(可能是私人或已刪除)。") from exc
        except CouldNotRetrieveTranscript as exc:
            # Base class also covers RequestBlocked / IpBlocked — the cloud-IP
            # block that bites once this runs off a datacenter address.
            raise TranscriptError(
                "抓取字幕失敗,可能被 YouTube 暫時封鎖(雲端 IP 常見);"
                "稍後再試,或為 youtube-transcript-api 設定代理。"
            ) from exc

        text = " ".join(s.text for s in fetched if s.text).strip()
        if not text:
            raise TranscriptError("這支影片的字幕是空的。")
        return TranscriptResult(language=fetched.language_code, text=text)
