"""Tests for Orchestrator workflow logic, handoffs, and hazard states."""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.constants import RiskLevel
from app.models import AgentLog, HazardZone, Region, Request
from app.services import orchestrator
from app.services.simulator import reset


@pytest.fixture(autouse=True)
def mock_routing_provider(monkeypatch: pytest.MonkeyPatch):
    """Mock OSRM responses for all routing calls in orchestrator tests."""
    def mock_get(url: str, **kwargs):
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 2500.0,
                        "duration": 360.0,
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


def test_orchestrator_assess_risk_and_handoff_log(client_and_session: tuple[TestClient, Session]):
    """assess_risk evaluates regions, logs handoff to Notification Service, and creates alerts."""
    _, session = client_and_session

    regions = session.exec(select(Region)).all()
    assert len(regions) >= 3

    # Force 2 regions into high/severe risk overrides
    overrides = {regions[0].id: 95.0, regions[1].id: 90.0, regions[2].id: 10.0}
    res = orchestrator.assess_risk(session, overrides=overrides)

    assert len(res.reports) == len(regions)
    assert len(res.events) >= len(regions)

    # Check Orchestrator hand-off log
    orchestrator_logs = session.exec(
        select(AgentLog)
        .where(AgentLog.agent == "Orchestrator")
        .order_by(AgentLog.id.desc())
    ).all()
    handoff_logs = [
        l.message for l in orchestrator_logs
        if "Passing" in l.message and "Notification Service" in l.message
    ]
    assert len(handoff_logs) >= 1
    # Regions 0 and 1 have high rainfall, so at least 2 are high risk
    assert "Passing 2 high-risk regions to Notification Service" in handoff_logs[0] or "Passing 3 high-risk regions" in handoff_logs[0]


def test_orchestrator_predict_supply_shortages(client_and_session: tuple[TestClient, Session]):
    """predict_supply_shortages generates resource shortage forecast and event logs."""
    _, session = client_and_session

    # Mark region as SEVERE risk and flooded so demand is projected
    region = session.exec(select(Region)).first()
    assert region is not None
    region.risk_level = RiskLevel.SEVERE.value
    region.is_flooded = True
    session.add(region)
    session.commit()

    res = orchestrator.predict_supply_shortages(session)
    assert "resources" in res.shortages
    assert isinstance(res.events, list)
    # Check that events list contains predicted shortages
    assert any("Shortage predicted" in ev for ev in res.events)



def test_orchestrator_submit_request(client_and_session: tuple[TestClient, Session]):
    """submit_request wraps create_request and properly persists a triaged request."""
    _, session = client_and_session

    req = orchestrator.submit_request(
        session,
        text="Elderly grandmother trapped on second floor with rising floodwater, needs medical kit",
        lat=26.175,
        lon=91.755,
        name="Sunita Das",
        triage=True,
    )

    assert req.id is not None
    assert req.name == "Sunita Das"
    assert req.priority_score is not None
    assert req.priority_score > 50  # Trapped elderly = high priority score


def test_orchestrator_activate_hazards(client_and_session: tuple[TestClient, Session]):
    """activate_hazards activates and deactivates hazard zones and logs state change."""
    _, session = client_and_session

    res_active = orchestrator.activate_hazards(session, active=True)
    assert all(h.active for h in res_active.hazards)
    assert any("hazard zones now active" in ev for ev in res_active.events)

    # Check Orchestrator log
    log = session.exec(
        select(AgentLog)
        .where(AgentLog.agent == "Orchestrator")
        .order_by(AgentLog.id.desc())
    ).first()
    assert log is not None
    assert "hazard zones now active" in log.message

    res_inactive = orchestrator.activate_hazards(session, active=False)
    assert all(not h.active for h in res_inactive.hazards)
    assert any("hazard zones deactivated" in ev for ev in res_inactive.events)


def test_orchestrator_plan_relief_flow(client_and_session: tuple[TestClient, Session]):
    """plan_relief coordinates triage, relief allocation, and delivery routes when hazards active."""
    _, session = client_and_session

    # Ingest 2 requests
    orchestrator.submit_request(
        session,
        text="Child with fever trapped in floodwater, need medicine kit",
        lat=26.175,
        lon=91.755,
        name="Request 1",
        triage=False,
    )
    orchestrator.submit_request(
        session,
        text="Need drinking water for 10 people",
        lat=26.170,
        lon=91.760,
        name="Request 2",
        triage=False,
    )

    # Activate hazards first so routing is triggered
    orchestrator.activate_hazards(session, active=True)

    # Plan relief with routes
    result = orchestrator.plan_relief(session, with_routes=True)
    assert len(result.triage_results) == 2
    assert len(result.plan.assignments) > 0
    assert result.routes_computed is not None
    assert len(result.routes_computed) > 0

    # Verify Orchestrator handoff logs
    orchestrator_logs = session.exec(
        select(AgentLog)
        .where(AgentLog.agent == "Orchestrator")
        .order_by(AgentLog.id.desc())
    ).all()
    messages = [l.message for l in orchestrator_logs]
    assert any("Passing 2 prioritized requests to Relief Agent" in m for m in messages)
    assert any("Routes ready for" in m for m in messages)


def test_orchestrator_full_simulation_progression(client_and_session: tuple[TestClient, Session]):
    """Resetting and advancing 4 stages gives identical events and state through orchestrator."""
    client, _ = client_and_session

    res_reset = client.post("/simulation/reset")
    assert res_reset.status_code == 200
    assert res_reset.json()["stage"] == 1

    # Stage 1 -> 2
    res2 = client.post("/simulation/next")
    assert res2.status_code == 200
    assert res2.json()["stage"] == 2
    events2 = res2.json()["events"]
    assert any("risk is now" in e for e in events2)

    # Stage 2 -> 3
    res3 = client.post("/simulation/next")
    assert res3.status_code == 200
    assert res3.json()["stage"] == 3
    events3 = res3.json()["events"]
    assert any("hazard zones now active" in e for e in events3)
    assert any("Shortage predicted" in e for e in events3)

    # Stage 3 -> 4
    res4 = client.post("/simulation/next")
    assert res4.status_code == 200
    assert res4.json()["stage"] == 4
    events4 = res4.json()["events"]
    assert any("Triage Agent ranked" in e for e in events4)
    assert any("Relief Agent proposed" in e for e in events4)

    # Stage 4 -> 5
    res5 = client.post("/simulation/next")
    assert res5.status_code == 200
    assert res5.json()["stage"] == 5
    assert res5.json()["can_advance"] is False
    events5 = res5.json()["events"]
    assert any("Routes computed" in e for e in events5)
    assert any("routes avoid all hazard zones" in e for e in events5)

