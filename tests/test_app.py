"""End-to-end happy-path: create subject → import → toggle → progress (Phase 1)."""


def _create_subject(client, name="日語 N5"):
    resp = client.post("/subjects", data={"name": name})
    assert resp.status_code == 200
    assert name in resp.text
    # Pull the subject id off the link in the returned partial.
    from app.db import get_session

    return resp


def _subject_id(client):
    # The home page lists subjects with links /subjects/<id>.
    import re

    html = client.get("/").text
    ids = re.findall(r"/subjects/(\d+)", html)
    assert ids
    return int(ids[-1])


def test_create_and_list_subject(client):
    _create_subject(client)
    home = client.get("/")
    assert "日語 N5" in home.text
    assert "0 個資源" in home.text  # FR-1.2 resource count


def test_import_is_idempotent(client):
    _create_subject(client)
    sid = _subject_id(client)
    url = "https://www.youtube.com/playlist?list=PLtest"

    r1 = client.post("/import", data={"subject_id": sid, "url": url})
    assert r1.status_code == 200
    assert "新增 3 項" in r1.text

    # Re-import the same playlist: no duplicates (FR-2.4).
    r2 = client.post("/import", data={"subject_id": sid, "url": url})
    assert "新增 0 項" in r2.text

    # Confirm only 3 items exist for the subject.
    from sqlmodel import Session, select

    from app.models import Item

    page = client.get(f"/subjects/{sid}").text
    assert page.count('class="item-row') == 3


def test_status_cycle_and_progress(client):
    _create_subject(client)
    sid = _subject_id(client)
    client.post(
        "/import",
        data={"subject_id": sid, "url": "https://www.youtube.com/playlist?list=PLtest"},
    )

    # Find an item id from the subject page.
    import re

    page = client.get(f"/subjects/{sid}").text
    item_ids = [int(x) for x in re.findall(r'id="item-(\d+)"', page)]
    assert len(item_ids) == 3

    # Cycle one item not_started → in_progress.
    r = client.post(f"/items/{item_ids[0]}/cycle")
    assert "進行中" in r.text
    # OOB progress fragment present.
    assert "hx-swap-oob" in r.text

    # Cycle to done and check resource progress reflects 1/3.
    client.post(f"/items/{item_ids[0]}/cycle")  # in_progress -> done
    page = client.get(f"/subjects/{sid}").text
    assert "1/3" in page
    assert "33%" in page


def test_import_bad_url_shows_error(client):
    _create_subject(client)
    sid = _subject_id(client)
    r = client.post("/import", data={"subject_id": sid, "url": "https://example.com/x"})
    assert "YouTube" in r.text  # friendly error message


def test_filter_incomplete(client):
    _create_subject(client)
    sid = _subject_id(client)
    client.post(
        "/import",
        data={"subject_id": sid, "url": "https://www.youtube.com/playlist?list=PLtest"},
    )
    import re

    page = client.get(f"/subjects/{sid}").text
    item_ids = [int(x) for x in re.findall(r'id="item-(\d+)"', page)]
    # Mark all done.
    for iid in item_ids:
        client.post(f"/items/{iid}/cycle")  # -> in_progress
        client.post(f"/items/{iid}/cycle")  # -> done

    incomplete = client.get(f"/subjects/{sid}?filter=incomplete").text
    assert incomplete.count('class="item-row') == 0
