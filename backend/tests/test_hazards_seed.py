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


def test_zone_polygons_valid_closed_and_non_overlapping() -> None:
    """Verify that every zone polygon is valid, closed, and pairwise non-overlapping."""
    from app.demo_data import DEMO_REGIONS

    zone_polys: dict[str, Polygon] = {}
    for r in DEMO_REGIONS:
        coords = r["polygon"]["coordinates"]
        assert len(coords) >= 1
        ring = coords[0]
        # Closed ring
        assert len(ring) >= 4
        assert ring[0] == ring[-1], f"Polygon for {r['name']} is not closed"

        poly = Polygon(ring)
        assert poly.is_valid, f"Polygon for {r['name']} is invalid"
        assert poly.area > 0
        zone_polys[r["name"]] = poly

    # Pairwise intersection area is zero, or below 1e-9 square degrees
    zone_names = list(zone_polys.keys())
    for i in range(len(zone_names)):
        for j in range(i + 1, len(zone_names)):
            n1, n2 = zone_names[i], zone_names[j]
            inter_area = zone_polys[n1].intersection(zone_polys[n2]).area
            assert inter_area <= 1e-9, f"Zones {n1} and {n2} overlap with area {inter_area}"


def test_sample_requests_inside_target_zones() -> None:
    """Verify that every sample request lies inside its target zone."""
    from app.demo_data import DEMO_REGIONS, SAMPLE_REQUESTS

    zone_polys = {
        r["name"]: Polygon(r["polygon"]["coordinates"][0])
        for r in DEMO_REGIONS
    }

    target_map = {
        "Rina": "Zone B - Beltola",
        "Amit": "Zone A - Bharalumukh",
        "Neighbour of Mrs. Das": "Zone A - Bharalumukh",
        "Pooja": "Zone B - Beltola",
    }

    for req in SAMPLE_REQUESTS:
        target_zone = target_map[req["name"]]
        pt = Point(req["lon"], req["lat"])
        poly = zone_polys[target_zone]
        assert poly.contains(pt), f"Request {req['name']} is not inside {target_zone}"
        assert poly.exterior.distance(pt) >= 0.002, f"Request {req['name']} is too close to boundary"

