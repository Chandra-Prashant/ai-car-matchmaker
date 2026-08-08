"""Shared test fixtures.

Tests build their own inventory in a temporary database rather than reading
the checked-out seed file. A stale artifact must never be able to pass or fail
a test for reasons unrelated to the code.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.inventory.generator import GeneratorConfig, generate
from app.models.listing import Base
from app.repositories.listing_repository import ListingRepository

# Pinned so availability windows are stable across runs and machines.
TEST_REFERENCE_DATE = date(2026, 8, 8)
TEST_SEED = 20260808


@pytest.fixture(scope="session")
def config() -> GeneratorConfig:
    return GeneratorConfig(seed=TEST_SEED, reference_date=TEST_REFERENCE_DATE)


@pytest.fixture(scope="session")
def listings(config: GeneratorConfig):
    return generate(config)


@pytest.fixture(scope="session")
def db_path(tmp_path_factory: pytest.TempPathFactory, listings) -> Path:
    path = tmp_path_factory.mktemp("inventory") / "test.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all(listings)
        session.commit()
    engine.dispose()
    return path


@pytest.fixture
def session(db_path: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{db_path}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def repo(session: Session) -> ListingRepository:
    return ListingRepository(session)
