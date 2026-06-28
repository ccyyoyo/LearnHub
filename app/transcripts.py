"""YouTube transcript fetching for quiz source text (PRD Phase 3).

Isolated like ``youtube.py`` so any upstream library change touches one file.
``youtube-transcript-api`` is imported lazily and every failure (no captions,
network, library absent) degrades to ``None`` — the caller then falls back to
the video's notes or title.
"""

from __future__ import annotations

# Japanese first (N5 content), English as a secondary.
_LANGS = ["ja", "en"]


class TranscriptFetcher:
    """Best-effort transcript fetch; returns ``None`` when unavailable."""

    def fetch(self, video_id: str) -> str | None:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError:
            return None

        # Library API changed across versions; try the 1.x instance form first,
        # then the older static method.
        text = self._fetch_v1(YouTubeTranscriptApi, video_id)
        if text is None:
            text = self._fetch_legacy(YouTubeTranscriptApi, video_id)
        return text

    @staticmethod
    def _fetch_v1(api_cls, video_id: str) -> str | None:
        try:
            fetched = api_cls().fetch(video_id, languages=_LANGS)
            text = " ".join(snippet.text for snippet in fetched).strip()
            return text or None
        except Exception:
            return None

    @staticmethod
    def _fetch_legacy(api_cls, video_id: str) -> str | None:
        try:
            entries = api_cls.get_transcript(video_id, languages=_LANGS)
            text = " ".join(e["text"] for e in entries).strip()
            return text or None
        except Exception:
            return None
