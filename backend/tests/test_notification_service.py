"""Integration tests for the Notification Service, approval lifecycle, and alert endpoints."""

from collections.abc import Generator
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from app.constants import AlertLevel, AlertStatus, RiskLevel
from app.db import get_session
from app.main import app
from app.models import Alert, Delivery, Region
from app.schemas import RiskReport
from app.seed import seed_database
from app.services import alert_drafting
from app.services.notification import create_alert_from_report




def test_moderate_report_auto_sent_and_appears_in_citizen_feed(
    client_and_session: tuple[TestClient, Session],
) -> None:
    """Verify MODERATE report triggers auto-advisory (approved_by='system (auto-advisory)'),

    creates deliveries, and appears immediately in GET /alerts.
    """
    client, session = client_and_session
    now = datetime.now(timezone.utc)
    region_b = session.exec(select(Region).where(Region.name == "Zone B - Central Lowlands")).first()
    assert region_b is not None

    report = RiskReport(
        region_id=region_b.id,
        region=region_b.name,
        risk_level=RiskLevel.MODERATE,
        rainfall_mm=35.0,
        rainfall_source="open-meteo",
        reason="Heavy rain forecast.",
        action="Issue advisory.",
        generated_at=now,
        simulated=True,
    )

    alert = create_alert_from_report(session, region_b, report)
    assert alert is not None
    assert alert.status == AlertStatus.SENT.value
    assert alert.approved_by == "system (auto-advisory)"
    assert alert.approved_at is not None

    # Check deliveries: in_app sent, sms_sim simulated for 1 subscriber (Zone B has Demo Citizen 3), telegram skipped
    deliveries = session.exec(select(Delivery).where(Delivery.alert_id == alert.id)).all()
    channels = {d.channel: d.status for d in deliveries}
    assert channels["in_app"] == "sent"
    assert channels["sms_sim"] == "simulated"
    assert channels["telegram"] == "skipped"

    # Appears in citizen feed
    feed_resp = client.get("/alerts")
    assert feed_resp.status_code == 200
    alerts_data = feed_resp.json()
    assert any(a["id"] == alert.id for a in alerts_data)

    # Not in pending
    pending_resp = client.get("/alerts/pending")
    assert not any(a["id"] == alert.id for a in pending_resp.json())


def test_high_report_creates_pending_draft(
    client_and_session: tuple[TestClient, Session],
) -> None:
    """Verify HIGH report creates a draft requiring approval: not in GET /alerts, present in GET /alerts/pending."""
    client, session = client_and_session
    now = datetime.now(timezone.utc)
    region_a = session.exec(select(Region).where(Region.name == "Zone A - Riverside")).first()
    assert region_a is not None

    report = RiskReport(
        region_id=region_a.id,
        region=region_a.name,
        risk_level=RiskLevel.HIGH,
        rainfall_mm=75.0,
        rainfall_source="open-meteo",
        reason="Intense rainfall expected.",
        action="Prepare warning.",
        generated_at=now,
        simulated=True,
    )

    alert = create_alert_from_report(session, region_a, report)
    assert alert is not None
    assert alert.status == AlertStatus.DRAFT.value
    assert alert.approved_by is None

    # Absent from citizen feed
    feed_resp = client.get("/alerts")
    assert not any(a["id"] == alert.id for a in feed_resp.json())

    # Present in pending coordinator feed
    pending_resp = client.get("/alerts/pending")
    assert any(a["id"] == alert.id for a in pending_resp.json())


def test_alert_deduplication_and_superseding(
    client_and_session: tuple[TestClient, Session],
) -> None:
    """Verify deduplication ignores equal/lower reports and higher severity supersedes lower draft."""
    client, session = client_and_session
    now = datetime.now(timezone.utc)
    region_a = session.exec(select(Region).where(Region.name == "Zone A - Riverside")).first()
    assert region_a is not None

    high_report = RiskReport(
        region_id=region_a.id,
        region=region_a.name,
        risk_level=RiskLevel.HIGH,
        rainfall_mm=75.0,
        rainfall_source="simulated",
        reason="Heavy rain.",
        action="Draft warning.",
        generated_at=now,
        simulated=True,
    )

    # 1. Create first HIGH alert (draft)
    draft_high = create_alert_from_report(session, region_a, high_report)
    assert draft_high is not None
    assert draft_high.level == AlertLevel.WARNING.value

    # 2. Duplicate HIGH report returns None
    dup = create_alert_from_report(session, region_a, high_report)
    assert dup is None

    # 3. SEVERE report supersedes the earlier HIGH draft
    severe_report = RiskReport(
        region_id=region_a.id,
        region=region_a.name,
        risk_level=RiskLevel.SEVERE,
        rainfall_mm=125.0,
        rainfall_source="simulated",
        reason="Extreme rain.",
        action="Urgent warning.",
        generated_at=now,
        simulated=True,
    )
    draft_severe = create_alert_from_report(session, region_a, severe_report)
    assert draft_severe is not None
    assert draft_severe.level == AlertLevel.URGENT.value

    session.refresh(draft_high)
    assert draft_high.status == AlertStatus.SUPERSEDED.value


def test_approve_alert_workflow_and_errors(
    client_and_session: tuple[TestClient, Session],
) -> None:
    """Verify approval transitions status to 'sent', dispatches deliveries, and handles 409/422."""
    client, session = client_and_session
    now = datetime.now(timezone.utc)
    region_a = session.exec(select(Region).where(Region.name == "Zone A - Riverside")).first()
    assert region_a is not None

    report = RiskReport(
        region_id=region_a.id,
        region=region_a.name,
        risk_level=RiskLevel.HIGH,
        rainfall_mm=80.0,
        rainfall_source="simulated",
        reason="Heavy rain.",
        action="Draft warning.",
        generated_at=now,
        simulated=True,
    )
    draft = create_alert_from_report(session, region_a, report)
    assert draft is not None

    # 1. Bad edited message -> 422 (missing region name)
    bad_resp = client.post(
        f"/alerts/{draft.id}/approve",
        json={"message": "Please evacuate immediately from flooded areas."},
    )
    assert bad_resp.status_code == 422

    # 2. Successful approval with valid edited message
    valid_edit = (
        "Flood warning for Zone A: 80 mm rainfall expected. "
        "Move belongings to higher ground. Nearest depot: Warehouse A - North Depot, 3.3 km."
    )
    approve_resp = client.post(
        f"/alerts/{draft.id}/approve",
        json={"approved_by": "Coordinator Sarah", "message": valid_edit},
    )
    assert approve_resp.status_code == 200
    data = approve_resp.json()
    assert data["status"] == "sent"
    assert data["approved_by"] == "Coordinator Sarah"
    assert data["approved_at"] is not None
    assert data["message"] == valid_edit
    assert len(data["deliveries"]) > 0

    # 3. Approving twice -> 409 Conflict
    second_approve = client.post(f"/alerts/{draft.id}/approve")
    assert second_approve.status_code == 409
