"""Tests for the Risk Agent logic, LLM explanation handling, and database updates."""

from collections.abc import Generator
from datetime import datetime, timezone
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from app.agents import risk_agent
from app.agents.risk_agent import run_risk_agent, run_risk_agent_all
from app.constants import RiskLevel
from app.models import AgentLog, Region
from app.schemas import RiskExplanation, RiskReport
from app.seed import seed_database
from app.services.weather import RainfallForecast


@pytest.fixture(name="session")
def session_fixture() -> Generator[Session, None, None]:
    """Provide an isolated, seeded in-memory database session."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        seed_database(session)
        yield session


def test_risk_agent_with_llm_text(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that when generate_json returns text, RiskReport uses LLM explanation."""
    now = datetime.now(timezone.utc)

    # Mock weather to 50 mm
    monkeypatch.setattr(
        risk_agent,
        "get_rainfall_forecast",
        lambda lat, lon, override_mm=None: RainfallForecast(
            lat=lat,
            lon=lon,
            rainfall_mm_24h=50.0,
            source="simulated",
            fetched_at=now,
        ),
    )

    # Mock LLM response
    mock_explanation = RiskExplanation(
        reason="Heavy rainfall expected across Bharalumukh zone.",
        action="Prepare sandbags and pre-position relief teams.",
    )
    monkeypatch.setattr(
        risk_agent, "generate_json", lambda prompt, schema, system=None: mock_explanation
    )

    region_a = session.exec(select(Region).where(Region.name == "Zone A - Bharalumukh")).first()
    assert region_a is not None

    report = run_risk_agent(session, region_a, persist=False)
    # 50 mm * (0.5 + 0.9) = 70.0 mm -> HIGH
    assert report.risk_level == RiskLevel.HIGH
    assert report.reason == "Heavy rainfall expected across Bharalumukh zone."
    assert report.action == "Prepare sandbags and pre-position relief teams."
    assert report.simulated is True
    assert report.rainfall_source == "simulated"


def test_risk_agent_with_template_fallback(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that when generate_json returns None, RiskReport falls back to template text."""
    now = datetime.now(timezone.utc)

    # Mock weather to 10 mm
    monkeypatch.setattr(
        risk_agent,
        "get_rainfall_forecast",
        lambda lat, lon, override_mm=None: RainfallForecast(
            lat=lat,
            lon=lon,
            rainfall_mm_24h=10.0,
            source="open-meteo",
            fetched_at=now,
        ),
    )

    # Mock LLM to return None
    monkeypatch.setattr(risk_agent, "generate_json", lambda prompt, schema, system=None: None)

    region_a = session.exec(select(Region).where(Region.name == "Zone A - Bharalumukh")).first()
    assert region_a is not None

    report = run_risk_agent(session, region_a, persist=False)
    # 10 mm * (0.5 + 0.9) = 14.0 mm -> LOW
    assert report.risk_level == RiskLevel.LOW
    assert "Forecast rainfall of 10 mm in the next 24 hours" in report.reason
    assert report.action == "No action needed; keep monitoring."


def test_risk_agent_golden_rule_overrides_llm_hallucination(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GOLDEN RULE: The risk level in RiskReport ALWAYS comes from calculate_risk,

    even if the LLM hallucinated text claims a different severity level.
    """
    now = datetime.now(timezone.utc)

    # Weather forecast calculates to LOW (10 mm * 1.4 = 14 mm)
    monkeypatch.setattr(
        risk_agent,
        "get_rainfall_forecast",
        lambda lat, lon, override_mm=None: RainfallForecast(
            lat=lat,
            lon=lon,
            rainfall_mm_24h=10.0,
            source="open-meteo",
            fetched_at=now,
        ),
    )

    # Hallucinated LLM response claiming SEVERE
    hallucinated_explanation = RiskExplanation(
        reason="Catastrophic flood crisis detected across zone.",
        action="Immediate evacuation of all residents required.",
    )
    monkeypatch.setattr(
        risk_agent,
        "generate_json",
        lambda prompt, schema, system=None: hallucinated_explanation,
    )

    region_a = session.exec(select(Region).where(Region.name == "Zone A - Bharalumukh")).first()
    assert region_a is not None

    report = run_risk_agent(session, region_a, persist=False)
    # Must remain LOW because calculate_risk produces LOW
    assert report.risk_level == RiskLevel.LOW


def test_risk_agent_writes_agent_logs(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that running the agent writes logs with agent='Risk' to agent_logs table."""
    monkeypatch.setattr(risk_agent, "generate_json", lambda prompt, schema, system=None: None)

    region_a = session.exec(select(Region).where(Region.name == "Zone A - Bharalumukh")).first()
    assert region_a is not None

    run_risk_agent(session, region_a, override_rainfall_mm=30.0, persist=False)

    logs = session.exec(select(AgentLog).where(AgentLog.agent == "Risk")).all()
    assert len(logs) >= 3

    log_messages = [l.message for l in logs]
    assert any("Checking rainfall forecast" in m for m in log_messages)
    assert any("Forecast for Zone A - Bharalumukh" in m for m in log_messages)
    assert any("Risk level" in m for m in log_messages)


def test_risk_agent_persist_flag(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify persist=True updates region row in DB and persist=False leaves it unchanged."""
    monkeypatch.setattr(risk_agent, "generate_json", lambda prompt, schema, system=None: None)

    region_a = session.exec(select(Region).where(Region.name == "Zone A - Bharalumukh")).first()
    assert region_a is not None
    initial_rain = region_a.rainfall_mm
    initial_risk = region_a.risk_level

    # 1. persist=False: region must remain unchanged
    run_risk_agent(session, region_a, override_rainfall_mm=90.0, persist=False)
    session.refresh(region_a)
    assert region_a.rainfall_mm == initial_rain
    assert region_a.risk_level == initial_risk

    # 2. persist=True: region must be updated
    run_risk_agent(session, region_a, override_rainfall_mm=90.0, persist=True)
    session.refresh(region_a)
    # 90 * (0.5 + 0.9) = 126 mm -> SEVERE
    assert region_a.rainfall_mm == 90.0
    assert region_a.risk_level == "SEVERE"


def test_run_risk_agent_all_returns_three_reports(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify run_risk_agent_all assesses all 3 regions."""
    monkeypatch.setattr(risk_agent, "generate_json", lambda prompt, schema, system=None: None)

    reports = run_risk_agent_all(
        session=session,
        override_by_region={1: 90.0, 2: 10.0, 3: 20.0},
        persist=False,
    )
    assert len(reports) == 3
    assert all(isinstance(r, RiskReport) for r in reports)

    zone_names = [r.region for r in reports]
    assert "Zone A - Bharalumukh" in zone_names
    assert "Zone B - Beltola" in zone_names
    assert "Zone C - Noonmati" in zone_names
