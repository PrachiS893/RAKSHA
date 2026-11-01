"""Tests for /agents status endpoint reporting health, activity, and log counts."""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete
from app.models import AgentLog
from app.services.agent_log import log_agent


@pytest.fixture(autouse=True)
def mock_routing_provider(monkeypatch: pytest.MonkeyPatch):
    """Mock routing provider for simulation advances."""
    def mock_get(url: str, **kwargs):
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 2000.0,
                        "duration": 300.0,
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[91.750, 26.210], [91.760, 26.190]],
                        },
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx, "get", mock_get)


def test_agents_status_fresh_database(client_and_session: tuple[TestClient, Session]):
    """On a fresh database with no logs, /agents returns 5 fixed entities with null activity and 0 logs."""
    client, session = client_and_session

    # Clear any logs created during seed
    session.exec(delete(AgentLog))
    session.commit()

    res = client.get("/agents")
    assert res.status_code == 200
    data = res.json()

    assert len(data) == 5
    names = [a["name"] for a in data]
    assert names == ["Risk", "Triage", "Relief", "Orchestrator", "Notification"]

    # Verify kinds
    kind_by_name = {a["name"]: a["kind"] for a in data}
    assert kind_by_name["Risk"] == "agent"
    assert kind_by_name["Triage"] == "agent"
    assert kind_by_name["Relief"] == "agent"
    assert kind_by_name["Orchestrator"] == "agent"
    assert kind_by_name["Notification"] == "service"

    # All null activity and 0 logs
    for item in data:
        assert item["last_active"] is None
        assert item["last_message"] is None
        assert item["log_count"] == 0


def test_agents_status_after_activity(client_and_session: tuple[TestClient, Session]):
    """After logs are logged or simulation runs, /agents reflects last_active and log_count."""
    client, session = client_and_session

    # Clear logs first
    session.exec(delete(AgentLog))
    session.commit()

    # Log events for specific agents
    log_agent(session, agent="Risk", message="Rainfall evaluated")
    log_agent(session, agent="Risk", message="Risk updated to HIGH")
    log_agent(session, agent="Notification", message="Telegram alert dispatched")

    res = client.get("/agents")
    assert res.status_code == 200
    data = res.json()

    risk_info = next(a for a in data if a["name"] == "Risk")
    assert risk_info["log_count"] == 2
    assert risk_info["last_message"] == "Risk updated to HIGH"
    assert risk_info["last_active"] is not None

    notif_info = next(a for a in data if a["name"] == "Notification")
    assert notif_info["log_count"] == 1
    assert notif_info["last_message"] == "Telegram alert dispatched"
    assert notif_info["last_active"] is not None

    triage_info = next(a for a in data if a["name"] == "Triage")
    assert triage_info["log_count"] == 0
    assert triage_info["last_active"] is None
    assert triage_info["last_message"] is None


def test_agents_status_after_simulation_run(client_and_session: tuple[TestClient, Session]):
    """Running simulation stages produces activity across multiple agents reflected in /agents."""
    client, _ = client_and_session

    client.post("/simulation/reset")
    client.post("/simulation/next")  # Stage 2: Risk Agent + Notification Service
    client.post("/simulation/next")  # Stage 3: Flooding + Relief shortages

    res = client.get("/agents")
    assert res.status_code == 200
    data = res.json()

    for item in data:
        if item["name"] in ("Risk", "Orchestrator", "Notification", "Relief"):
            assert item["log_count"] > 0
            assert item["last_active"] is not None
            assert item["last_message"] is not None
