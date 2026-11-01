"""Tests for optional background scheduler and periodic risk check."""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.agents import risk_agent
from app.config import settings
from app.models import AgentLog, Request, SimulationState
from app.services import orchestrator
from app.services.scheduler import scheduled_risk_check
from app.services.weather import RainfallForecast


def test_scheduler_disabled_when_interval_zero():
    """Verify that when RISK_CHECK_INTERVAL_MINUTES is 0, scheduler is disabled by default."""
    assert settings.RISK_CHECK_INTERVAL_MINUTES == 0


def test_scheduled_risk_check_skips_when_stage_greater_than_one(client_and_session: tuple[TestClient, Session]):
    """scheduled_risk_check skips risk evaluation and logs when simulation stage > 1."""
    _, session = client_and_session

    sim_state = session.get(SimulationState, 1)
    if sim_state is None:
        sim_state = SimulationState(id=1, stage=2)
    else:
        sim_state.stage = 2
    session.add(sim_state)
    session.commit()

    scheduled_risk_check()

    log = session.exec(
        select(AgentLog)
        .where(AgentLog.agent == "Orchestrator")
        .order_by(AgentLog.id.desc())
    ).first()
    assert log is not None
    assert "Skipped scheduled check: simulation in progress" in log.message


def test_scheduled_risk_check_skips_when_requests_exist(client_and_session: tuple[TestClient, Session]):
    """scheduled_risk_check skips risk evaluation and logs when requests exist."""
    _, session = client_and_session

    # Reset to stage 1 but create an active request
    sim_state = session.get(SimulationState, 1)
    if sim_state is None:
        sim_state = SimulationState(id=1, stage=1)
    else:
        sim_state.stage = 1
    session.add(sim_state)

    orchestrator.submit_request(
        session,
        text="Need drinking water urgently",
        lat=26.175,
        lon=91.755,
        name="Test Request",
        triage=False,
    )
    session.commit()

    scheduled_risk_check()

    log = session.exec(
        select(AgentLog)
        .where(AgentLog.agent == "Orchestrator")
        .order_by(AgentLog.id.desc())
    ).first()
    assert log is not None
    assert "Skipped scheduled check: simulation in progress" in log.message


def test_scheduled_risk_check_runs_when_idle(
    client_and_session: tuple[TestClient, Session],
    monkeypatch: pytest.MonkeyPatch,
):
    """scheduled_risk_check runs orchestrator.assess_risk when stage is 1 and 0 requests."""
    client, session = client_and_session

    # Reset simulation so stage is 1 and 0 requests exist
    client.post("/simulation/reset")

    # Mock weather to avoid network calls
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        risk_agent,
        "get_rainfall_forecast",
        lambda lat, lon, override_mm=None: RainfallForecast(
            lat=lat,
            lon=lon,
            rainfall_mm_24h=20.0,
            source="simulated",
            fetched_at=now,
        ),
    )

    scheduled_risk_check()

    # Verify risk assessment ran
    logs = session.exec(
        select(AgentLog)
        .where(AgentLog.agent == "Orchestrator")
        .order_by(AgentLog.id.desc())
    ).all()
    messages = [l.message for l in logs]
    assert any("Starting scheduled periodic risk check" in m for m in messages)
    assert any("Passing" in m and "Notification Service" in m for m in messages)


def test_scheduled_risk_check_never_raises(
    client_and_session: tuple[TestClient, Session],
    monkeypatch: pytest.MonkeyPatch,
):
    """scheduled_risk_check catches all internal exceptions and never raises."""
    _, session = client_and_session

    def mock_broken_assess_risk(*args, **kwargs):
        raise RuntimeError("Simulated unhandled risk assessment failure")

    monkeypatch.setattr(orchestrator, "assess_risk", mock_broken_assess_risk)

    # Ensure system is idle so it attempts to call assess_risk
    sim_state = session.get(SimulationState, 1)
    if sim_state is None:
        sim_state = SimulationState(id=1, stage=1)
    else:
        sim_state.stage = 1
    session.add(sim_state)
    session.commit()

    # Must execute cleanly without raising RuntimeError
    try:
        scheduled_risk_check()
    except Exception as exc:
        pytest.fail(f"scheduled_risk_check raised an exception: {exc}")
