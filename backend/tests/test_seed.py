"""Tests for database seeding functionality and idempotency."""

from collections.abc import Generator
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from app.models import Inventory, Region, Request, Subscription, Warehouse
from app.seed import seed_database


@pytest.fixture(name="session")
def session_fixture() -> Generator[Session, None, None]:
    """Create an isolated in-memory SQLite database session for seed tests."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        yield session


def test_seed_database_counts_and_idempotency(session: Session) -> None:
    """Verify that seed_database populates expected tables and is idempotent."""
    # First seed execution
    first_counts = seed_database(session)
    assert first_counts["regions"] == 3
    assert first_counts["warehouses"] == 3
    assert first_counts["inventory"] == 12
    assert first_counts["subscriptions"] == 4
    assert first_counts["requests"] == 0

    # Verify directly via queries
    regions = session.exec(select(Region)).all()
    warehouses = session.exec(select(Warehouse)).all()
    inventory = session.exec(select(Inventory)).all()
    subscriptions = session.exec(select(Subscription)).all()
    requests = session.exec(select(Request)).all()

    assert len(regions) == 3
    assert len(warehouses) == 3
    assert len(inventory) == 12
    assert len(subscriptions) == 4
    assert len(requests) == 0

    # Verify simulated flood flag
    for region in regions:
        assert region.is_simulated_flood is True

    # Second seed execution (idempotency check)
    second_counts = seed_database(session)
    assert second_counts["regions"] == 3
    assert second_counts["warehouses"] == 3
    assert second_counts["inventory"] == 12
    assert second_counts["subscriptions"] == 4
    assert second_counts["requests"] == 0

    regions_after = session.exec(select(Region)).all()
    assert len(regions_after) == 3
