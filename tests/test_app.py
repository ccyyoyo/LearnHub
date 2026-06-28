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


def test_single_video_in_playlist_is_deduped(client):
    """A standalone video already present in an imported playlist is recognised
    as a duplicate across resources, not re-added to the '個別影片' bucket."""
    _create_subject(client)
    sid = _subject_id(client)
    # Playlist brings in vid1, vid2, vid3.
    client.post(
        "/import",
        data={"subject_id": sid, "url": "https://www.youtube.com/playlist?list=PLtest"},
    )
    # Importing vid1 as a standalone video must dedupe against the playlist.
    r = client.post(
        "/import",
        data={"subject_id": sid, "url": "https://www.youtube.com/watch?v=vid1"},
    )
    assert "新增 0 項" in r.text

    # Still exactly 3 items — the standalone import added nothing.
    page = client.get(f"/subjects/{sid}").text
    assert page.count('class="item-row') == 3
    # A genuinely new standalone video does get added to a fresh bucket.
    r2 = client.post(
        "/import",
        data={"subject_id": sid, "url": "https://www.youtube.com/watch?v=brandnew"},
    )
    assert "新增 1 項" in r2.text


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
    # Single client-side toggle button carrying both mode labels.
    assert "data-progress-toggle" in page
    assert "依數量" in page
    assert "依時間" in page


def test_refresh_button_present(client):
    sid = _imported_subject(client)
    # Refresh-durations lives in edit mode only.
    assert "refresh-durations" in client.get(f"/subjects/{sid}?edit=1").text
    assert "refresh-durations" not in client.get(f"/subjects/{sid}").text


def test_refresh_durations_updates_items(client):
    _create_subject(client)
    sid = _subject_id(client)
    client.post(
        "/import",
        data={"subject_id": sid, "url": "https://www.youtube.com/playlist?list=PLtest"},
    )
    import re

    page = client.get(f"/subjects/{sid}").text
    rid = int(re.search(r'id="resource-(\d+)"', page).group(1))
    assert "10:00" in page  # total before refresh (100+200+300s)

    r = client.post(
        f"/subjects/{sid}/resources/{rid}/refresh-durations",
        data={"filter": "all", "edit": "0", "progress": "count"},
    )
    assert r.status_code == 200
    assert "重新整理" in r.text  # success flash
    # Fake client reports every video as 300s -> total 900s = 15:00.
    assert "15:00" in r.text
    assert "15:00" in client.get(f"/subjects/{sid}").text


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


def test_import_respects_active_filter(client):
    # Importing while the 未完成 (incomplete) filter is active must return a
    # resources fragment honoring that filter — not silently fall back to "all"
    # while the toolbar tag stays on 未完成.
    _create_subject(client)
    sid = _subject_id(client)
    url = "https://www.youtube.com/playlist?list=PLtest"
    client.post("/import", data={"subject_id": sid, "url": url})

    import re

    page = client.get(f"/subjects/{sid}").text
    item_ids = [int(x) for x in re.findall(r'id="item-(\d+)"', page)]
    # Mark the first item done so it should be hidden under "incomplete".
    client.post(f"/items/{item_ids[0]}/cycle")  # -> in_progress
    client.post(f"/items/{item_ids[0]}/cycle")  # -> done

    # Re-import with the incomplete filter active (as the form now sends it).
    r = client.post(
        "/import",
        data={"subject_id": sid, "url": url, "filter": "incomplete"},
    )
    assert r.status_code == 200
    # The done item must not appear in the re-rendered resources fragment.
    assert f'id="item-{item_ids[0]}"' not in r.text
    # The two not-yet-done items remain.
    assert r.text.count('class="item-row') == 2


def test_item_sort_duration_and_title(client):
    sid = _imported_subject(client)
    original_ids = _item_ids(client, sid)
    assert len(original_ids) == 3

    duration_desc = client.get(f"/subjects/{sid}?sort=duration_desc").text
    assert _item_ids_from_html(duration_desc) == list(reversed(original_ids))

    title_asc = client.get(f"/subjects/{sid}?sort=title_asc").text
    assert _item_ids_from_html(title_asc) == [
        original_ids[1],  # Alpha
        original_ids[2],  # Bravo
        original_ids[0],  # Charlie
    ]

    title_desc = client.get(f"/subjects/{sid}?sort=title_desc").text
    assert _item_ids_from_html(title_desc) == [
        original_ids[0],  # Charlie
        original_ids[2],  # Bravo
        original_ids[1],  # Alpha
    ]


def test_item_sort_incomplete_first(client):
    sid = _imported_subject(client)
    ids = _item_ids(client, sid)
    client.post(f"/items/{ids[0]}/cycle")  # -> in_progress
    client.post(f"/items/{ids[0]}/cycle")  # -> done

    page = client.get(f"/subjects/{sid}?sort=incomplete_first").text
    assert _item_ids_from_html(page) == [ids[1], ids[2], ids[0]]


def test_sort_state_is_preserved_in_controls(client):
    sid = _imported_subject(client)
    page = client.get(f"/subjects/{sid}?filter=incomplete&sort=title_desc&edit=1").text
    assert 'name="sort" value="title_desc"' in page
    assert 'value="title_desc" selected' in page
    assert "?filter=all&sort=title_desc&edit=1" in page
    assert "?filter=incomplete&sort=title_desc" in page


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
    return _item_ids_from_html(page)


def _item_ids_from_html(html):
    import re

    return [int(x) for x in re.findall(r'id="item-(\d+)"', html)]


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


# --- Floating progress widget -----------------------------------------------


def test_home_shows_floating_overall_progress(client):
    sid = _imported_subject(client)  # 3 items, none done yet
    home = client.get("/").text
    assert 'id="floating-progress"' in home
    assert "總進度" in home
    assert "0/3" in home


def test_subject_page_shows_floating_progress(client):
    sid = _imported_subject(client, name="日語")
    page = client.get(f"/subjects/{sid}").text
    assert 'id="floating-progress"' in page
    # Title is the subject name, inside the floating widget.
    assert 'class="fp-title"' in page
    assert "日語" in page


def test_cycle_updates_floating_widget_oob(client):
    sid = _imported_subject(client)
    iid = _item_ids(client, sid)[0]
    r = client.post(f"/items/{iid}/cycle")  # -> in_progress
    # Floating widget refreshed out-of-band alongside the row + resource bar.
    assert 'id="floating-progress"' in r.text
    assert 'hx-swap-oob="true"' in r.text


def test_floating_marks_complete_at_100_percent(client):
    sid = _imported_subject(client)
    for iid in _item_ids(client, sid):
        client.post(f"/items/{iid}/cycle")  # -> in_progress
        client.post(f"/items/{iid}/cycle")  # -> done
    page = client.get(f"/subjects/{sid}").text
    assert "is-complete" in page  # all items done
    assert "3/3" in page


def test_floating_hidden_when_no_items(client):
    _create_subject(client, name="空主題")
    sid = _subject_id(client)
    page = client.get(f"/subjects/{sid}").text
    # Element still present (so OOB swaps have a target) but visually hidden.
    assert 'id="floating-progress"' in page
    assert "is-empty" in page


# --- Home: per-subject progress bars (feature ①) ----------------------------


def test_home_subject_card_shows_progress(client):
    sid = _imported_subject(client)  # 3 items, none done
    home = client.get("/").text
    assert "0 個資源" not in home  # the card now shows real progress, not just count
    assert 'class="subject-info"' in home
    assert "0%" in home  # nothing done yet

    # Finish one of three → card reflects 33%.
    iid = _item_ids(client, sid)[0]
    client.post(f"/items/{iid}/cycle")  # -> in_progress
    client.post(f"/items/{iid}/cycle")  # -> done
    assert "33%" in client.get("/").text


# --- Home: goal dashboard banner (feature ②) --------------------------------


def _future_date(days=40):
    from datetime import date, timedelta

    return (date.today() + timedelta(days=days)).isoformat()


def test_home_prompts_to_set_goal_when_none(client):
    home = client.get("/").text
    assert 'id="goal-banner"' in home
    assert "設定考試目標" in home  # the set-goal call to action
    assert 'hx-post="/goal"' in home


def test_set_goal_renders_countdown_and_quota(client):
    _imported_subject(client)  # 3 unwatched videos to spread over the runway
    r = client.post("/goal", data={"name": "JLPT N4", "exam_date": _future_date(40)})
    assert r.status_code == 200
    assert "JLPT N4" in r.text
    assert "倒數 40 天" in r.text
    assert "今天" in r.text and "支" in r.text  # daily quota
    assert "還沒看" in r.text

    # Banner now persists on the home page.
    home = client.get("/").text
    assert "JLPT N4" in home
    assert "倒數 40 天" in home


def test_goal_quota_counts_only_unwatched(client):
    sid = _imported_subject(client)
    for iid in _item_ids(client, sid):  # finish everything
        client.post(f"/items/{iid}/cycle")
        client.post(f"/items/{iid}/cycle")
    r = client.post("/goal", data={"name": "N4", "exam_date": _future_date(30)})
    assert "全部完成" in r.text  # 0 remaining → done pace, quota hidden


def test_clear_goal_returns_setup_form(client):
    client.post("/goal", data={"name": "N4", "exam_date": _future_date(20)})
    r = client.delete("/goal")
    assert r.status_code == 200
    assert "設定考試目標" in r.text
    assert "倒數" not in r.text


def test_set_goal_bad_date_is_ignored(client):
    r = client.post("/goal", data={"name": "N4", "exam_date": "not-a-date"})
    assert r.status_code == 200
    assert "設定考試目標" in r.text  # stayed on the setup form, no crash


# --- Migration: fold legacy per-video resources into one bucket -------------


def test_merge_single_video_resources(engine, monkeypatch):
    """Legacy data with one resource per standalone video collapses into the
    single '個別影片' bucket, deduping by video_id and re-sequencing positions."""
    from sqlmodel import Session, select

    from app import db as dbmod
    from app.models import SINGLES_SOURCE, Item, Resource, ResourceType, Subject

    monkeypatch.setattr(dbmod, "engine", engine)
    with Session(engine) as s:
        sub = Subject(name="日語 N5")
        s.add(sub)
        s.commit()
        s.refresh(sub)
        rids = []
        for i, title in enumerate(["数字", "数量詞", "感応詞"]):
            r = Resource(
                subject_id=sub.id,
                type=ResourceType.video,
                source_url=f"https://youtu.be/v{i}",
                title=title,
            )
            s.add(r)
            s.commit()
            s.refresh(r)
            rids.append(r.id)
            s.add(Item(resource_id=r.id, video_id=f"v{i}", title=title, position=0))
            s.commit()
        # A duplicate of v0 living under the 2nd resource must be dropped.
        s.add(Item(resource_id=rids[1], video_id="v0", title="dup", position=1))
        s.commit()

    dbmod._merge_single_video_resources()

    with Session(engine) as s:
        resources = s.exec(select(Resource)).all()
        assert len(resources) == 1
        bucket = resources[0]
        assert bucket.title == "個別影片"
        assert bucket.source_url == SINGLES_SOURCE
        assert sorted((it.video_id, it.position) for it in bucket.items) == [
            ("v0", 0),
            ("v1", 1),
            ("v2", 2),
        ]

    # Idempotent: a second pass leaves the already-merged subject untouched.
    dbmod._merge_single_video_resources()
    with Session(engine) as s:
        assert len(s.exec(select(Resource)).all()) == 1
        assert len(s.exec(select(Item)).all()) == 3


# --- Cross-resource status sync (same video appearing in multiple lists) -----


def _two_playlist_subject(client):
    """Subject with two playlists sharing the same videos (vid1/vid2/vid3)."""
    _create_subject(client)
    sid = _subject_id(client)
    for lst in ("PLa", "PLb"):
        client.post(
            "/import",
            data={"subject_id": sid, "url": f"https://www.youtube.com/playlist?list={lst}"},
        )
    return sid


def test_status_syncs_across_lists_same_subject(client, engine):
    from sqlmodel import Session, select

    from app.models import Item, ItemStatus

    sid = _two_playlist_subject(client)
    with Session(engine) as s:
        copies = s.exec(select(Item).where(Item.video_id == "vid1")).all()
        assert len(copies) == 2  # one row per playlist
        clicked = copies[0].id

    # Cycle one copy to done (not_started → in_progress → done).
    client.post(f"/items/{clicked}/cycle")
    client.post(f"/items/{clicked}/cycle")

    with Session(engine) as s:
        copies = s.exec(select(Item).where(Item.video_id == "vid1")).all()
        assert all(it.status is ItemStatus.done for it in copies)
        # A different video stays untouched.
        others = s.exec(select(Item).where(Item.video_id == "vid2")).all()
        assert all(it.status is ItemStatus.not_started for it in others)


def test_status_syncs_across_subjects(client, engine):
    from sqlmodel import Session, select

    from app.models import Item, ItemStatus

    _create_subject(client, name="主題一")
    s1 = _subject_id(client)
    client.post(
        "/import",
        data={"subject_id": s1, "url": "https://www.youtube.com/playlist?list=PLa"},
    )
    _create_subject(client, name="主題二")
    s2 = _subject_id(client)
    client.post(
        "/import",
        data={"subject_id": s2, "url": "https://www.youtube.com/watch?v=vid1"},
    )

    with Session(engine) as s:
        copies = s.exec(select(Item).where(Item.video_id == "vid1")).all()
        assert len(copies) == 2  # one in each subject
        clicked = copies[0].id

    client.post(f"/items/{clicked}/cycle")
    client.post(f"/items/{clicked}/cycle")

    with Session(engine) as s:
        copies = s.exec(select(Item).where(Item.video_id == "vid1")).all()
        assert all(it.status is ItemStatus.done for it in copies)


def test_subject_progress_dedups_shared_video(client):
    sid = _two_playlist_subject(client)
    page = client.get(f"/subjects/{sid}").text
    # 2 playlists × 3 videos = 6 rows but only 3 unique; subject progress
    # counts the 3 unique videos, never 6.
    assert "0/6" not in page
    assert "0/3" in page


def test_cycle_response_oob_updates_sibling_row(client, engine):
    from sqlmodel import Session, select

    from app.models import Item

    sid = _two_playlist_subject(client)
    with Session(engine) as s:
        copies = s.exec(select(Item).where(Item.video_id == "vid1")).all()
        clicked, sibling = copies[0].id, copies[1].id

    r = client.post(f"/items/{clicked}/cycle")
    # The sibling copy comes back as an out-of-band swap so it updates live.
    assert f'id="item-{sibling}"' in r.text
    assert 'hx-swap-oob="true"' in r.text
