"""Tests for routing endpoints (/relief/routes, /assignments/{id}/route, dev route test)."""

from typing import Any
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlmodel import Session, select
from app.config import settings
from app.constants import RiskLevel
from app.demo_data import SAMPLE_REQUESTS
from app.models import Assignment, Region
from app.services.request_intake import create_request


def _setup_relief_plan(client: TestClient, session: Session) -> None:
    # Set Zone A SEVERE, Zone B HIGH
    regions = session.exec(select(Region)).all()
    for r in regions:
        if "Zone A" in r.name:
            r.risk_level = RiskLevel.SEVERE.value
        elif "Zone B" in r.name:
            r.risk_level = RiskLevel.HIGH.value
        session.add(r)
    session.commit()

    for req_data in SAMPLE_REQUESTS:
        create_request(
            session=session,
            text=req_data["text"],
            lat=req_data["lat"],
            lon=req_data["lon"],
            name=req_data.get("name"),
            triage=False,
        )

    # Generate initial plan (4 proposed assignments with route=None)
    client.post("/relief/plan")


def test_compute_routes_batch_and_force(
    client_and_session: tuple[TestClient, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session = client_and_session
    _setup_relief_plan(client, session)

    # Mock OSRM to return a valid route
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
    monkeypatch.setattr(settings, "ORS_API_KEY", "")

    # 1. First batch route computation
    res1 = client.post("/relief/routes")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["computed"] == 4
    for a in data1["assignments"]:
        assert a["route"] is not None
        assert a["route"]["provider"] == "osrm"
        assert a["route"]["distance_km"] == 3.2
        assert "disclaimer" in a["route"]

    # 2. Second batch without force -> computes 0
    res2 = client.post("/relief/routes")
    assert res2.status_code == 200
    assert res2.json()["computed"] == 0

    # 3. Third batch with force=true -> computes 4 again
    res3 = client.post("/relief/routes?force=true")
    assert res3.status_code == 200
    assert res3.json()["computed"] == 4

    # 4. Verify GET /relief/plan includes the route objects
    res_plan = client.get("/relief/plan")
    assert res_plan.status_code == 200
    for a in res_plan.json()["assignments"]:
        assert a["route"] is not None
        assert a["route"]["provider"] in ("osrm", "cache")


def test_single_assignment_route_and_approval(
    client_and_session: tuple[TestClient, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session = client_and_session
    _setup_relief_plan(client, session)

    def mock_get(url: str, **kwargs):
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 2800.0,
                        "duration": 360.0,
                        "geometry": {"type": "LineString", "coordinates": [[91.74, 26.21], [91.75, 26.18]]},
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx, "get", mock_get)
    monkeypatch.setattr(settings, "ORS_API_KEY", "")

    assignments = session.exec(select(Assignment)).all()
    target_a = assignments[0]
    assert target_a.route is None

    # Compute single route
    res = client.post(f"/assignments/{target_a.id}/route")
    assert res.status_code == 200
    data = res.json()
    assert data["route"] is not None
    assert data["route"]["distance_km"] == 2.8

    # Approving an assignment that has a route still works perfectly
    res_appr = client.post(f"/assignments/{target_a.id}/approve")
    assert res_appr.status_code == 200
    assert res_appr.json()["approved"] is True
    assert res_appr.json()["route"] is not None

    # Unknown assignment returns 404
    assert client.post("/assignments/9999/route").status_code == 404


def test_dev_route_test_and_hazards_activate(
    client_and_session: tuple[TestClient, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session = client_and_session

    def mock_get(url: str, **kwargs):
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 1500.0,
                        "duration": 200.0,
                        "geometry": {"type": "LineString", "coordinates": [[91.74, 26.21], [91.735, 26.185]]},
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx, "get", mock_get)

    # 1. POST /dev/route-test
    res_test = client.post("/dev/route-test?warehouse_id=1&lat=26.185&lon=91.735")
    assert res_test.status_code == 200
    route = res_test.json()
    assert "geometry" in route
    assert "distance_km" in route
    assert "disclaimer" in route

    # Invalid warehouse returns 404
    assert client.post("/dev/route-test?warehouse_id=999&lat=26.185&lon=91.735").status_code == 404

    # 2. POST /dev/hazards/activate
    res_act = client.post("/dev/hazards/activate?active=true")
    assert res_act.status_code == 200
    assert res_act.json()["updated"] == 2
    assert res_act.json()["active"] is True

    hazards_res = client.get("/hazards").json()
    assert all(h["active"] is True for h in hazards_res)

    # Deactivate
    client.post("/dev/hazards/activate?active=false")
    hazards_res2 = client.get("/hazards").json()
    assert all(h["active"] is False for h in hazards_res2)
