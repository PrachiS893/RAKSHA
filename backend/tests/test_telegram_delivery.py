"""Tests for Telegram Bot delivery, credential isolation, and security sanitization."""

from collections.abc import Generator
from unittest.mock import MagicMock
import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from app.config import settings
from app.constants import AlertLevel, AlertStatus
from app.models import AgentLog, Alert, Delivery, Subscription
from app.services.delivery import deliver_telegram
from app.services.notification import send_alert


@pytest.fixture(name="session")
def session_fixture() -> Generator[Session, None, None]:
    """Provide an isolated in-memory database session."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        yield session


def test_telegram_success_and_token_isolation(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that successful Telegram dispatch creates a 'sent' Delivery row and never leaks the bot token."""
    secret_token = "SECRET_BOT_TOKEN_123456789_XYZ"
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", secret_token)

    alert = Alert(
        id=1,
        region_id=1,
        level=AlertLevel.WARNING.value,
        message="Flood warning for Zone A. Relief point: Warehouse A, 3.3 km away.",
        status=AlertStatus.DRAFT.value,
    )
    session.add(alert)
    session.commit()

    sub = Subscription(
        region_id=1,
        name="Citizen Vikram",
        telegram_chat_id="987654321",
    )
    session.add(sub)
    session.commit()

    # Mock successful HTTP post
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200

    def mock_post(*args, **kwargs):
        url = args[1] if len(args) > 1 else args[0]
        assert secret_token in str(url)
        return mock_resp

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    deliveries = deliver_telegram(session, alert, [sub])
    assert len(deliveries) == 1
    deliv = deliveries[0]
    assert deliv.status == "sent"
    assert deliv.recipient == "Citizen Vikram"
    assert deliv.sent_at is not None
    assert deliv.detail is None

    # Verify token never leaked to Delivery or AgentLog
    assert secret_token not in (deliv.detail or "")


def test_telegram_failure_records_safe_detail_without_token(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that failed Telegram dispatch records only HTTP status or exception name, never secrets."""
    secret_token = "SUPER_SECRET_TOKEN_DO_NOT_LEAK"
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", secret_token)

    alert = Alert(
        id=2,
        region_id=1,
        level=AlertLevel.URGENT.value,
        message="URGENT flood warning for Zone A.",
        status=AlertStatus.DRAFT.value,
    )
    session.add(alert)

    sub = Subscription(
        region_id=1,
        name="Citizen Priya",
        telegram_chat_id="11223344",
    )
    session.add(sub)
    session.commit()

    # 1. HTTP 403 Forbidden failure
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 403

    monkeypatch.setattr(httpx.Client, "post", lambda url, *args, **kwargs: mock_resp)

    deliveries = deliver_telegram(session, alert, [sub])
    assert len(deliveries) == 1
    assert deliveries[0].status == "failed"
    assert deliveries[0].detail == "HTTP 403"
    assert secret_token not in deliveries[0].detail

    # 2. Network Exception failure
    def mock_error_post(*args, **kwargs):
        url = args[1] if len(args) > 1 else args[0]
        raise httpx.ConnectTimeout(f"Timeout contacting {url}")

    monkeypatch.setattr(httpx.Client, "post", mock_error_post)

    deliveries2 = deliver_telegram(session, alert, [sub])
    assert len(deliveries2) == 1
    assert deliveries2[0].status == "failed"
    # Detail must be exception class name, not str(exc) which contains the url with token!
    assert deliveries2[0].detail == "ConnectTimeout"
    assert secret_token not in deliveries2[0].detail


def test_send_alert_logs_sanitized_summary(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that send_alert logs delivery summary without exposing bot tokens."""
    secret_token = "CONFIDENTIAL_TOKEN_ABC_999"
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", secret_token)

    alert = Alert(
        id=3,
        region_id=1,
        level=AlertLevel.WARNING.value,
        message="Flood warning for Zone A: 70 mm rain.",
        status=AlertStatus.DRAFT.value,
    )
    session.add(alert)

    sub = Subscription(
        region_id=1,
        name="Citizen Anjali",
        telegram_chat_id="556677",
    )
    session.add(sub)
    session.commit()

    # Mock Telegram to fail with 500
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 500
    monkeypatch.setattr(httpx.Client, "post", lambda url, *args, **kwargs: mock_resp)

    send_alert(session, alert, approved_by="Coordinator Mike")

    # Check all logs in DB
    logs = session.exec(select(AgentLog)).all()
    for log in logs:
        assert secret_token not in log.message
        if log.payload:
            assert secret_token not in str(log.payload)


def test_telegram_text_has_no_duplicated_level_label(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify Telegram message text starts with [DEMO - simulated scenario] followed directly by message with no duplicate level label."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "mock_bot_token_123")

    alert = Alert(
        id=10,
        region_id=1,
        level=AlertLevel.URGENT.value,
        message="URGENT flood warning for Zone A: severe flooding is likely.",
        status=AlertStatus.APPROVED.value,
    )
    session.add(alert)

    sub = Subscription(
        region_id=1,
        name="Citizen Dev",
        telegram_chat_id="12345678",
    )
    session.add(sub)
    session.commit()

    captured_payload: dict = {}

    def mock_post(*args, **kwargs):
        nonlocal captured_payload
        captured_payload = kwargs.get("json", {})
        resp = MagicMock(spec=httpx.Response)
        resp.is_success = True
        resp.status_code = 200
        return resp

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    deliveries = deliver_telegram(session, alert, [sub])
    assert len(deliveries) == 1
    assert deliveries[0].status == "sent"

    sent_text = captured_payload.get("text", "")
    # Must start with DEMO prefix and followed directly by the message
    assert sent_text == "[DEMO - simulated scenario] URGENT flood warning for Zone A: severe flooding is likely."
    # Must NOT contain duplicate level prefix like "Urgent warning: URGENT..."
    assert "Urgent warning:" not in sent_text
    assert "Urgent warning: URGENT" not in sent_text
    # Stored alert message in DB remains unchanged
    assert alert.message == "URGENT flood warning for Zone A: severe flooding is likely."
