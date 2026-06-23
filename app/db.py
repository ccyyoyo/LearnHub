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


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped DB session."""
    with Session(engine) as session:
        yield session
