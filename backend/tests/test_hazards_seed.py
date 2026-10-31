"""Tests for hazard zone seed data, polygon geometry validity, and GET /hazards endpoint."""

from fastapi.testclient import TestClient
from shapely.geometry import Point, Polygon
from sqlmodel import Session, select
from app.demo_data import DEMO_WAREHOUSES, HAZARD_ZONES, SAMPLE_REQUESTS
from app.models import HazardZone


def test_hazards_seed_counts_and_properties(
    client_and_session: tuple[TestClient, Session],
) -> None:
    _, session = client_and_session

    hazards = session.exec(select(HazardZone).order_by(HazardZone.id)).all()
    assert len(hazards) == 2

    for h in hazards:
        assert h.active is False
        assert h.simulated is True
        assert h.name in [hz["name"] for hz in HAZARD_ZONES]
        assert h.polygon["type"] == "Polygon"

        coords = h.polygon["coordinates"]
        assert len(coords) >= 1
        ring = coords[0]
        # Valid closed ring: at least 4 coordinates (3 unique + 1 closing) and first equals last
        assert len(ring) >= 4
        assert ring[0] == ring[-1]

        # Valid Shapely polygon
        poly = Polygon(ring)
        assert poly.is_valid
        assert poly.area > 0


def test_no_warehouse_or_sample_request_inside_hazards() -> None:
    """Ensure simulated obstacle polygons do not trap warehouses or citizens at source/destination."""
    hazard_polys = [
        Polygon(hz["polygon"]["coordinates"][0])
        for hz in HAZARD_ZONES
    ]

    # Test all warehouses
    for w in DEMO_WAREHOUSES:
        # Shapely coordinates are [lon, lat]
        pt = Point(w["lon"], w["lat"])
        for poly in hazard_polys:
            assert not poly.contains(pt), f"Warehouse {w['name']} is inside hazard polygon"
            assert poly.distance(pt) > 0.001

    # Test all sample requests
    for req in SAMPLE_REQUESTS:
        pt = Point(req["lon"], req["lat"])
        for poly in hazard_polys:
            assert not poly.contains(pt), f"Request {req.get('name')} is inside hazard polygon"
            assert poly.distance(pt) > 0.001


def test_get_hazards_endpoint_shape(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, _ = client_and_session

    res = client.get("/hazards")
    assert res.status_code == 200
    data = res.json()

    assert len(data) == 2
    for item in data:
        assert "id" in item
        assert "name" in item
        assert "description" in item
        assert "polygon" in item
        assert "active" in item
        assert "simulated" in item
        assert item["active"] is False
        assert item["simulated"] is True
        assert item["polygon"]["type"] == "Polygon"
