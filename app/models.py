"""SQLModel domain models (PRD §8).

The schema is intentionally shaped to absorb Phase 2 (notes) and Phase 3 (AI)
without a rewrite (G4 / NFR-4): ``Item.note_md`` already exists for Phase 2, and
nothing here is specific to YouTube beyond ``video_id`` / ``thumbnail_url``.
"""

from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResourceType(str, Enum):
    playlist = "playlist"
    video = "video"


class ItemStatus(str, Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    done = "done"


# Allowed forward transitions when a user clicks the status toggle, plus the
# human label shown in the UI.
STATUS_LABELS: dict[ItemStatus, str] = {
    ItemStatus.not_started: "未開始",
    ItemStatus.in_progress: "進行中",
    ItemStatus.done: "已完成",
}


class Goal(SQLModel, table=True):
    """The learner's headline target, e.g. 「JLPT N4・2026-07-05」.

    Treated as a singleton (at most one row): it anchors the home dashboard
    banner — the exam countdown, the per-day quota, and the ahead/behind pace.
    ``created_at`` doubles as the plan's start date for pace calculation.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    exam_date: date
    created_at: datetime = Field(default_factory=utcnow)


class Subject(SQLModel, table=True):
    """A learning topic, e.g. 「日語 N5」or「Rust」(FR-1)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)

    resources: list["Resource"] = Relationship(
        back_populates="subject",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class Resource(SQLModel, table=True):
    """A playlist or a standalone video imported under a subject (FR-2)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    type: ResourceType
    source_url: str
    title: str
    created_at: datetime = Field(default_factory=utcnow)

    subject: Optional[Subject] = Relationship(back_populates="resources")
    items: list["Item"] = Relationship(
        back_populates="resource",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class Item(SQLModel, table=True):
    """A single video — the unit a learner ticks off (FR-3)."""

    __table_args__ = (
        # Idempotent imports: a video appears at most once per resource (FR-2.4).
        UniqueConstraint("resource_id", "video_id", name="uq_item_resource_video"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    resource_id: int = Field(foreign_key="resource.id", index=True)
    video_id: str = Field(index=True)
    title: str
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[int] = None  # video length in seconds (None if unknown)
    position: int = 0
    status: ItemStatus = Field(default=ItemStatus.not_started)
    note_md: Optional[str] = None  # Phase 2
    updated_at: datetime = Field(default_factory=utcnow)

    resource: Optional[Resource] = Relationship(back_populates="items")

    @property
    def youtube_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"
