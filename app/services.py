"""Aggregation helpers shared by routers/templates.

Progress is computed on the fly from ``Item.status`` rather than stored, so the
data model stays free of redundant counters (PRD §8 note).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from .models import Attempt, Goal, Item, ItemStatus, Question, Resource, Subject

ITEM_SORTS = {
    "original",
    "incomplete_first",
    "duration_asc",
    "duration_desc",
    "title_asc",
    "title_desc",
}

# Progress can be measured two ways (user's choice in the toolbar): by number of
# videos finished, or by watch-time finished. "count" stays the default.
PROGRESS_MODES = ("count", "time")
DEFAULT_PROGRESS_MODE = "count"


def format_duration(seconds: int | None) -> str:
    """Render seconds as a clock string: ``12:34`` or ``1:02:03``."""
    total = int(seconds or 0)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def normalize_item_sort(sort: str) -> str:
    return sort if sort in ITEM_SORTS else "original"


def sort_items(items: list[Item], sort: str) -> list[Item]:
    sort = normalize_item_sort(sort)
    items_by_position = sorted(items, key=lambda it: it.position)
    if sort == "incomplete_first":
        return sorted(items_by_position, key=lambda it: it.status is ItemStatus.done)
    if sort == "duration_asc":
        return sorted(
            items_by_position,
            key=lambda it: (it.duration_seconds is None, it.duration_seconds or 0),
        )
    if sort == "duration_desc":
        return sorted(
            items_by_position,
            key=lambda it: (it.duration_seconds is None, -(it.duration_seconds or 0)),
        )
    if sort == "title_asc":
        return sorted(items_by_position, key=lambda it: it.title.casefold())
    if sort == "title_desc":
        return sorted(items_by_position, key=lambda it: it.title.casefold(), reverse=True)
    return items_by_position


def _seconds(item: Item) -> int:
    return item.duration_seconds or 0


@dataclass(frozen=True)
class Progress:
    done: int  # count of finished videos, or finished seconds, per ``mode``
    total: int
    mode: str = DEFAULT_PROGRESS_MODE

    @property
    def percent(self) -> int:
        if self.total == 0:
            return 0
        return round(self.done / self.total * 100)

    @property
    def label(self) -> str:
        """Human label for the progress bar, in the units of the active mode."""
        if self.mode == "time":
            return f"{format_duration(self.done)} / {format_duration(self.total)}"
        return f"{self.done}/{self.total}"


def count_progress(items: list[Item]) -> Progress:
    total = len(items)
    done = sum(1 for it in items if it.status is ItemStatus.done)
    return Progress(done=done, total=total, mode="count")


def time_progress(items: list[Item]) -> Progress:
    total = sum(_seconds(it) for it in items)
    done = sum(_seconds(it) for it in items if it.status is ItemStatus.done)
    return Progress(done=done, total=total, mode="time")


def item_progress(items: list[Item], mode: str = DEFAULT_PROGRESS_MODE) -> Progress:
    return time_progress(items) if mode == "time" else count_progress(items)


def resource_progress(resource: Resource, mode: str = DEFAULT_PROGRESS_MODE) -> Progress:
    return item_progress(list(resource.items), mode)


def resource_total_seconds(resource: Resource) -> int:
    """Total watch-time of a resource (shown regardless of progress mode)."""
    return sum(_seconds(it) for it in resource.items)


@dataclass(frozen=True)
class ProgressPair:
    """Both progress readings for one item set, so the UI can switch modes
    client-side without re-querying the server."""

    count: Progress
    time: Progress


def progress_pair(items: list[Item]) -> ProgressPair:
    return ProgressPair(count=count_progress(items), time=time_progress(items))


def subject_progress(subject: Subject) -> ProgressPair:
    """Completion across every item in every resource under a subject."""
    items = [it for res in subject.resources for it in res.items]
    return progress_pair(items)


def overall_progress(subjects: list[Subject]) -> ProgressPair:
    """Completion across every item the learner has, used on the landing page."""
    items = [it for sub in subjects for res in sub.resources for it in res.items]
    return progress_pair(items)


# Status cycle used by the one-click toggle (FR-3.1):
# not_started → in_progress → done → not_started.
_NEXT = {
    ItemStatus.not_started: ItemStatus.in_progress,
    ItemStatus.in_progress: ItemStatus.done,
    ItemStatus.done: ItemStatus.not_started,
}


def next_status(current: ItemStatus) -> ItemStatus:
    return _NEXT[current]


# --- Goal / study plan (home dashboard banner) ------------------------------
#
# Turns "I have an exam on <date>" into today's marching orders: how many videos
# to finish per day to land on time, and whether the learner is ahead or behind
# the pace the calendar demands.

# Tolerance (in percentage points) around the expected pace before we call the
# learner "ahead" or "behind" rather than simply "on track".
_PACE_BAND = 3


@dataclass(frozen=True)
class StudyPlan:
    exam_name: str
    days_left: int  # whole days until the exam; 0 today, negative once past
    progress: Progress  # overall completion, by video count
    remaining_items: int  # videos not yet done
    remaining_seconds: int  # watch-time of the not-done videos
    daily_items: int  # videos/day needed to finish on time
    daily_minutes: int  # watch-minutes/day needed to finish on time
    expected_percent: int  # where the calendar says you "should" be by now

    @property
    def is_complete(self) -> bool:
        return self.progress.total > 0 and self.remaining_items == 0

    @property
    def is_overdue(self) -> bool:
        return self.days_left < 0 and not self.is_complete

    @property
    def countdown_label(self) -> str:
        if self.days_left > 1:
            return f"倒數 {self.days_left} 天"
        if self.days_left == 1:
            return "剩最後 1 天"
        if self.days_left == 0:
            return "就是今天!"
        return f"已過考試日 {abs(self.days_left)} 天"

    @property
    def pace(self) -> str:
        """One of: ``done`` / ``overdue`` / ``ahead`` / ``behind`` / ``on_track``."""
        if self.is_complete:
            return "done"
        if self.is_overdue:
            return "overdue"
        delta = self.progress.percent - self.expected_percent
        if delta >= _PACE_BAND:
            return "ahead"
        if delta <= -_PACE_BAND:
            return "behind"
        return "on_track"

    @property
    def pace_label(self) -> str:
        return {
            "done": "全部完成 🎉",
            "overdue": "已過期 ⏰",
            "ahead": "超前進度 🚀",
            "behind": "落後了 ⚠️",
            "on_track": "跟上進度 ✅",
        }[self.pace]


def _remaining_seconds(items: list[Item]) -> int:
    return sum(_seconds(it) for it in items if it.status is not ItemStatus.done)


def study_plan(goal: Goal, subjects: list[Subject], today: date) -> StudyPlan:
    """Compute the dashboard plan for ``goal`` against everything the learner has.

    The daily quota spreads the *remaining* work evenly over the days left; the
    expected percent spreads it over the *whole* run (goal-set date → exam) so
    we can say whether the learner is ahead of or behind schedule.
    """
    items = [it for sub in subjects for res in sub.resources for it in res.items]
    progress = count_progress(items)
    remaining_items = progress.total - progress.done
    remaining_seconds = _remaining_seconds(items)

    days_left = (goal.exam_date - today).days
    # Once the exam is here (or past) there's no "spread over N days" left, so
    # the day's quota is simply everything that remains.
    spread_days = max(days_left, 1)
    daily_items = math.ceil(remaining_items / spread_days) if remaining_items else 0
    daily_minutes = math.ceil(remaining_seconds / 60 / spread_days)

    start = goal.created_at.date()
    total_days = max((goal.exam_date - start).days, 1)
    elapsed = min(max((today - start).days, 0), total_days)
    expected_percent = round(elapsed / total_days * 100)

    return StudyPlan(
        exam_name=goal.name,
        days_left=days_left,
        progress=progress,
        remaining_items=remaining_items,
        remaining_seconds=remaining_seconds,
        daily_items=daily_items,
        daily_minutes=daily_minutes,
        expected_percent=expected_percent,
    )


# --- Quiz / question bank (Phase 3) -----------------------------------------
#
# All counts derived on the fly from Question/Attempt rows — no stored
# aggregates, same as progress above (PRD §8 note). Functions operate on loaded
# ORM objects so they stay pure and unit-testable.


def _latest_attempt(question: Question) -> Attempt | None:
    """The most recent answer to a question, or None if never attempted."""
    if not question.attempts:
        return None
    return max(question.attempts, key=lambda a: a.created_at)


def question_is_outstanding(question: Question) -> bool:
    """True when the learner's *latest* answer was wrong (a question to review)."""
    latest = _latest_attempt(question)
    return latest is not None and not latest.is_correct


def _item_questions(item: Item) -> list[Question]:
    return list(item.questions)


def item_attempt_count(item: Item) -> int:
    return sum(len(q.attempts) for q in item.questions)


def item_error_rate(item: Item) -> float:
    """Wrong answers / total answers across the item's questions (0 if none)."""
    total = item_attempt_count(item)
    if total == 0:
        return 0.0
    wrong = sum(1 for q in item.questions for a in q.attempts if not a.is_correct)
    return wrong / total


def recent_wrong_questions(item: Item) -> list[Question]:
    """Questions whose latest answer was wrong, newest-wrong first.

    This is the review pool the assembler reuses for high-error items.
    """
    scored: list[tuple[datetime, Question]] = []
    for q in item.questions:
        latest = _latest_attempt(q)
        if latest is not None and not latest.is_correct:
            scored.append((latest.created_at, q))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [q for _, q in scored]


def assemble_quiz_plan(item: Item, n: int) -> tuple[list[Question], int]:
    """Decide the make-up of an N-question quiz for ``item``.

    Reuse the learner's wrong questions first (free, real review); generate the
    remainder. A never-practiced item has no wrong questions, so it's all new.
    Wrong questions beyond N are dropped — we keep the most recently missed.
    Returns ``(reused_questions, count_to_generate)``.
    """
    reuse = recent_wrong_questions(item)[:n]
    return reuse, n - len(reuse)


def _subject_items(subject: Subject) -> list[Item]:
    return [it for res in subject.resources for it in res.items]


def select_practice_item(subject: Subject) -> Item | None:
    """Pick the item most in need of practice (home "練習推薦" → 出題, entry B).

    Never-practiced items come first (coverage), ordered by their place in the
    subject; once everything has been practiced, the highest error rate wins.
    """
    items = sorted(
        _subject_items(subject),
        key=lambda it: (it.resource.created_at, it.position),
    )
    if not items:
        return None
    never = [it for it in items if item_attempt_count(it) == 0]
    if never:
        return never[0]
    return max(items, key=item_error_rate)


def resolve_source_text(item: Item, transcript: str | None) -> str:
    """Fallback ladder for generation input: transcript → notes → title."""
    if transcript and transcript.strip():
        return transcript
    if item.note_md and item.note_md.strip():
        return item.note_md
    return item.title


@dataclass(frozen=True)
class QuizStats:
    """Home-page question-bank summary."""

    total_questions: int
    total_attempts: int
    correct_rate: int  # %, 0 when nothing answered
    wrong_count: int  # questions whose latest answer was wrong (to review)


def quiz_stats(questions: list[Question], attempts: list[Attempt]) -> QuizStats:
    total_attempts = len(attempts)
    correct = sum(1 for a in attempts if a.is_correct)
    correct_rate = round(correct / total_attempts * 100) if total_attempts else 0
    wrong_count = sum(1 for q in questions if question_is_outstanding(q))
    return QuizStats(
        total_questions=len(questions),
        total_attempts=total_attempts,
        correct_rate=correct_rate,
        wrong_count=wrong_count,
    )


@dataclass(frozen=True)
class SubjectPractice:
    """One row of the home "練習推薦" list."""

    subject: Subject
    practiced: bool
    error_rate: int  # %, only meaningful when practiced


def practice_recommendations(subjects: list[Subject]) -> list[SubjectPractice]:
    """Subjects ranked by need: never-practiced first, then error rate desc.

    Subjects with no items are skipped (nothing to practice).
    """
    rows: list[SubjectPractice] = []
    for subject in subjects:
        items = _subject_items(subject)
        if not items:
            continue
        attempts = sum(item_attempt_count(it) for it in items)
        if attempts == 0:
            rows.append(SubjectPractice(subject, practiced=False, error_rate=0))
            continue
        wrong = sum(
            1 for it in items for q in it.questions for a in q.attempts if not a.is_correct
        )
        rate = round(wrong / attempts * 100)
        rows.append(SubjectPractice(subject, practiced=True, error_rate=rate))
    rows.sort(key=lambda r: (r.practiced, -r.error_rate))
    return rows
