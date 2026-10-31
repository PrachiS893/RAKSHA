"""Tests verifying test suite network and credential isolation."""

from collections.abc import Generator
import httpx
import pytest
from starlette.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from app.config import settings
from app.constants import AlertLevel, AlertStatus
from app.db import get_session
from app.main import app
from app.models import Alert, Delivery, Region, Subscription
from app.seed import seed_database


@pytest.fixture(name="client_and_session")
def client_and_session_fixture() -> Generator[tuple[TestClient, Session], None, None]:
    """Provide TestClient and direct Session sharing an isolated in-memory SQLite database."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        seed_database(session)

    def get_test_session() -> Generator[Session, None, None]:
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    with Session(test_engine) as session:
        with TestClient(app) as test_client:
            yield test_client, session
    app.dependency_overrides.clear()


def test_default_environment_variables_are_isolated() -> None:
    """Verify that default test settings are safely blanked and isolated from real .env."""
    assert settings.TELEGRAM_BOT_TOKEN == ""
    assert settings.DEMO_TELEGRAM_CHAT_ID == ""
    assert settings.LLM_API_KEY == ""
    assert settings.ORS_API_KEY == ""
    assert settings.LLM_ENABLED is False
    assert settings.AUTO_SEED is False
    assert settings.DATABASE_URL == "sqlite://"


def test_unmocked_httpx_call_raises_error() -> None:
    """Verify that any unmocked real network call attempt immediately raises a clear error."""
    # 1. Test via httpx.Client()
    with pytest.raises(RuntimeError, match="real network call in a test"):
        with httpx.Client() as client:
            client.get("https://api.telegram.org")

    # 2. Test via top-level httpx.get()
    with pytest.raises(RuntimeError, match="real network call in a test"):
        httpx.get("https://api.groq.com/openai/v1/chat/completions")


def test_default_environment_approving_alert_skips_telegram(
    client_and_session: tuple[TestClient, Session],
) -> None:
    """Verify that in the default test environment, approving an alert creates a Telegram delivery

    row with status 'skipped' and detail 'no bot token configured' without making network calls.
    """
    client, session = client_and_session

    # Verify no real bot token is configured
    assert settings.TELEGRAM_BOT_TOKEN == ""

    # Find Zone A
    region_a = session.exec(select(Region).where(Region.name == "Zone A - Riverside")).first()
    assert region_a is not None

    # Ensure a subscriber with a Telegram chat ID exists in Zone A
    sub = session.exec(
        select(Subscription).where(
            Subscription.region_id == region_a.id,
            Subscription.telegram_chat_id.is_not(None),
        )
    ).first()
    if sub is None:
        sub = Subscription(
            region_id=region_a.id,
            name="Demo Citizen 1",
            telegram_chat_id="123456789",
        )
        session.add(sub)
        session.commit()
    else:
        # Give sub a dummy chat id if it was blank
        if not sub.telegram_chat_id:
            sub.telegram_chat_id = "123456789"
            session.add(sub)
            session.commit()

    # Create a draft warning for Zone A
    draft = Alert(
        region_id=region_a.id,
        level=AlertLevel.WARNING.value,
        message="Flood warning for Zone A - Riverside: move valuables to higher ground.",
        status=AlertStatus.DRAFT.value,
    )
    session.add(draft)
    session.commit()
    session.refresh(draft)

    # Approve the draft alert via API endpoint
    response = client.post(
        f"/alerts/{draft.id}/approve",
        json={"approved_by": "Coordinator Sarah"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "sent"

    # Verify Telegram delivery row in DB is marked 'skipped'
    deliveries = session.exec(
        select(Delivery).where(
            Delivery.alert_id == draft.id,
            Delivery.channel == "telegram",
        )
    ).all()
    assert len(deliveries) >= 1
    telegram_delivery = deliveries[0]
    assert telegram_delivery.status == "skipped"
    assert telegram_delivery.detail == "no bot token configured"
    assert telegram_delivery.sent_at is None
