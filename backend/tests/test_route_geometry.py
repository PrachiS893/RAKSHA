"""Tests for route geometry helpers, spatial intersection checks, and cache key generation."""

from app.demo_data import HAZARD_ZONES
from app.services.route_geometry import (
    active_hazard_multipolygon,
    crossed_hazards,
    route_cache_key,
)


def _get_test_hazards() -> list[dict]:
    # Return copies of demo hazards
    return [
        {
            "id": 1,
            "name": HAZARD_ZONES[0]["name"],
            "polygon": HAZARD_ZONES[0]["polygon"],
            "active": True,
        },
        {
            "id": 2,
            "name": HAZARD_ZONES[1]["name"],
            "polygon": HAZARD_ZONES[1]["polygon"],
            "active": True,
        },
    ]


def test_crossed_hazards_detection_and_corner_touching() -> None:
    hazards = _get_test_hazards()

    # Hazard 1: lon [91.738, 91.744], lat [26.193, 26.198]
    # 1. Crossing line straight through the center
    line_crossing = [
        [91.730, 26.195],
        [91.750, 26.195],
    ]
    crossed = crossed_hazards(line_crossing, hazards)
    assert crossed == ["Flooded underpass - north approach"]

    # 2. Line that only touches a corner at (91.738, 26.193)
    line_corner_touch = [
        [91.730, 26.193],
        [91.738, 26.193],
    ]
    assert crossed_hazards(line_corner_touch, hazards) == []

    # 3. Line far away
    line_far = [
        [91.800, 26.150],
        [91.810, 26.160],
    ]
    assert crossed_hazards(line_far, hazards) == []


def test_inactive_hazards_are_ignored() -> None:
    # Set all hazards inactive
    hazards = _get_test_hazards()
    for h in hazards:
        h["active"] = False

    line_crossing = [
        [91.730, 26.195],
        [91.750, 26.195],
    ]
    # crossed_hazards ignores inactive hazards
    assert crossed_hazards(line_crossing, hazards) == []

    # active_hazard_multipolygon returns None when none are active
    assert active_hazard_multipolygon(hazards) is None


def test_active_hazard_multipolygon_structure() -> None:
    hazards = _get_test_hazards()
    # One active, one inactive
    hazards[0]["active"] = True
    hazards[1]["active"] = False

    multi = active_hazard_multipolygon(hazards)
    assert multi is not None
    assert multi["type"] == "MultiPolygon"
    assert len(multi["coordinates"]) == 1
    assert multi["coordinates"][0] == hazards[0]["polygon"]["coordinates"]


def test_route_cache_key_stability_and_dynamics() -> None:
    origin = (26.21, 91.74)
    dest = (26.182, 91.765)

    hazards = _get_test_hazards()
    # Initially both active
    key1 = route_cache_key("driving-car", origin, dest, hazards)
    key2 = route_cache_key("driving-car", origin, dest, hazards)
    # Stable hash
    assert key1 == key2

    # Coordinates rounded to 5 decimals give same key
    origin_slight_drift = (26.2100001, 91.7400002)
    key_drift = route_cache_key("driving-car", origin_slight_drift, dest, hazards)
    assert key1 == key_drift

    # Different profile changes key
    key_profile = route_cache_key("driving-hgv", origin, dest, hazards)
    assert key1 != key_profile

    # Deactivating one hazard changes the key
    hazards[0]["active"] = False
    key_deactivated = route_cache_key("driving-car", origin, dest, hazards)
    assert key1 != key_deactivated

    # Modifying an inactive hazard does NOT change the key
    hazards[0]["name"] = "Different Name"
    key_inactive_mod = route_cache_key("driving-car", origin, dest, hazards)
    assert key_deactivated == key_inactive_mod
