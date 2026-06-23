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


def test_duration_badges_and_total(client):
    _create_subject(client)
    sid = _subject_id(client)
    client.post(
        "/import",
        data={"subject_id": sid, "url": "https://www.youtube.com/playlist?list=PLtest"},
    )
    page = client.get(f"/subjects/{sid}").text
    # Per-video durations (100 / 200 / 300s -> clock format).
    assert "1:40" in page
    assert "3:20" in page
    assert "5:00" in page
    # Resource total (600s) shown on the header.
    assert "10:00" in page


def test_progress_mode_count_vs_time(client):
    _create_subject(client)
    sid = _subject_id(client)
    client.post(
        "/import",
        data={"subject_id": sid, "url": "https://www.youtube.com/playlist?list=PLtest"},
    )
    import re

    page = client.get(f"/subjects/{sid}").text
    item_ids = [int(x) for x in re.findall(r'id="item-(\d+)"', page)]
    assert len(item_ids) == 3

    # Items are ordered by position: the third is the 300s (5:00) video.
    client.post(f"/items/{item_ids[2]}/cycle?progress=time")  # -> in_progress
    r = client.post(f"/items/{item_ids[2]}/cycle?progress=time")  # -> done
    # OOB progress fragment comes back measured in watch-time.
    assert "5:00 / 10:00" in r.text

    # Time mode: 300/600s done -> 50%.
    time_page = client.get(f"/subjects/{sid}?progress=time").text
    assert "5:00 / 10:00" in time_page
    assert "50%" in time_page

    # Count mode: 1 of 3 videos done.
    count_page = client.get(f"/subjects/{sid}?progress=count").text
    assert "1/3" in count_page


def test_progress_toggle_present(client):
    sid = _imported_subject(client)
    page = client.get(f"/subjects/{sid}").text
    assert "依數量" in page
    assert "依時間" in page
    assert "progress=time" in page


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


# --- Subject rename (inline edit) -------------------------------------------


def test_subject_page_has_rename_trigger(client):
    _create_subject(client)
    sid = _subject_id(client)
    page = client.get(f"/subjects/{sid}").text
    assert "改名" in page
    assert f"/subjects/{sid}/rename-form" in page


def test_rename_form_returns_editable_form(client):
    _create_subject(client, name="舊名")
    sid = _subject_id(client)
    form = client.get(f"/subjects/{sid}/rename-form")
    assert form.status_code == 200
    assert "舊名" in form.text
    assert f"/subjects/{sid}/rename" in form.text


def test_rename_returns_header_fragment(client):
    _create_subject(client, name="舊名")
    sid = _subject_id(client)
    r = client.post(f"/subjects/{sid}/rename", data={"name": "新名"})
    assert r.status_code == 200
    assert "新名" in r.text
    # Header fragment, not the whole page (the import panel lives on the page).
    assert "匯入資源" not in r.text


def test_rename_empty_keeps_old_name(client):
    _create_subject(client, name="舊名")
    sid = _subject_id(client)
    client.post(f"/subjects/{sid}/rename", data={"name": "   "})
    assert "舊名" in client.get(f"/subjects/{sid}").text


# --- Edit mode + bulk operations --------------------------------------------


def _imported_subject(client, name="主題"):
    _create_subject(client, name=name)
    sid = _subject_id(client)
    client.post(
        "/import",
        data={"subject_id": sid, "url": "https://www.youtube.com/playlist?list=PLtest"},
    )
    return sid


def _item_ids(client, sid):
    import re

    page = client.get(f"/subjects/{sid}").text
    return [int(x) for x in re.findall(r'id="item-(\d+)"', page)]


def test_edit_mode_renders_controls(client):
    sid = _imported_subject(client)

    normal = client.get(f"/subjects/{sid}").text
    assert 'name="item_ids"' not in normal  # no checkboxes by default

    edit = client.get(f"/subjects/{sid}?edit=1").text
    assert 'name="item_ids"' in edit  # multi-select checkboxes
    assert "bulk-status" in edit  # bulk status action wired
    assert "bulk-delete" in edit  # bulk delete action wired
    assert f"/subjects/{sid}/resources/" in edit  # per-resource delete button


def test_bulk_status_sets_only_selected(client):
    sid = _imported_subject(client)
    ids = _item_ids(client, sid)
    assert len(ids) == 3

    r = client.post(
        f"/subjects/{sid}/items/bulk-status",
        data={"item_ids": ids[:2], "status": "done", "filter": "all", "edit": "1"},
    )
    assert r.status_code == 200
    page = client.get(f"/subjects/{sid}").text
    assert "2/3" in page  # exactly the two selected are done


def test_bulk_delete_removes_selected_and_recomputes(client):
    sid = _imported_subject(client)
    ids = _item_ids(client, sid)

    r = client.post(
        f"/subjects/{sid}/items/bulk-delete",
        data={"item_ids": ids[:2], "filter": "all", "edit": "1"},
    )
    assert r.status_code == 200
    page = client.get(f"/subjects/{sid}").text
    assert page.count('class="item-row') == 1
    assert "0/1" in page  # progress recomputed over the remaining item


def test_bulk_ignores_cross_subject_ids(client):
    sid_a = _imported_subject(client, name="A")
    ids_a = _item_ids(client, sid_a)

    sid_b = _imported_subject(client, name="B")

    # Try to delete A's items through B's endpoint — must be ignored.
    client.post(
        f"/subjects/{sid_b}/items/bulk-delete",
        data={"item_ids": ids_a, "filter": "all", "edit": "1"},
    )
    page_a = client.get(f"/subjects/{sid_a}").text
    assert page_a.count('class="item-row') == 3  # A untouched


def test_delete_whole_resource(client):
    sid = _imported_subject(client)
    import re

    page = client.get(f"/subjects/{sid}").text
    rid = int(re.search(r'id="resource-(\d+)"', page).group(1))

    r = client.delete(f"/subjects/{sid}/resources/{rid}")
    assert r.status_code == 200
    page = client.get(f"/subjects/{sid}").text
    assert page.count('class="item-row') == 0
    assert "還沒有資源" in page
