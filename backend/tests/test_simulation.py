"""Tests for B6 flood simulation engine and endpoints."""

from collections.abc import Generator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from app.constants import AlertStatus, RequestStatus, RiskLevel
from app.db import get_session
from app.main import app
from app.models import (
    AgentLog,
    Alert,
    Assignment,
    Delivery,
    Inventory,
    Region,
    Request,
    Subscription,
)
from app.seed import seed_database
from app.services import alert_drafting
from app.agents import risk_agent


@pytest.fixture(name="client_and_session")
def client_and_session_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, Session], None, None]:
    """Provide TestClient and direct Session on an isolated in-memory SQLite database."""
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

    # Prevent external LLM or weather calls during simulation tests
    monkeypatch.setattr(alert_drafting, "generate_json", lambda prompt, schema, system=None: None)
    monkeypatch.setattr(risk_agent, "generate_json", lambda prompt, schema, system=None: None)

    with TestClient(app) as test_client:
        with Session(test_engine) as db_session:
            yield test_client, db_session

    app.dependency_overrides.clear()


def test_simulation_initial_state(client_and_session: tuple[TestClient, Session]) -> None:
    client, _ = client_and_session
    res = client.get("/simulation")
    assert res.status_code == 200
    data = res.json()

    assert data["stage"] == 1
    assert data["total_stages"] == 5
    assert data["name"] == "Normal conditions"
    assert data["can_advance"] is True
    assert data["label"] == "Illustrative simulation, not a live emergency feed."
    assert data["events"] == []

    stats = data["stats"]
    assert stats["open_requests"] == 0
    assert stats["pending_alerts"] == 0
    assert stats["sent_alerts"] == 0
    assert stats["stock_remaining_pct"] == 100.0

    assert stats["highest_risk"]["risk_level"] == RiskLevel.LOW.value
    assert stats["highest_risk"]["region_id"] == 1

    for reg in stats["regions"]:
        assert reg["risk_level"] == RiskLevel.LOW.value
        assert reg["rainfall_mm"] == 0.0
        assert reg["is_flooded"] is False


def test_simulation_stage_2_advance(client_and_session: tuple[TestClient, Session]) -> None:
    client, db = client_and_session
    res = client.post("/simulation/next")
    assert res.status_code == 200
    data = res.json()

    assert data["stage"] == 2
    assert data["name"] == "Heavy rainfall forecast"
    assert data["can_advance"] is True
    assert len(data["events"]) > 0

    stats = data["stats"]
    assert stats["highest_risk"]["risk_level"] == RiskLevel.SEVERE.value
    assert stats["highest_risk"]["region_id"] == 1

    regions_by_id = {r["id"]: r for r in stats["regions"]}
    assert regions_by_id[1]["risk_level"] == RiskLevel.SEVERE.value
    assert regions_by_id[1]["rainfall_mm"] == 90.0
    assert regions_by_id[2]["risk_level"] == RiskLevel.HIGH.value
    assert regions_by_id[2]["rainfall_mm"] == 70.0
    assert regions_by_id[3]["risk_level"] == RiskLevel.MODERATE.value
    assert regions_by_id[3]["rainfall_mm"] == 40.0

    # Exactly 3 alerts: C Advisory auto-sent, A Urgent and B Warning as drafts
    assert stats["sent_alerts"] == 1
    assert stats["pending_alerts"] == 2
    assert stats["open_requests"] == 0

    citizen_feed = client.get("/alerts").json()
    assert len(citizen_feed) == 1
    assert citizen_feed[0]["region_id"] == 3
    assert citizen_feed[0]["level"] == "ADVISORY"
    assert citizen_feed[0]["status"] == "sent"

    pending_feed = client.get("/alerts/pending").json()
    assert len(pending_feed) == 2
    pending_levels = {a["region_id"]: a["level"] for a in pending_feed}
    assert pending_levels[1] == "URGENT"
    assert pending_levels[2] == "WARNING"


def test_simulation_stage_3_advance(client_and_session: tuple[TestClient, Session]) -> None:
    client, db = client_and_session
    # Advance to Stage 2, then Stage 3
    client.post("/simulation/next")
    res = client.post("/simulation/next")
    assert res.status_code == 200
    data = res.json()

    assert data["stage"] == 3
    assert data["name"] == "Flood begins"

    stats = data["stats"]
    regions_by_id = {r["id"]: r for r in stats["regions"]}
    # Zone A and B flooded, C not flooded
    assert regions_by_id[1]["is_flooded"] is True
    assert regions_by_id[2]["is_flooded"] is True
    assert regions_by_id[3]["is_flooded"] is False

    # 4 requests created
    assert stats["open_requests"] == 4
    # No duplicate alerts
    assert stats["pending_alerts"] == 2
    assert stats["sent_alerts"] == 1

    requests = db.exec(select(Request)).all()
    assert len(requests) == 4
    reg_counts: dict[int, int] = {}
    for req in requests:
        assert req.region_id in (1, 2)
        assert req.status == RequestStatus.RECEIVED.value
        reg_counts[req.region_id] = reg_counts.get(req.region_id, 0) + 1
    assert reg_counts[1] == 2  # Zone A
    assert reg_counts[2] == 2  # Zone B

    # Coordinates check
    req_map = {r.name: r for r in requests if r.name}
    assert req_map["Rina"].region_id == 2
    assert req_map["Amit"].region_id == 1
    assert req_map["Neighbour of Mrs. Das"].region_id == 1
    assert req_map["Pooja"].region_id == 2


def test_simulation_stages_4_and_5_and_terminal_409(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, db = client_and_session
    # Advance through stages 2, 3, 4, 5
    client.post("/simulation/next")  # 2
    client.post("/simulation/next")  # 3

    r4 = client.post("/simulation/next")  # 4
    assert r4.status_code == 200
    assert r4.json()["stage"] == 4
    assert r4.json()["can_advance"] is True

    r5 = client.post("/simulation/next")  # 5
    assert r5.status_code == 200
    assert r5.json()["stage"] == 5
    assert r5.json()["can_advance"] is False

    # Check Orchestrator logs
    logs = db.exec(select(AgentLog).where(AgentLog.agent == "Orchestrator")).all()
    messages = [log.message for log in logs]
    assert any("Triage and allocation will run here" in m for m in messages)
    assert any("Route calculation and final approval plan will run here" in m for m in messages)

    # Advance at Stage 5 returns 409
    r_terminal = client.post("/simulation/next")
    assert r_terminal.status_code == 409
    assert "already at stage 5" in r_terminal.json()["detail"].lower()


def test_simulation_reset_flow(client_and_session: tuple[TestClient, Session]) -> None:
    client, db = client_and_session
    # Advance to Stage 3 so there are alerts, requests, and flooded regions
    client.post("/simulation/next")
    client.post("/simulation/next")

    # Verify state before reset
    assert len(db.exec(select(Request)).all()) == 4
    assert len(db.exec(select(Alert)).all()) == 3

    # Reset
    res = client.post("/simulation/reset")
    assert res.status_code == 200
    data = res.json()

    assert data["stage"] == 1
    assert data["name"] == "Normal conditions"
    assert data["events"] == ["Simulation reset to stage 1: Normal conditions"]

    # Verify tables cleared and state restored
    assert len(db.exec(select(Request)).all()) == 0
    assert len(db.exec(select(Alert)).all()) == 0
    assert len(db.exec(select(Delivery)).all()) == 0
    assert len(db.exec(select(Assignment)).all()) == 0

    # Subscriptions untouched
    assert len(db.exec(select(Subscription)).all()) == 4

    # Inventory restored
    for item in db.exec(select(Inventory)).all():
        assert item.quantity == item.initial_quantity

    # Regions reset
    for r in db.exec(select(Region)).all():
        assert r.risk_level == RiskLevel.LOW.value
        assert r.rainfall_mm == 0.0
        assert r.is_flooded is False


def test_simulation_full_cycle_twice(client_and_session: tuple[TestClient, Session]) -> None:
    client, _ = client_and_session

    for cycle in range(2):
        reset_res = client.post("/simulation/reset")
        assert reset_res.status_code == 200
        assert reset_res.json()["stage"] == 1

        for expected_stage in range(2, 6):
            adv_res = client.post("/simulation/next")
            assert adv_res.status_code == 200
            assert adv_res.json()["stage"] == expected_stage

        # Terminal check at stage 5
        assert client.post("/simulation/next").status_code == 409
