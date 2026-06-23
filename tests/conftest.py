"""Test fixtures: an isolated in-memory DB and a fake YouTube client."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.ai import AIClient
from app.db import get_session
from app.main import app
from app.models import AIKind, ResourceType
from app.transcript import TranscriptFetcher, TranscriptResult
from app.youtube import ParsedUrl, VideoData, YouTubeClient


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


class FakeYouTubeClient:
    """Returns canned data so tests don't hit the network/API."""

    playlist = [
        VideoData("vid1", "影片一", "http://thumb/1.jpg", 0),
        VideoData("vid2", "影片二", "http://thumb/2.jpg", 1),
        VideoData("vid3", "影片三", "http://thumb/3.jpg", 2),
    ]

    async def fetch(self, parsed: ParsedUrl):
        if parsed.type is ResourceType.playlist:
            return "測試清單", list(self.playlist)
        return "單支影片", [VideoData(parsed.id, "單支影片", None, 0)]


class FakeTranscriptFetcher:
    """Canned transcript so tests never hit YouTube. Counts calls so a test can
    assert the per-video cache stops repeat fetches."""

    def __init__(self):
        self.calls = 0

    def fetch(self, video_id: str) -> TranscriptResult:
        self.calls += 1
        return TranscriptResult(language="en", text=f"transcript text for {video_id}")


class FakeAIClient:
    """Canned LLM output so tests never hit the API. Records calls for cache
    assertions."""

    def __init__(self):
        self.calls = 0

    async def generate(self, kind: AIKind, transcript_text: str) -> str:
        self.calls += 1
        label = "摘要" if kind is AIKind.summary else "重點筆記"
        return f"【{label}】{transcript_text[:24]}"


@pytest.fixture
def client(engine):
    def get_session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[YouTubeClient] = lambda: FakeYouTubeClient()
    # Share single fake instances so tests can read their .calls counters.
    fake_transcript = FakeTranscriptFetcher()
    fake_ai = FakeAIClient()
    app.dependency_overrides[TranscriptFetcher] = lambda: fake_transcript
    app.dependency_overrides[AIClient] = lambda: fake_ai
    with TestClient(app) as c:
        c.fake_transcript = fake_transcript
        c.fake_ai = fake_ai
        yield c
    app.dependency_overrides.clear()
