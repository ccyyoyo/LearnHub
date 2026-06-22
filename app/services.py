"""Aggregation helpers shared by routers/templates.

Progress is computed on the fly from ``Item.status`` rather than stored, so the
data model stays free of redundant counters (PRD §8 note).
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Item, ItemStatus, Resource


@dataclass(frozen=True)
class Progress:
    done: int
    total: int

    @property
    def percent(self) -> int:
        if self.total == 0:
            return 0
        return round(self.done / self.total * 100)


def item_progress(items: list[Item]) -> Progress:
    total = len(items)
    done = sum(1 for it in items if it.status is ItemStatus.done)
    return Progress(done=done, total=total)


def resource_progress(resource: Resource) -> Progress:
    return item_progress(list(resource.items))


# Status cycle used by the one-click toggle (FR-3.1):
# not_started → in_progress → done → not_started.
_NEXT = {
    ItemStatus.not_started: ItemStatus.in_progress,
    ItemStatus.in_progress: ItemStatus.done,
    ItemStatus.done: ItemStatus.not_started,
}


def next_status(current: ItemStatus) -> ItemStatus:
    return _NEXT[current]
