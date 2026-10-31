"""Route geometry and spatial verification helpers using Shapely.

GOLDEN RULES:
- Routes avoid simulated hazard zones where the routing service allows it, and EVERY route is
  re-checked with Shapely: if it crosses an active hazard zone, it is flagged (hazard_free false),
  never hidden.
- Raksha cannot guarantee real road safety without verified real-time road data. Every route
  response carries a disclaimer.
- The routing layer must NEVER crash the demo: provider chain with cache and straight-line fallback.
- Never log or store the ORS key. It goes only in the Authorization header. On failures log only
  status codes or exception class names.
"""

import hashlib
import json
from typing import Any, Optional
from shapely.geometry import LineString, shape


def active_hazard_multipolygon(hazards: list[Any]) -> Optional[dict[str, Any]]:
    """Build a GeoJSON MultiPolygon from all currently active hazard zones, or None if none are active."""
    active_polygons: list[list[list[list[float]]]] = []
    for h in hazards:
        is_active = getattr(h, "active", False) if hasattr(h, "active") else (isinstance(h, dict) and h.get("active", False))
        if not is_active:
            continue
        poly_data = h.polygon if hasattr(h, "polygon") else h.get("polygon")
        if poly_data and "coordinates" in poly_data:
            active_polygons.append(poly_data["coordinates"])

    if not active_polygons:
        return None

    return {
        "type": "MultiPolygon",
        "coordinates": active_polygons,
    }


def crossed_hazards(route_coords: list[list[float]], hazards: list[Any]) -> list[str]:
    """Identify which active hazard zones a route trajectory crosses using Shapely.

    A hazard counts as crossed only if line.intersection(polygon).length > 0.00005 degrees (~5.5 m).
    Touching a corner or edge tangentially (length <= 0.00005) does not count as crossed.
    Inactive hazards are never considered crossed.
    """
    if not route_coords or len(route_coords) < 2:
        return []

    try:
        line = LineString(route_coords)
    except Exception:
        return []

    crossed: list[str] = []
    for h in hazards:
        is_active = getattr(h, "active", False) if hasattr(h, "active") else (isinstance(h, dict) and h.get("active", False))
        if not is_active:
            continue

        poly_data = h.polygon if hasattr(h, "polygon") else h.get("polygon")
        name = getattr(h, "name", "Hazard") if hasattr(h, "name") else h.get("name", "Hazard")
        if not poly_data:
            continue

        try:
            poly = shape(poly_data)
            inter = line.intersection(poly)
            if inter and getattr(inter, "length", 0.0) > 0.00005:
                crossed.append(name)
        except Exception:
            continue

    return crossed


def route_cache_key(
    profile: str,
    origin: tuple[float, float],
    destination: tuple[float, float],
    hazards: list[Any],
) -> str:
    """Compute a deterministic hash key for route caching based on coordinates and active hazards.

    Coordinates are rounded to 5 decimal places (~1.1 m). The key only depends on ACTIVE hazards
    (their sorted IDs, names, and geometries), so activating or deactivating hazards changes the key.
    """
    orig_rounded = [round(origin[0], 5), round(origin[1], 5)]
    dest_rounded = [round(destination[0], 5), round(destination[1], 5)]

    active_hazards_repr: list[dict[str, Any]] = []
    for h in hazards:
        is_active = getattr(h, "active", False) if hasattr(h, "active") else (isinstance(h, dict) and h.get("active", False))
        if not is_active:
            continue

        hid = getattr(h, "id", None) if hasattr(h, "id") else h.get("id")
        hname = getattr(h, "name", "") if hasattr(h, "name") else h.get("name", "")
        hpoly = getattr(h, "polygon", {}) if hasattr(h, "polygon") else h.get("polygon", {})
        active_hazards_repr.append({
            "id": hid,
            "name": hname,
            "polygon": hpoly,
        })

    # Sort deterministically by id (handling None) then name
    active_hazards_repr.sort(key=lambda item: (item["id"] if item["id"] is not None else -1, item["name"]))

    payload = {
        "profile": profile,
        "origin": orig_rounded,
        "destination": dest_rounded,
        "active_hazards": active_hazards_repr,
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
