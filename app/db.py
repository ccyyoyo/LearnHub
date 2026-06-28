"""Database engine, session management, and table creation."""

from collections.abc import Iterator

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

settings = get_settings()

# ``check_same_thread`` is required so the SQLite connection can be shared
# across FastAPI's worker threads.
engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """Create tables if they don't exist.

    Phase 1 deliberately uses metadata create-all instead of Alembic; the PRD
    allows a simple table-creation step for P1 (§7 Migration row).
    """
    # Import models so their tables are registered on SQLModel.metadata.
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _ensure_columns()
    _merge_single_video_resources()


def _ensure_columns() -> None:
    """Add columns introduced after a DB was first created.

    ``create_all`` never alters an existing table, so a pre-existing
    ``learnhub.db`` would otherwise be missing newer nullable columns. We patch
    them in by hand (still no Alembic — see ``init_db``).
    """
    inspector = inspect(engine)
    if "item" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("item")}
    if "duration_seconds" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE item ADD COLUMN duration_seconds INTEGER"))


def _merge_single_video_resources() -> None:
    """Fold legacy per-video resources into one aggregate bucket per subject.

    Early imports gave every standalone video its own ``Resource`` (titled with
    the video name). Imports now collect them into a single "個別影片" bucket per
    subject; this one-time pass brings old data in line so they render together.
    Idempotent: a subject already holding a single normalized bucket is skipped.
    """
    from sqlmodel import select

    from .models import SINGLES_SOURCE, Item, Resource, ResourceType, Subject

    with Session(engine) as session:
        subjects = session.exec(select(Subject)).all()
        changed = False
        for subject in subjects:
            videos = sorted(
                (r for r in subject.resources if r.type == ResourceType.video),
                key=lambda r: r.created_at,
            )
            already_merged = (
                len(videos) == 1
                and videos[0].source_url == SINGLES_SOURCE
                and videos[0].title == "個別影片"
            )
            if not videos or already_merged:
                continue

            bucket = videos[0]
            bucket.source_url = SINGLES_SOURCE
            bucket.title = "個別影片"
            session.add(bucket)

            seen = {it.video_id for it in bucket.items}
            next_pos = max((it.position for it in bucket.items), default=-1) + 1
            for extra in videos[1:]:
                # Move via the relationship (not just the FK): appending to
                # ``bucket.items`` detaches the item from ``extra.items`` so the
                # delete-orphan cascade below won't take the moved items with it.
                for item in sorted(list(extra.items), key=lambda it: it.position):
                    if item.video_id in seen:
                        session.delete(item)
                        continue
                    item.position = next_pos
                    bucket.items.append(item)
                    seen.add(item.video_id)
                    next_pos += 1
                session.delete(extra)
            changed = True
        if changed:
            session.commit()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped DB session."""
    with Session(engine) as session:
        yield session
