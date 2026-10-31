"""Tests for routing provider chain, fallback strategies, and circuit breaking."""

import json
from pathlib import Path
from typing import Any
import httpx
import pytest
from app.config import settings
from app.demo_data import HAZARD_ZONES
from app.services.routing import ProviderBreaker, get_route


@pytest.fixture
def active_hazards() -> list[dict[str, Any]]:
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


def test_ors_success_and_key_protection(
    monkeypatch: pytest.MonkeyPatch,
    active_hazards: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    fake_key = "secret_ors_key_12345"
    monkeypatch.setattr(settings, "ORS_API_KEY", fake_key)
    monkeypatch.setattr(settings, "ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTE_CACHE_DIR", str(tmp_path))

    captured_requests: list[dict[str, Any]] = []

    def mock_post(url: str, **kwargs):
        captured_requests.append({"url": url, **kwargs})
        # Return a safe route avoiding hazards (e.g. coordinates outside hazard boxes)
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [91.750, 26.210],
                            [91.760, 26.190],
                            [91.765, 26.182],
                        ],
                    },
                    "properties": {
                        "summary": {
                            "distance": 3500.0,
                            "duration": 480.0,
                        }
                    },
                }
            ],
        }
        return httpx.Response(200, json=geojson)

    monkeypatch.setattr(httpx, "post", mock_post)

    origin = (26.21, 91.74)
    dest = (26.182, 91.765)
    route = get_route(origin, dest, active_hazards)

    # Verify provider and parsed measurements
    assert route["provider"] == "ors"
    assert route["distance_km"] == 3.5
    assert route["duration_min"] == 8.0
    assert route["hazard_free"] is True
    assert len(route["avoided_hazards"]) == 2
    assert route["crossed_hazards"] == []

    # Verify request headers and body
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req["headers"]["Authorization"] == fake_key
    assert "options" in req["json"]
    assert "avoid_polygons" in req["json"]["options"]
    assert req["json"]["options"]["avoid_polygons"]["type"] == "MultiPolygon"
    assert len(req["json"]["options"]["avoid_polygons"]["coordinates"]) == 2

    # Verify key does not appear anywhere in returned data
    serialized_route = json.dumps(route)
    assert fake_key not in serialized_route


def test_ors_geometry_crossing_hazard_is_flagged(
    monkeypatch: pytest.MonkeyPatch,
    active_hazards: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ORS_API_KEY", "fake_key")
    monkeypatch.setattr(settings, "ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTE_CACHE_DIR", str(tmp_path))

    # ORS returns a geometry that penetrates hazard 1
    def mock_post(url: str, **kwargs):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [91.740, 26.172050],
                            [91.750, 26.172050],
                        ],
                    },
                    "properties": {
                        "summary": {"distance": 2000.0, "duration": 300.0}
                    },
                }
            ],
        }
        return httpx.Response(200, json=geojson)

    monkeypatch.setattr(httpx, "post", mock_post)

    route = get_route((26.172050, 91.740), (26.172050, 91.750), active_hazards)
    assert route["provider"] == "ors"
    assert route["hazard_free"] is False
    assert "Flooded underpass - north approach" in route["crossed_hazards"]
    assert "No hazard-free route found" in route["warning"]


def test_ors_failure_falls_back_to_osrm_choosing_hazard_free_alt(
    monkeypatch: pytest.MonkeyPatch,
    active_hazards: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ORS_API_KEY", "fake_key")
    monkeypatch.setattr(settings, "ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTE_CACHE_DIR", str(tmp_path))

    # ORS fails with HTTP 500
    def mock_post(url: str, **kwargs):
        return httpx.Response(500, json={"error": "internal error"})

    # OSRM returns two alternatives:
    # Alt 1: shorter (3000 m) but crosses hazard 1
    # Alt 2: slightly longer (3800 m) but completely hazard-free
    def mock_get(url: str, **kwargs):
        osrm_resp = {
            "code": "Ok",
            "routes": [
                {
                    "distance": 3000.0,
                    "duration": 400.0,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [91.740, 26.172050],
                            [91.750, 26.172050],
                        ],
                    },
                },
                {
                    "distance": 3800.0,
                    "duration": 500.0,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [91.750, 26.210],
                            [91.760, 26.190],
                            [91.765, 26.182],
                        ],
                    },
                },
            ],
        }
        return httpx.Response(200, json=osrm_resp)

    monkeypatch.setattr(httpx, "post", mock_post)
    monkeypatch.setattr(httpx, "get", mock_get)

    route = get_route((26.21, 91.74), (26.182, 91.765), active_hazards)
    assert route["provider"] == "osrm"
    assert route["distance_km"] == 3.8
    assert route["duration_min"] == 8.3
    assert route["hazard_free"] is True
    assert route["crossed_hazards"] == []
    assert route["warning"] is None


def test_osrm_all_alternatives_cross_hazards_returns_shortest_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    active_hazards: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ORS_API_KEY", "")
    monkeypatch.setattr(settings, "ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTE_CACHE_DIR", str(tmp_path))

    # All OSRM routes cross hazard 1
    def mock_get(url: str, **kwargs):
        osrm_resp = {
            "code": "Ok",
            "routes": [
                {
                    "distance": 2500.0,
                    "duration": 300.0,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [91.740, 26.172050],
                            [91.750, 26.172050],
                        ],
                    },
                },
                {
                    "distance": 4500.0,
                    "duration": 600.0,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [91.742, 26.171000],
                            [91.748, 26.173000],
                        ],
                    },
                },
            ],
        }
        return httpx.Response(200, json=osrm_resp)

    monkeypatch.setattr(httpx, "get", mock_get)

    route = get_route((26.21, 91.74), (26.182, 91.765), active_hazards)
    assert route["provider"] == "osrm"
    assert route["distance_km"] == 2.5
    assert route["hazard_free"] is False
    assert "Flooded underpass - north approach" in route["crossed_hazards"]
    assert "No hazard-free route found" in route["warning"]


def test_both_providers_fail_uses_stale_cache_or_straight_line(
    monkeypatch: pytest.MonkeyPatch,
    active_hazards: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ORS_API_KEY", "fake_key")
    monkeypatch.setattr(settings, "ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTE_CACHE_DIR", str(tmp_path))

    def mock_post(url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    def mock_get(url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx, "post", mock_post)
    monkeypatch.setattr(httpx, "get", mock_get)

    origin = (26.21, 91.74)
    dest = (26.182, 91.765)

    # 1. No cache exists -> straight line route
    route_straight = get_route(origin, dest, active_hazards)
    assert route_straight["provider"] == "straight_line"
    assert route_straight["distance_km"] > 0
    assert "straight-line estimate, not a road route" in route_straight["warning"]

    # 2. Put a cached route in cache directory with slightly different active hazards
    cache_file = tmp_path / "custom_stale_route.json"
    dummy_cached = {
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [91.74, 26.21],
                [91.75, 26.20],
                [91.765, 26.182],
            ],
        },
        "distance_km": 4.1,
        "duration_min": 9.0,
        "provider": "ors",
        "hazard_free": True,
        "avoided_hazards": [],
        "crossed_hazards": [],
        "warning": None,
        "attribution": "Mock Cached",
        "disclaimer": "...",
        "computed_at": "2026-10-31T10:00:00Z",
    }
    cache_file.write_text(json.dumps(dummy_cached), encoding="utf-8")

    # Second call uses the cached route with provider "cache" and a stale warning
    route_cache = get_route(origin, dest, active_hazards)
    assert route_cache["provider"] == "cache"
    assert "Cached route used" in route_cache["warning"]


def test_circuit_breaker_prevents_subsequent_calls_in_batch(
    monkeypatch: pytest.MonkeyPatch,
    active_hazards: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ORS_API_KEY", "fake_key")
    monkeypatch.setattr(settings, "ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTE_CACHE_DIR", str(tmp_path))

    call_counts = {"ors": 0, "osrm": 0}

    def mock_post(url, **kwargs):
        call_counts["ors"] += 1
        raise httpx.TimeoutException("ORS timeout")

    def mock_get(url, **kwargs):
        call_counts["osrm"] += 1
        raise httpx.TimeoutException("OSRM timeout")

    monkeypatch.setattr(httpx, "post", mock_post)
    monkeypatch.setattr(httpx, "get", mock_get)

    breaker = ProviderBreaker()

    # Call 1: both providers fail and trip breaker
    r1 = get_route((26.21, 91.74), (26.182, 91.765), active_hazards, breaker=breaker)
    assert r1["provider"] == "straight_line"
    assert call_counts["ors"] == 1
    assert call_counts["osrm"] == 1

    # Call 2: breaker is open for both providers -> 0 additional HTTP calls!
    r2 = get_route((26.13, 91.80), (26.142, 91.789), active_hazards, breaker=breaker)
    assert r2["provider"] == "straight_line"
    assert call_counts["ors"] == 1
    assert call_counts["osrm"] == 1


def test_routing_disabled_skips_network_calls(
    monkeypatch: pytest.MonkeyPatch,
    active_hazards: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ROUTING_ENABLED", False)
    monkeypatch.setattr(settings, "ROUTE_CACHE_DIR", str(tmp_path))

    call_counts = {"calls": 0}

    def mock_any(*args, **kwargs):
        call_counts["calls"] += 1
        raise RuntimeError("Should not be called")

    monkeypatch.setattr(httpx, "post", mock_any)
    monkeypatch.setattr(httpx, "get", mock_any)

    route = get_route((26.21, 91.74), (26.182, 91.765), active_hazards)
    assert route["provider"] == "straight_line"
    assert call_counts["calls"] == 0


def test_no_ors_key_skips_ors_and_uses_osrm(
    monkeypatch: pytest.MonkeyPatch,
    active_hazards: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ORS_API_KEY", "")
    monkeypatch.setattr(settings, "ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTE_CACHE_DIR", str(tmp_path))

    call_counts = {"ors": 0, "osrm": 0}

    def mock_post(url, **kwargs):
        call_counts["ors"] += 1
        return httpx.Response(200, json={})

    def mock_get(url, **kwargs):
        call_counts["osrm"] += 1
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 3000.0,
                        "duration": 400.0,
                        "geometry": {"type": "LineString", "coordinates": [[91.75, 26.21], [91.76, 26.18]]},
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx, "post", mock_post)
    monkeypatch.setattr(httpx, "get", mock_get)

    route = get_route((26.21, 91.74), (26.182, 91.765), active_hazards)
    assert route["provider"] == "osrm"
    assert call_counts["ors"] == 0
    assert call_counts["osrm"] == 1
