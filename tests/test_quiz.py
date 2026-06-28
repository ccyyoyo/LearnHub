"""Quiz generation + answering + bank stats (Phase 3).

The provider and transcript fetcher are faked via dependency overrides, the same
way the YouTube client is faked in conftest — no network, no real model calls.
"""

import re

import pytest
from sqlmodel import Session, select

from app.ai.base import GeneratedQuestion
from app.main import app
from app.models import Attempt, Question
from app.routers.quiz import get_question_provider, get_transcript_fetcher


class FakeProvider:
    """Returns ``n`` canned questions; option 0 is always correct."""

    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    def generate(self, source_text: str, n: int) -> list[GeneratedQuestion]:
        self.calls.append((source_text, n))
        return [
            GeneratedQuestion(
                stem=f"これは問題{i}ですか。",
                options=["正解", "誘答1", "誘答2", "誘答3"],
                answer_index=0,
                explanation="因為第一個選項正確。",
            )
            for i in range(n)
        ]


class FakeFetcher:
    def __init__(self, text: str | None = "これは字幕のテキストです"):
        self.text = text

    def fetch(self, video_id: str) -> str | None:
        return self.text


@pytest.fixture
def provider():
    p = FakeProvider()
    app.dependency_overrides[get_question_provider] = lambda: p
    yield p
    app.dependency_overrides.pop(get_question_provider, None)


@pytest.fixture
def fetcher():
    f = FakeFetcher()
    app.dependency_overrides[get_transcript_fetcher] = lambda: f
    yield f
    app.dependency_overrides.pop(get_transcript_fetcher, None)


# --- helpers ----------------------------------------------------------------


def _imported_subject(client, name="日語 N5"):
    client.post("/subjects", data={"name": name})
    sid = int(re.findall(r"/subjects/(\d+)", client.get("/").text)[-1])
    client.post(
        "/import",
        data={"subject_id": sid, "url": "https://www.youtube.com/playlist?list=PLtest"},
    )
    return sid


def _item_ids(client, sid):
    page = client.get(f"/subjects/{sid}").text
    return [int(x) for x in re.findall(r'id="item-(\d+)"', page)]


def _quiz_question_ids(html):
    return [int(x) for x in re.findall(r'id="quiz-q-(\d+)"', html)]


# --- UI presence ------------------------------------------------------------


def test_quiz_button_on_subject_page(client):
    sid = _imported_subject(client)
    page = client.get(f"/subjects/{sid}").text
    assert "出題" in page
    assert "/items/" in page and "/quiz" in page
    # Quiz launcher is hidden in edit mode (checkboxes take over).
    assert "出題" not in client.get(f"/subjects/{sid}?edit=1").text


# --- generation -------------------------------------------------------------


def test_generate_creates_and_renders_questions(client, engine, provider, fetcher):
    sid = _imported_subject(client)
    iid = _item_ids(client, sid)[0]

    r = client.post(f"/items/{iid}/quiz", data={"n": 3})
    assert r.status_code == 200
    assert len(_quiz_question_ids(r.text)) == 3
    assert "これは問題0ですか。" in r.text

    # Persisted in the DB.
    with Session(engine) as s:
        qs = s.exec(select(Question).where(Question.item_id == iid)).all()
        assert len(qs) == 3

    # Transcript was used as the source.
    assert provider.calls[0][0] == fetcher.text
    assert provider.calls[0][1] == 3


def test_n_is_clamped_to_ten(client, provider, fetcher):
    sid = _imported_subject(client)
    iid = _item_ids(client, sid)[0]
    r = client.post(f"/items/{iid}/quiz", data={"n": 50})
    assert len(_quiz_question_ids(r.text)) == 10


def test_fallback_to_title_when_no_transcript(client, provider, fetcher):
    fetcher.text = None  # no captions
    sid = _imported_subject(client)
    iid = _item_ids(client, sid)[0]
    client.post(f"/items/{iid}/quiz", data={"n": 1})
    # Source falls back to the video title (first item = "Charlie").
    assert provider.calls[-1][0] == "Charlie"


# --- answering --------------------------------------------------------------


def test_answer_correct_and_wrong(client, engine, provider, fetcher):
    sid = _imported_subject(client)
    iid = _item_ids(client, sid)[0]
    r = client.post(f"/items/{iid}/quiz", data={"n": 2})
    qids = _quiz_question_ids(r.text)
    assert len(qids) == 2

    correct = client.post(f"/questions/{qids[0]}/answer", data={"chosen_index": 0})
    assert "答對" in correct.text
    assert "因為第一個選項正確。" in correct.text  # explanation shown

    wrong = client.post(f"/questions/{qids[1]}/answer", data={"chosen_index": 2})
    assert "答錯" in wrong.text

    with Session(engine) as s:
        attempts = s.exec(select(Attempt)).all()
        assert len(attempts) == 2
        assert sum(1 for a in attempts if a.is_correct) == 1


# --- assembly: reuse wrong questions ----------------------------------------


def test_regenerate_reuses_wrong_questions(client, provider, fetcher):
    sid = _imported_subject(client)
    iid = _item_ids(client, sid)[0]

    r1 = client.post(f"/items/{iid}/quiz", data={"n": 2})
    qids = _quiz_question_ids(r1.text)
    for qid in qids:  # answer both wrong
        client.post(f"/questions/{qid}/answer", data={"chosen_index": 1})

    r2 = client.post(f"/items/{iid}/quiz", data={"n": 3})
    # 3-question quiz = 2 reused wrong + 1 newly generated.
    assert len(_quiz_question_ids(r2.text)) == 3
    assert provider.calls[-1][1] == 1  # only one new question generated


# --- provider error ---------------------------------------------------------


def test_provider_error_shows_friendly_message(client, fetcher):
    class Boom:
        def generate(self, source_text, n):
            from app.ai.errors import AIError

            raise AIError("配額用完了。")

    app.dependency_overrides[get_question_provider] = lambda: Boom()
    try:
        sid = _imported_subject(client)
        iid = _item_ids(client, sid)[0]
        r = client.post(f"/items/{iid}/quiz", data={"n": 2})
        assert r.status_code == 200
        assert "配額用完了。" in r.text
    finally:
        app.dependency_overrides.pop(get_question_provider, None)


# --- home stats + practice entry --------------------------------------------


def test_home_quiz_stats_and_recommendation(client, provider, fetcher):
    sid = _imported_subject(client)
    iid = _item_ids(client, sid)[0]

    # Before any quiz: subject is "never practiced".
    home = client.get("/").text
    assert "題庫" in home
    assert "未練習" in home

    r = client.post(f"/items/{iid}/quiz", data={"n": 2})
    qids = _quiz_question_ids(r.text)
    client.post(f"/questions/{qids[0]}/answer", data={"chosen_index": 0})  # correct
    client.post(f"/questions/{qids[1]}/answer", data={"chosen_index": 1})  # wrong

    home = client.get("/").text
    assert "題庫 <strong>2</strong> 題" in home
    assert "正確率 <strong>50%</strong>" in home
    assert "錯題 <strong>1</strong>" in home
    assert "錯誤率 50%" in home  # subject now practiced, shown with rate


def test_practice_route_picks_item_and_offers_quiz(client):
    sid = _imported_subject(client)
    resp = client.get(f"/practice/{sid}")
    assert resp.status_code == 200
    assert "推薦練習" in resp.text
    assert "/quiz" in resp.text  # launcher wired to generate


def test_prompt_targets_language_not_plot_recall():
    from app.ai.prompts import build_prompt

    prompt = build_prompt("これは会社へ行く話です。", 3)
    assert "3" in prompt
    assert "語彙" in prompt and "文法" in prompt  # tests language ability
    assert "劇情" in prompt  # explicitly forbids plot/content recall
    assert "これは会社へ行く話です。" in prompt  # source embedded


def test_practice_empty_subject(client):
    client.post("/subjects", data={"name": "空主題"})
    sid = int(re.findall(r"/subjects/(\d+)", client.get("/").text)[-1])
    page = client.get(f"/practice/{sid}").text
    assert "還沒有可練習的影片" in page


# --- allocate_questions -----------------------------------------------------

from app.services import allocate_questions


def test_allocate_even_when_weights_equal():
    # 3 單元權重相同 → 6 題平均每單元 2 題。
    plan = allocate_questions([(1, 1.0), (2, 1.0), (3, 1.0)], 6)
    assert plan == {1: 2, 2: 2, 3: 2}


def test_allocate_weights_toward_high_error():
    # 高錯誤率單元拿較多題;保底每單元 1 題;總和守恆。
    plan = allocate_questions([(1, 0.8), (2, 0.2)], 10)
    assert sum(plan.values()) == 10
    assert plan[1] > plan[2]
    assert plan[2] >= 1


def test_allocate_min_one_each_when_n_equals_units():
    plan = allocate_questions([(1, 0.9), (2, 0.0), (3, 0.5)], 3)
    assert plan == {1: 1, 2: 1, 3: 1}


def test_allocate_fewer_questions_than_units_picks_top_weighted():
    # n < 單元數 → 無法每個都給;權重最高的 n 個各 1 題,其餘 0。
    plan = allocate_questions([(1, 0.1), (2, 0.9), (3, 0.5), (4, 0.0)], 2)
    assert sum(plan.values()) == 2
    assert plan == {2: 1, 3: 1, 1: 0, 4: 0}


def test_allocate_single_unit_gets_all():
    assert allocate_questions([(7, 0.0)], 5) == {7: 5}


def test_allocate_all_zero_weight_falls_back_to_even():
    plan = allocate_questions([(1, 0.0), (2, 0.0)], 4)
    assert plan == {1: 2, 2: 2}


# --- practice_units / practice_weight ---------------------------------------

from app.models import Item, Question as QModel, Resource, Subject
from app.services import practice_units, practice_weight


def _make_subject_with_items(session):
    sub = Subject(name="日語 N5")
    session.add(sub)
    session.commit()
    session.refresh(sub)
    res = Resource(subject_id=sub.id, type="playlist", source_url="u", title="t")
    session.add(res)
    session.commit()
    session.refresh(res)
    items = []
    for pos in range(3):
        it = Item(resource_id=res.id, video_id=f"v{pos}", title=f"T{pos}", position=pos)
        session.add(it)
        items.append(it)
    session.commit()
    for it in items:
        session.refresh(it)
    return sub, items


def _answer(session, item, *, correct: bool):
    q = QModel(
        item_id=item.id,
        stem="?",
        options_json='["a","b","c","d"]',
        answer_index=0,
        explanation="e",
    )
    session.add(q)
    session.commit()
    session.refresh(q)
    session.add(
        Attempt(question_id=q.id, chosen_index=0 if correct else 1, is_correct=correct)
    )
    session.commit()


def test_practice_weight_never_practiced_is_max(engine):
    with Session(engine) as s:
        _, items = _make_subject_with_items(s)
        assert practice_weight(items[0]) == 1.0  # no attempts → top priority


def test_practice_weight_practiced_uses_error_rate(engine):
    with Session(engine) as s:
        _, items = _make_subject_with_items(s)
        _answer(s, items[0], correct=False)  # 1 wrong of 1 → rate 1.0
        s.refresh(items[0])
        assert practice_weight(items[0]) == 1.0
        _answer(s, items[0], correct=True)  # now 1 wrong of 2 → 0.5
        s.refresh(items[0])
        assert practice_weight(items[0]) == 0.5


def test_practice_units_sorts_never_practiced_first_then_error(engine):
    with Session(engine) as s:
        sub, items = _make_subject_with_items(s)
        _answer(s, items[0], correct=True)  # practiced, 0% error
        _answer(s, items[1], correct=False)  # practiced, 100% error
        # items[2] never practiced
        s.refresh(sub)
        units = practice_units(sub)
        ids = [u.item.id for u in units]
        assert ids[0] == items[2].id  # never-practiced first
        assert ids[1] == items[1].id  # then highest error
        assert ids[2] == items[0].id
        assert units[0].practiced is False
        assert units[1].error_rate == 100
        assert units[0].attempts == 0
