"""Phase 3 AI assist: transcript → LLM → cached artifact, with friendly errors.

Transcript fetching and the LLM call are faked via ``app.dependency_overrides``
(see conftest), so these tests never touch YouTube or the Anthropic API.
"""

import re

from sqlmodel import Session, select

from app.models import AIArtifact, Transcript

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLtest"


def _make_subject_with_items(client, name="AI 主題"):
    client.post("/subjects", data={"name": name})
    sid = int(re.findall(r"/subjects/(\d+)", client.get("/").text)[-1])
    client.post("/import", data={"subject_id": sid, "url": PLAYLIST_URL})
    return sid


def _first_item_id(client, sid):
    page = client.get(f"/subjects/{sid}").text
    return int(re.findall(r'id="item-(\d+)"', page)[0])


def test_summarize_generates_and_caches(client, engine):
    sid = _make_subject_with_items(client)
    iid = _first_item_id(client, sid)

    r = client.post(f"/items/{iid}/summarize")
    assert r.status_code == 200
    assert "摘要" in r.text
    assert "transcript text for" in r.text  # the (faked) generated content

    # A second click is served from the cache — the LLM is not invoked again.
    client.post(f"/items/{iid}/summarize")
    assert client.fake_ai.calls == 1
    with Session(engine) as s:
        assert len(s.exec(select(AIArtifact)).all()) == 1


def test_notes_generates(client):
    sid = _make_subject_with_items(client)
    iid = _first_item_id(client, sid)
    r = client.post(f"/items/{iid}/notes")
    assert r.status_code == 200
    assert "重點筆記" in r.text


def test_transcript_fetched_once_across_kinds(client, engine):
    sid = _make_subject_with_items(client)
    iid = _first_item_id(client, sid)

    client.post(f"/items/{iid}/summarize")
    client.post(f"/items/{iid}/notes")

    assert client.fake_transcript.calls == 1  # transcript cached across kinds
    assert client.fake_ai.calls == 2  # but each kind is generated once
    with Session(engine) as s:
        assert len(s.exec(select(Transcript)).all()) == 1


def test_cached_results_render_on_page(client):
    sid = _make_subject_with_items(client)
    iid = _first_item_id(client, sid)
    client.post(f"/items/{iid}/summarize")

    # Reloading the subject page shows the already-generated summary inline.
    page = client.get(f"/subjects/{sid}").text
    assert f'id="ai-out-summary-{iid}"' in page
    assert "transcript text for" in page


def test_ai_controls_hidden_in_edit_mode(client):
    sid = _make_subject_with_items(client)

    normal = client.get(f"/subjects/{sid}").text
    assert "/summarize" in normal
    assert "重點筆記" in normal

    edit = client.get(f"/subjects/{sid}?edit=1").text
    assert "/summarize" not in edit  # AI row suppressed while bulk-editing


def test_transcript_error_is_friendly(client, engine):
    from app.main import app
    from app.transcript import TranscriptError, TranscriptFetcher

    class Boom:
        def fetch(self, video_id):
            raise TranscriptError("這支影片沒有可用的字幕。")

    app.dependency_overrides[TranscriptFetcher] = lambda: Boom()

    sid = _make_subject_with_items(client)
    iid = _first_item_id(client, sid)
    r = client.post(f"/items/{iid}/summarize")

    assert r.status_code == 200
    assert "沒有可用的字幕" in r.text
    # A failed fetch caches nothing, so the user can retry later.
    with Session(engine) as s:
        assert s.exec(select(AIArtifact)).all() == []


def test_summarize_unknown_item_404(client):
    assert client.post("/items/999999/summarize").status_code == 404
