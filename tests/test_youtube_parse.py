"""URL parsing is the riskiest pure-logic piece, so cover it directly (FR-2.2)."""

import pytest

from app.models import ResourceType
from app.youtube import YouTubeError, parse_iso8601_duration, parse_youtube_url


@pytest.mark.parametrize(
    "url,expected_id",
    [
        ("https://www.youtube.com/playlist?list=PL123abc", "PL123abc"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLxyz", "PLxyz"),
        ("youtube.com/playlist?list=PLnoScheme", "PLnoScheme"),
    ],
)
def test_parse_playlist(url, expected_id):
    parsed = parse_youtube_url(url)
    assert parsed.type is ResourceType.playlist
    assert parsed.id == expected_id


@pytest.mark.parametrize(
    "url,expected_id",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?t=30", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/abc123XYZ", "abc123XYZ"),
        ("https://www.youtube.com/embed/abc123XYZ", "abc123XYZ"),
    ],
)
def test_parse_video(url, expected_id):
    parsed = parse_youtube_url(url)
    assert parsed.type is ResourceType.video
    assert parsed.id == expected_id


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "https://example.com/watch?v=abc",
        "https://www.youtube.com/feed/subscriptions",
        "https://www.youtube.com/watch?v=x&list=RDmix123",  # auto-generated mix
    ],
)
def test_parse_rejects(url):
    with pytest.raises(YouTubeError):
        parse_youtube_url(url)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("PT4M13S", 253),
        ("PT1H2M3S", 3723),
        ("PT45S", 45),
        ("PT2H", 7200),
        ("PT0S", 0),
        ("P0D", 0),  # live streams report zero duration
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_parse_iso8601_duration(value, expected):
    assert parse_iso8601_duration(value) == expected
