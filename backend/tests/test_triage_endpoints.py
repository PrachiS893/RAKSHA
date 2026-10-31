"""Tests for triage API endpoints and submission integration."""

from collections.abc import Generator
import pytest
from starlette.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from app.config import settings
from app.db import get_session
from app.main import app
from app.models import Request
from app.seed import seed_database


@pytest.fixture(name="client")
def client_fixture() -> Generator[TestClient, None, None]:
    """Create a TestClient with an isolated seeded in-memory database."""
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
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(name="client_and_session")
def client_and_session_fixture() -> Generator[tuple[TestClient, Session], None, None]:
    """Create a TestClient and Session sharing the same in-memory database."""
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


def test_create_request_with_triage_on_submit(client: TestClient) -> None:
    """Verify POST /requests with TRIAGE_ON_SUBMIT=True immediately scores and prioritizes."""
    payload = {
        "text": "My father is diabetic and has run out of insulin. He is very weak.",
        "name": "Amit",
        "lat": 26.175,
        "lon": 91.745,
    }
    response = client.post("/requests", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert data["status"] == "prioritized"
    assert data["ref"].startswith("R")
    assert data["urgency"] == "CRITICAL"
    assert data["priority_score"] is not None
    assert data["priority_score"] >= 75
    assert data["resource_needed"] == "medical_kit"
    assert data["need_summary"] is not None
    assert data["score_breakdown"] is not None
    assert len(data["score_breakdown"]) > 0


def test_create_request_with_triage_disabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify POST /requests with TRIAGE_ON_SUBMIT=False arrives as received and unscored."""
    monkeypatch.setattr(settings, "TRIAGE_ON_SUBMIT", False)

    payload = {
        "text": "Need drinking water and food for family.",
        "name": "Rina",
        "lat": 26.135,
        "lon": 91.735,
    }
    response = client.post("/requests", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert data["status"] == "received"
    assert data["priority_score"] is None
    assert data["urgency"] is None


def test_triage_run_and_force_flag(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify POST /triage/run processes un-triaged requests and force=True re-triages."""
    monkeypatch.setattr(settings, "TRIAGE_ON_SUBMIT", False)

    # Create un-triaged request
    client.post(
        "/requests",
        json={"text": "Water needed urgently.", "lat": 26.18, "lon": 91.74},
    )

    # First run: triages 1 request
    res1 = client.post("/triage/run")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["triaged"] >= 1
    assert len(data1["ranked"]) >= 1

    # Second run without force: 0 newly triaged
    res2 = client.post("/triage/run?force=false")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["triaged"] == 0
    assert len(data2["ranked"]) >= 1

    # Third run with force=true: re-triages all requests
    res3 = client.post("/triage/run?force=true")
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["triaged"] >= 1


def test_single_request_triage_endpoint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify POST /requests/{id}/triage re-runs triage and returns 404 for missing request."""
    monkeypatch.setattr(settings, "TRIAGE_ON_SUBMIT", False)

    create_res = client.post(
        "/requests",
        json={"text": "Food needed for 4 people.", "lat": 26.18, "lon": 91.74},
    )
    req_id = create_res.json()["id"]

    triage_res = client.post(f"/requests/{req_id}/triage")
    assert triage_res.status_code == 200
    data = triage_res.json()
    assert data["request_id"] == req_id
    assert data["ref"] == f"R{req_id}"
    assert data["priority_score"] is not None

    # Test 404
    missing_res = client.post("/requests/999999/triage")
    assert missing_res.status_code == 404


def test_dev_triage_preview_does_not_persist(
    client_and_session: tuple[TestClient, Session],
) -> None:
    """Verify POST /dev/triage-preview returns decision support without saving to database."""
    client, db = client_and_session
    initial_count = len(db.exec(select(Request)).all())

    preview_payload = {
        "text": "My father is diabetic and has run out of insulin. He is very weak.",
        "region_id": 1,
    }
    response = client.post("/dev/triage-preview", json=preview_payload)
    assert response.status_code == 200
    data = response.json()

    assert "result" in data
    assert "features" in data
    assert data["result"]["urgency"] == "CRITICAL"
    assert data["result"]["priority_score"] >= 75
    assert data["features"]["medical_dependency"] is True

    # Check database was not modified
    db.expire_all()
    current_count = len(db.exec(select(Request)).all())
    assert current_count == initial_count
