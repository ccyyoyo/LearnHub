"""Aggregation helpers shared by routers/templates.

Progress is computed on the fly from ``Item.status`` rather than stored, so the
data model stays free of redundant counters (PRD §8 note).
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Item, ItemStatus, Resource, Subject

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
