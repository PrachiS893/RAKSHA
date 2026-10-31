"""Safe delivery routing service avoiding simulated hazard zones.

GOLDEN RULES:
- Routes avoid simulated hazard zones where the routing service allows it, and EVERY route is
  re-checked with Shapely: if it crosses an active hazard zone, it is flagged (hazard_free false),
  never hidden.
- Raksha cannot guarantee real road safety without verified real-time road data. Every route
  response carries a disclaimer: 'Route avoids simulated hazard zones only. Real road conditions
  are not verified.'
- The routing layer must NEVER crash the demo: provider chain with cache and straight-line fallback.
- Never log or store the ORS key. It goes only in the Authorization header. On failures log only
  status codes or exception class names.
"""

import copy
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Optional
import httpx
from app.config import settings
from app.schemas import format_iso_utc
from app.services.allocation import haversine_km
from app.services.route_geometry import (
    active_hazard_multipolygon,
    crossed_hazards,
    route_cache_key,
)

logger = logging.getLogger(__name__)

ROUTING_DISCLAIMER: str = (
    "Route avoids simulated hazard zones only. Real road conditions are not verified."
)
ORS_ATTRIBUTION: str = (
    "Routing by openrouteservice.org | (c) OpenStreetMap contributors"
)
OSRM_ATTRIBUTION: str = (
    "(c) OpenStreetMap contributors (OSRM demo server)"
)
STRAIGHT_LINE_ATTRIBUTION: str = (
    "Direct coordinate distance estimate"
)


class ProviderBreaker:
    """Per-batch circuit breaker preventing repeated timeouts when a routing provider is offline."""

    def __init__(self) -> None:
        self.open_providers: set[str] = set()

    def is_open(self, provider: str) -> bool:
        """Check whether the provider circuit has been opened due to a previous failure."""
        return provider in self.open_providers

    def record_failure(self, provider: str) -> None:
        """Open the circuit for the failed provider for the remainder of this batch."""
        self.open_providers.add(provider)


def _apply_safety_audit(
    route: dict[str, Any],
    hazards: list[Any],
) -> dict[str, Any]:
    """Re-verify route trajectory against active hazard zones using Shapely and update status flags."""
    coords = route.get("geometry", {}).get("coordinates", [])
    active_hazards = [
        h for h in hazards
        if (getattr(h, "active", False) if hasattr(h, "active") else (isinstance(h, dict) and h.get("active", False)))
    ]
    active_names = [
        getattr(h, "name", "Hazard") if hasattr(h, "name") else h.get("name", "Hazard")
        for h in active_hazards
    ]

    crossed = crossed_hazards(coords, active_hazards)
    is_hazard_free = (len(crossed) == 0)
    avoided = [name for name in active_names if name not in crossed]

    route["hazard_free"] = is_hazard_free
    route["crossed_hazards"] = crossed
    route["avoided_hazards"] = avoided

    if not is_hazard_free and not route.get("warning"):
        route["warning"] = f"No hazard-free route found; this route crosses: {', '.join(crossed)}"

    return route


def get_route(
    origin: tuple[float, float],
    destination: tuple[float, float],
    hazards: list[Any],
    use_hazards: bool = True,
    breaker: Optional[ProviderBreaker] = None,
) -> dict[str, Any]:
    """Calculate a delivery route from origin (lat, lon) to destination (lat, lon).

    Follows a resilient provider chain:
      0. Check ROUTING_ENABLED flag.
      1. Cache lookup by hash key.
      2. OpenRouteService (ORS) with polygon avoidance.
      3. OSRM fallback checking alternative paths against hazard zones.
      4. Stale cache fallback or straight-line estimation.
    """
    cache_dir = Path(settings.ROUTE_CACHE_DIR)
    now_iso = format_iso_utc(datetime.now(timezone.utc))

    # 1. Exact Cache Lookup
    cache_key = route_cache_key(
        profile=settings.ROUTING_PROFILE,
        origin=origin,
        destination=destination,
        hazards=hazards if use_hazards else [],
    )
    cache_file = cache_dir / f"{cache_key}.json"

    if cache_file.exists():
        try:
            cached_data = json.loads(cache_file.read_text(encoding="utf-8"))
            cached_data["provider"] = "cache"
            return _apply_safety_audit(cached_data, hazards)
        except Exception as exc:
            logger.warning("Failed to read route cache file (%s)", exc.__class__.__name__)

    # 2. OpenRouteService (ORS)
    if settings.ROUTING_ENABLED and settings.ORS_API_KEY and settings.ORS_API_KEY.strip():
        if not (breaker and breaker.is_open("ors")):
            ors_url = f"https://api.openrouteservice.org/v2/directions/{settings.ROUTING_PROFILE}/geojson"
            ors_headers = {
                "Authorization": settings.ORS_API_KEY,
                "Content-Type": "application/json",
            }
            ors_body: dict[str, Any] = {
                "coordinates": [
                    [round(origin[1], 5), round(origin[0], 5)],
                    [round(destination[1], 5), round(destination[0], 5)],
                ],
            }

            if use_hazards:
                multi_poly = active_hazard_multipolygon(hazards)
                if multi_poly:
                    ors_body["options"] = {"avoid_polygons": multi_poly}

            try:
                response = httpx.post(
                    ors_url,
                    headers=ors_headers,
                    json=ors_body,
                    timeout=settings.ROUTING_TIMEOUT_SECONDS,
                )
                if response.status_code == 200:
                    data = response.json()
                    features = data.get("features", [])
                    if features:
                        feature = features[0]
                        geom = feature.get("geometry", {})
                        summary = feature.get("properties", {}).get("summary", {})
                        dist_km = round(summary.get("distance", 0.0) / 1000.0, 1)
                        dur_min = round(summary.get("duration", 0.0) / 60.0, 1)

                        route = {
                            "geometry": geom,
                            "distance_km": dist_km,
                            "duration_min": dur_min,
                            "provider": "ors",
                            "hazard_free": True,
                            "avoided_hazards": [],
                            "crossed_hazards": [],
                            "warning": None,
                            "attribution": ORS_ATTRIBUTION,
                            "disclaimer": ROUTING_DISCLAIMER,
                            "computed_at": now_iso,
                        }
                        route = _apply_safety_audit(route, hazards)

                        # Write verified route to cache
                        try:
                            cache_dir.mkdir(parents=True, exist_ok=True)
                            cache_file.write_text(json.dumps(route, indent=2), encoding="utf-8")
                        except Exception as exc:
                            logger.warning("Failed to write route cache (%s)", exc.__class__.__name__)

                        return route
                else:
                    logger.warning("ORS routing returned HTTP %d", response.status_code)
                    if response.status_code >= 500 and breaker:
                        breaker.record_failure("ors")
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.warning("ORS call failed (%s)", exc.__class__.__name__)
                if breaker:
                    breaker.record_failure("ors")
            except Exception as exc:
                logger.warning("ORS call encountered unexpected error (%s)", exc.__class__.__name__)

    # 3. OSRM Fallback
    if settings.ROUTING_ENABLED and not (breaker and breaker.is_open("osrm")):
        osrm_url = (
            f"{settings.OSRM_BASE_URL.rstrip('/')}/route/v1/driving/"
            f"{origin[1]:.5f},{origin[0]:.5f};{destination[1]:.5f},{destination[0]:.5f}"
            f"?alternatives=true&geometries=geojson&overview=full"
        )
        try:
            response = httpx.get(osrm_url, timeout=settings.ROUTING_TIMEOUT_SECONDS)
            if response.status_code == 200:
                data = response.json()
                routes = data.get("routes", [])
                if routes:
                    # Sort alternatives shortest first
                    routes.sort(key=lambda r: r.get("distance", float("inf")))
                    chosen_route: Optional[dict[str, Any]] = None
                    chosen_crossed: list[str] = []

                    # Pick the first hazard-free alternative
                    for r in routes:
                        coords = r.get("geometry", {}).get("coordinates", [])
                        crossed = crossed_hazards(coords, hazards)
                        if not crossed:
                            chosen_route = r
                            chosen_crossed = []
                            break

                    # If all alternatives cross a hazard, choose the shortest
                    if not chosen_route:
                        chosen_route = routes[0]
                        coords = chosen_route.get("geometry", {}).get("coordinates", [])
                        chosen_crossed = crossed_hazards(coords, hazards)

                    dist_km = round(chosen_route.get("distance", 0.0) / 1000.0, 1)
                    dur_min = round(chosen_route.get("duration", 0.0) / 60.0, 1)
                    geom = chosen_route.get("geometry", {})

                    warning: Optional[str] = None
                    if chosen_crossed:
                        warning = f"No hazard-free route found; this route crosses: {', '.join(chosen_crossed)}"

                    route = {
                        "geometry": geom,
                        "distance_km": dist_km,
                        "duration_min": dur_min,
                        "provider": "osrm",
                        "hazard_free": (len(chosen_crossed) == 0),
                        "avoided_hazards": [],
                        "crossed_hazards": chosen_crossed,
                        "warning": warning,
                        "attribution": OSRM_ATTRIBUTION,
                        "disclaimer": ROUTING_DISCLAIMER,
                        "computed_at": now_iso,
                    }
                    route = _apply_safety_audit(route, hazards)

                    try:
                        cache_dir.mkdir(parents=True, exist_ok=True)
                        cache_file.write_text(json.dumps(route, indent=2), encoding="utf-8")
                    except Exception as exc:
                        logger.warning("Failed to write OSRM route cache (%s)", exc.__class__.__name__)

                    return route
            else:
                logger.warning("OSRM routing returned HTTP %d", response.status_code)
                if response.status_code >= 500 and breaker:
                    breaker.record_failure("osrm")
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning("OSRM call failed (%s)", exc.__class__.__name__)
            if breaker:
                breaker.record_failure("osrm")
        except Exception as exc:
            logger.warning("OSRM call encountered unexpected error (%s)", exc.__class__.__name__)

    # 4a. Check for any cached route for same endpoints (even if hazard set differed)
    if cache_dir.exists():
        for f in cache_dir.glob("*.json"):
            try:
                cached_data = json.loads(f.read_text(encoding="utf-8"))
                coords = cached_data.get("geometry", {}).get("coordinates", [])
                if len(coords) >= 2:
                    start = coords[0]
                    end = coords[-1]
                    if (
                        abs(start[1] - origin[0]) < 0.0001
                        and abs(start[0] - origin[1]) < 0.0001
                        and abs(end[1] - destination[0]) < 0.0001
                        and abs(end[0] - destination[1]) < 0.0001
                    ):
                        route = copy.deepcopy(cached_data)
                        route["provider"] = "cache"
                        route["warning"] = "Cached route used; active hazard conditions may differ from when computed"
                        return _apply_safety_audit(route, hazards)
            except Exception:
                continue

    # 4b. Straight-Line Fallback
    dist_km = haversine_km(origin[0], origin[1], destination[0], destination[1])
    dur_min = round((dist_km / 25.0) * 60.0, 1) if dist_km > 0 else 0.0
    line_coords = [
        [round(origin[1], 5), round(origin[0], 5)],
        [round(destination[1], 5), round(destination[0], 5)],
    ]

    straight_route = {
        "geometry": {
            "type": "LineString",
            "coordinates": line_coords,
        },
        "distance_km": dist_km,
        "duration_min": dur_min,
        "provider": "straight_line",
        "hazard_free": True,
        "avoided_hazards": [],
        "crossed_hazards": [],
        "warning": "No routing service available; straight-line estimate, not a road route",
        "attribution": STRAIGHT_LINE_ATTRIBUTION,
        "disclaimer": ROUTING_DISCLAIMER,
        "computed_at": now_iso,
    }
    return _apply_safety_audit(straight_route, hazards)
