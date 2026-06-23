"""Test fixtures: an isolated in-memory DB and a fake YouTube client."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app
from app.models import ResourceType
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
        VideoData("vid1", "影片一", "http://thumb/1.jpg", 0, duration_seconds=100),
        VideoData("vid2", "影片二", "http://thumb/2.jpg", 1, duration_seconds=200),
        VideoData("vid3", "影片三", "http://thumb/3.jpg", 2, duration_seconds=300),
    ]

    async def fetch(self, parsed: ParsedUrl):
        if parsed.type is ResourceType.playlist:
            return "測試清單", list(self.playlist)
        return "單支影片", [VideoData(parsed.id, "單支影片", None, 0, duration_seconds=90)]

    async def fetch_durations(self, video_ids):
        # Pretend every video is now 5 minutes long (used by the refresh test).
        return {vid: 300 for vid in video_ids}


@pytest.fixture
def client(engine):
    def get_session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[YouTubeClient] = lambda: FakeYouTubeClient()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
