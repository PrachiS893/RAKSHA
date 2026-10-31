"""Integration tests for Raksha API endpoints."""

from collections.abc import Generator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from app.db import get_session
from app.main import app
from app.models import Region
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

    # Seed the test in-memory database
    with Session(test_engine) as session:
        seed_database(session)

    def get_test_session() -> Generator[Session, None, None]:
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_get_regions(client: TestClient) -> None:
    """Verify that GET /regions returns 3 regions with valid GeoJSON polygons."""
    response = client.get("/regions")
    assert response.status_code == 200
    regions = response.json()
    assert len(regions) == 3

    zone_names = [r["name"] for r in regions]
    assert "Zone A - Riverside" in zone_names
    assert "Zone B - Central Lowlands" in zone_names
    assert "Zone C - Eastern Uplands" in zone_names

    for r in regions:
        assert "id" in r
        assert r["polygon"]["type"] == "Polygon"
        assert len(r["polygon"]["coordinates"]) >= 1
        # Check closed ring
        ring = r["polygon"]["coordinates"][0]
        assert ring[0] == ring[-1]
        assert "center" in r
        assert "lat" in r["center"]
        assert "lon" in r["center"]
        assert r["is_simulated_flood"] is True


def test_get_warehouses_includes_nested_inventory(client: TestClient) -> None:
    """Verify that GET /warehouses includes nested inventory and units."""
    response = client.get("/warehouses")
    assert response.status_code == 200
    warehouses = response.json()
    assert len(warehouses) == 3

    warehouse_a = next(w for w in warehouses if "North Depot" in w["name"])
    assert warehouse_a["simulated"] is True
    assert len(warehouse_a["inventory"]) == 4

    water_inv = next(i for i in warehouse_a["inventory"] if i["resource"] == "drinking_water")
    assert water_inv["unit"] == "litres"
    assert water_inv["quantity"] == 300
    assert water_inv["initial_quantity"] == 300


def test_create_request_inside_zone(client: TestClient) -> None:
    """Verify that POST /requests inside Zone A detects region_id and returns 201."""
    # Point inside Zone A: lat 26.175, lon 91.745
    payload = {
        "text": "My father is diabetic and has run out of insulin. He is very weak.",
        "name": "Amit",
        "lat": 26.175,
        "lon": 91.745,
    }
    response = client.post("/requests", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert data["status"] == "received"
    assert data["name"] == "Amit"
    assert data["region_name"] == "Zone A - Riverside"
    assert data["region_id"] is not None
    assert data["resource_needed"] is None
    assert data["urgency"] is None
    assert data["priority_score"] is None
    assert "created_at" in data


def test_create_request_outside_zones(client: TestClient) -> None:
    """Verify that POST /requests outside all zones sets region_id to null."""
    # Point far outside: lat 25.0, lon 90.0
    payload = {
        "text": "Out of area distress call.",
        "name": "Caller",
        "lat": 25.0,
        "lon": 90.0,
    }
    response = client.post("/requests", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert data["status"] == "received"
    assert data["region_id"] is None
    assert data["region_name"] is None


def test_create_request_validation_empty_text(client: TestClient) -> None:
    """Verify that POST /requests with empty or whitespace-only text returns 422."""
    payload = {
        "text": "   ",
        "lat": 26.18,
        "lon": 91.74,
    }
    response = client.post("/requests", json=payload)
    assert response.status_code == 422


def test_get_requests_lists_created_request(client: TestClient) -> None:
    """Verify that GET /requests lists newly created requests."""
    payload = {
        "text": "Need drinking water and food for family.",
        "name": "Rina",
        "lat": 26.135,
        "lon": 91.735,
    }
    create_resp = client.post("/requests", json=payload)
    assert create_resp.status_code == 201
    created_id = create_resp.json()["id"]

    list_resp = client.get("/requests")
    assert list_resp.status_code == 200
    requests = list_resp.json()
    assert any(r["id"] == created_id for r in requests)


def test_get_alerts_initially_empty(client: TestClient) -> None:
    """Verify that GET /alerts returns an empty list initially (excluding drafts)."""
    response = client.get("/alerts")
    assert response.status_code == 200
    assert response.json() == []


def test_subscriptions_valid_and_invalid_region(client: TestClient) -> None:
    """Verify POST /subscriptions returns 201 for valid region and 404 for invalid."""
    # Find a valid region ID
    regions_resp = client.get("/regions")
    valid_region_id = regions_resp.json()[0]["id"]

    # Valid subscription
    valid_payload = {
        "region_id": valid_region_id,
        "name": "Test Citizen",
        "telegram_chat_id": "test_chat_123",
    }
    post_resp = client.post("/subscriptions", json=valid_payload)
    assert post_resp.status_code == 201
    data = post_resp.json()
    assert data["region_id"] == valid_region_id
    assert data["name"] == "Test Citizen"
    assert data["telegram_chat_id"] == "test_chat_123"
    assert data["region_name"] == regions_resp.json()[0]["name"]

    # Invalid region subscription
    invalid_payload = {
        "region_id": 999999,
        "name": "Non-existent region citizen",
    }
    err_resp = client.post("/subscriptions", json=invalid_payload)
    assert err_resp.status_code == 404
    assert "not exist" in err_resp.json()["detail"]
