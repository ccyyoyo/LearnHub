"""Aggregation helpers shared by routers/templates.

Progress is computed on the fly from ``Item.status`` rather than stored, so the
data model stays free of redundant counters (PRD §8 note).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlmodel import Session, select

from .models import AIArtifact, Item, ItemStatus, Resource


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


def artifacts_by_video(
    session: Session, video_ids: Iterable[str]
) -> dict[str, dict[str, AIArtifact]]:
    """Map ``{video_id: {kind_value: artifact}}`` for the given videos.

    Lets the subject page render already-generated AI results on load (and after
    bulk edits) in one query, instead of an HTMX round-trip per item.
    """
    ids = list(video_ids)
    if not ids:
        return {}
    rows = session.exec(select(AIArtifact).where(AIArtifact.video_id.in_(ids))).all()
    out: dict[str, dict[str, AIArtifact]] = {}
    for art in rows:
        out.setdefault(art.video_id, {})[art.kind.value] = art
    return out
