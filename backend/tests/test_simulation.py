"""Tests for B6 flood simulation engine and endpoints."""

from collections.abc import Generator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from app.constants import AlertStatus, RequestStatus, RiskLevel
from app.db import get_session
from app.main import app
import httpx
from app.models import (
    AgentLog,
    Alert,
    Assignment,
    Delivery,
    HazardZone,
    Inventory,
    Region,
    Request,
    Subscription,
)
from app.seed import seed_database
from app.services import alert_drafting
from app.agents import risk_agent


@pytest.fixture(autouse=True)
def mock_osrm_for_simulation(monkeypatch: pytest.MonkeyPatch):
    """Mock OSRM route provider for simulation tests to prevent network access."""
    def mock_get(url: str, **kwargs):
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 3200.0,
                        "duration": 420.0,
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [91.750, 26.210],
                                [91.760, 26.190],
                                [91.765, 26.182],
                            ],
                        },
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx, "get", mock_get)




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
    assert stats["hazards_active"] == 2

    events_3 = data["events"]
    assert any("drinking_water" in e and "shortage" in e.lower() for e in events_3)
    assert any("food_packet" in e and "shortage" in e.lower() for e in events_3)
    assert any("rescue_boat" in e and "shortage" in e.lower() for e in events_3)
    assert any("medical_kit" in e and "TIGHT" in e for e in events_3)
    assert any("2 hazard zones now active (simulated)" in e for e in events_3)

    hazards_res = client.get("/hazards").json()
    assert len(hazards_res) == 2
    assert all(h["active"] is True for h in hazards_res)

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
    r3 = client.post("/simulation/next")  # 3
    assert r3.status_code == 200
    # In stage 3, requests are created unscored (waiting for stage 4 triage)
    reqs_stage_3 = db.exec(select(Request)).all()
    assert len(reqs_stage_3) == 4
    for req in reqs_stage_3:
        assert req.status == "received"
        assert req.priority_score is None

    r4 = client.post("/simulation/next")  # 4
    assert r4.status_code == 200
    assert r4.json()["stage"] == 4
    assert r4.json()["can_advance"] is True
    events_4 = r4.json()["events"]
    assert any("Triage Agent ranked 4 requests" in e for e in events_4)
    assert any("Relief Agent proposed 4 assignments" in e for e in events_4)
    assert r4.json()["stats"]["assignments_pending"] == 4
    assert r4.json()["stats"]["stock_remaining_pct"] == 100.0

    # In stage 4, proposed assignments exist, unapproved, stock unchanged
    db.expire_all()
    assignments_4 = db.exec(select(Assignment)).all()
    assert len(assignments_4) == 4
    assert all(not a.approved for a in assignments_4)

    reqs_stage_4 = db.exec(select(Request)).all()
    assert len(reqs_stage_4) == 4
    for req in reqs_stage_4:
        assert req.status == "prioritized"
        assert req.priority_score is not None

    # Test coordinator approval of relief plan
    appr_res = client.post("/plan/approve")
    assert appr_res.status_code == 200
    assert appr_res.json()["approved"] == 4

    # Verify stock_remaining_pct is below 100 and all four requests are assigned
    status_res = client.get("/simulation").json()
    assert status_res["stats"]["stock_remaining_pct"] < 100.0
    assert status_res["stats"]["assignments_pending"] == 0

    db.expire_all()
    for req in db.exec(select(Request)).all():
        assert req.status == RequestStatus.ASSIGNED.value

    r5 = client.post("/simulation/next")  # 5
    assert r5.status_code == 200
    assert r5.json()["stage"] == 5
    assert r5.json()["can_advance"] is False
    events_5 = r5.json()["events"]
    assert any("Routes computed for 4 assignments" in e for e in events_5)
    assert any("routes avoid all hazard zones" in e for e in events_5)

    # Every assignment has a valid route
    db.expire_all()
    assignments_5 = db.exec(select(Assignment)).all()
    assert len(assignments_5) == 4
    for a in assignments_5:
        assert a.route is not None
        assert "geometry" in a.route
        assert "disclaimer" in a.route

    # Check Orchestrator and Relief logs
    logs_orch = db.exec(select(AgentLog).where(AgentLog.agent == "Orchestrator")).all()
    orch_messages = [log.message for log in logs_orch]
    assert any("Routes ready for 4 assignments" in m for m in orch_messages)

    logs_relief = db.exec(select(AgentLog).where(AgentLog.agent == "Relief")).all()
    relief_messages = [log.message for log in logs_relief]
    assert any("Plan ready: 4 assignments" in m for m in relief_messages)
    assert any("Plan approved: 4 assignments" in m for m in relief_messages)
    assert any("Route for R" in m for m in relief_messages)

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

    # Hazard zones deactivated
    hazards_after = db.exec(select(HazardZone)).all()
    assert len(hazards_after) == 2
    assert all(h.active is False for h in hazards_after)
    assert data["stats"]["hazards_active"] == 0


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
