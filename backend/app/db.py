"""Database engine and session management.

Single place that knows where the SQLite file lives and how sessions are
created, so nothing above this has to construct an engine.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.registry import Base  # registers every table

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "seed" / "marketplace.db"


#: Repository root — the anchor for relative DATABASE_PATH values.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def database_path() -> Path:
    """Resolve the database location.

    Environment variable wins so Docker can point elsewhere without code
    changes; otherwise fall back to the repository's seed directory.

    A relative DATABASE_PATH resolves against the repository root, not the
    working directory. Otherwise the same .env would point somewhere
    different depending on whether the process started in backend/ or at the
    root — which is exactly the bug this replaced.
    """
    env = os.getenv("DATABASE_PATH")
    if not env:
        return _DEFAULT_DB_PATH

    candidate = Path(env).expanduser()
    if not candidate.is_absolute():
        candidate = _REPO_ROOT / candidate
    return candidate.resolve()


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        path = database_path()
        _engine = create_engine(
            f"sqlite:///{path}",
            # SQLite defaults to rejecting cross-thread use; FastAPI's
            # threadpool needs this off.
            connect_args={"check_same_thread": False},
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context-managed session for scripts and tools."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def create_all() -> None:
    """Create tables. Used by tests against an in-memory or temporary file."""
    Base.metadata.create_all(get_engine())


def reset_engine() -> None:
    """Drop cached engine and factory — tests use this when repointing
    DATABASE_PATH between cases."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
