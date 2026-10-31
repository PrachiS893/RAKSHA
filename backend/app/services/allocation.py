"""Relief allocation service for matching warehouse supplies to prioritized requests.

GOLDEN RULES:
- Allocation is a RECOMMENDATION. Stock is only reduced when a coordinator approves.
- Highest priority requests are served first; each request gets the NEAREST warehouse that has enough stock.
- Shortage numbers are demo planning assumptions, not real forecasts. Label them as such everywhere.
"""

import copy
import math
from typing import Any, Optional
from app.constants import Resource

# Quantity rules: water 3 litres/person, food 3 packets/person, medical 1/request, boat 1/request.
# people_count None counts as 1.
QUANTITY_RULES: dict[str, Any] = {
    Resource.DRINKING_WATER.value: lambda p: 3 * (p if p is not None and p >= 1 else 1),
    Resource.FOOD_PACKET.value: lambda p: 3 * (p if p is not None and p >= 1 else 1),
    Resource.MEDICAL_KIT.value: lambda p: 1,
    Resource.RESCUE_BOAT.value: lambda p: 1,
}

RESOURCE_UNITS: dict[str, str] = {
    Resource.DRINKING_WATER.value: "litres",
    Resource.FOOD_PACKET.value: "packets",
    Resource.MEDICAL_KIT.value: "kits",
    Resource.RESCUE_BOAT.value: "boats",
}


def quantity_needed(
    resource: Optional[str | Resource], people_count: Optional[int]
) -> int:
    """Calculate the required supply units for a relief request based on standard dispatch rules."""
    if resource is None:
        return 0

    res_key = resource.value if isinstance(resource, Resource) else str(resource)
    rule = QUANTITY_RULES.get(res_key)
    if rule:
        return rule(people_count)
    return 1


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance between two points in kilometers, rounded to 1 decimal."""
    radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(radius_km * c, 1)


def allocate(
    requests: list[Any],
    warehouses_stock: dict[int, dict[str, int]],
    warehouse_coords: dict[int, tuple[float, float]],
    warehouse_names: Optional[dict[int, str]] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pure deterministic allocation algorithm matching supplies to prioritized distress requests.

    Requests are evaluated in order of priority_score descending (ties: older first, then id).
    A working copy of stock is reduced as assignments are proposed.

    Returns:
        tuple of (assignments: list[dict], unmet: list[dict])
    """
    working_stock: dict[int, dict[str, int]] = copy.deepcopy(warehouses_stock)
    names: dict[int, str] = warehouse_names or {
        wid: f"Warehouse {wid}" for wid in warehouse_coords
    }

    # Sort requests descending by priority_score, then ascending by created_at, then id
    sorted_requests = sorted(
        requests,
        key=lambda r: (
            -(getattr(r, "priority_score", None) or 0),
            getattr(r, "created_at", None) or 0,
            getattr(r, "id", None) or 0,
        ),
    )

    assignments: list[dict[str, Any]] = []
    unmet: list[dict[str, Any]] = []

    for req in sorted_requests:
        req_id = getattr(req, "id", None) or 0
        req_ref = getattr(req, "ref", None) or f"R{req_id}"
        resource = getattr(req, "resource_needed", None)
        if isinstance(resource, Resource):
            resource = resource.value

        priority_score = getattr(req, "priority_score", None) or 0
        urgency = getattr(req, "urgency", None) or "LOW"
        if hasattr(urgency, "value"):
            urgency = urgency.value

        req_lat = getattr(req, "lat", 0.0)
        req_lon = getattr(req, "lon", 0.0)
        people_count = getattr(req, "people_count", None)

        # 1. If request has no resource_needed: unmet
        if not resource:
            unmet.append({
                "request_id": req_id,
                "request_ref": req_ref,
                "resource": None,
                "quantity_needed": 0,
                "reason": "Needs coordinator decision: no clear resource identified",
            })
            continue

        need = quantity_needed(resource, people_count)

        # 2. Find candidate warehouses whose stock >= need
        candidates: list[tuple[float, int, int]] = []
        for wid, coords in warehouse_coords.items():
            stock = working_stock.get(wid, {}).get(resource, 0)
            if stock >= need:
                dist = haversine_km(req_lat, req_lon, coords[0], coords[1])
                # Candidate tuple: (distance_km, -stock for tie-break, wid)
                candidates.append((dist, -stock, wid))

        if candidates:
            candidates.sort()
            best_dist, neg_stock, chosen_wid = candidates[0]
            working_stock[chosen_wid][resource] -= need
            w_name = names.get(chosen_wid, f"Warehouse {chosen_wid}")

            reason = (
                f"Nearest warehouse with enough stock ({best_dist:.1f} km). "
                f"Priority {priority_score}, {urgency}."
            )
            assignments.append({
                "request_id": req_id,
                "request_ref": req_ref,
                "warehouse_id": chosen_wid,
                "warehouse": w_name,
                "resource": resource,
                "unit": RESOURCE_UNITS.get(resource, "units"),
                "quantity": need,
                "distance_km": best_dist,
                "partial": False,
                "unmet_quantity": 0,
                "reason": reason,
                "priority_score": priority_score,
                "urgency": urgency,
            })
            continue

        # 3. If no warehouse has stock >= need, check for partial stock
        max_stock = -1
        best_partial_wid: Optional[int] = None
        best_partial_dist = 0.0

        warehouse_options: list[tuple[int, float, int]] = []
        for wid, coords in warehouse_coords.items():
            stock = working_stock.get(wid, {}).get(resource, 0)
            dist = haversine_km(req_lat, req_lon, coords[0], coords[1])
            # Tuple: (-stock, dist, wid)
            warehouse_options.append((-stock, dist, wid))

        warehouse_options.sort()
        neg_stock, best_dist, chosen_wid = warehouse_options[0]
        avail_stock = -neg_stock

        if avail_stock > 0:
            alloc_qty = avail_stock
            unmet_qty = need - alloc_qty
            working_stock[chosen_wid][resource] = 0
            w_name = names.get(chosen_wid, f"Warehouse {chosen_wid}")

            reason = (
                f"Partial: only {alloc_qty} of {need} available; shortage flagged. "
                f"Distance {best_dist:.1f} km. Priority {priority_score}, {urgency}."
            )
            assignments.append({
                "request_id": req_id,
                "request_ref": req_ref,
                "warehouse_id": chosen_wid,
                "warehouse": w_name,
                "resource": resource,
                "unit": RESOURCE_UNITS.get(resource, "units"),
                "quantity": alloc_qty,
                "distance_km": best_dist,
                "partial": True,
                "unmet_quantity": unmet_qty,
                "reason": reason,
                "priority_score": priority_score,
                "urgency": urgency,
            })
        else:
            # Every warehouse has 0 stock
            unmet.append({
                "request_id": req_id,
                "request_ref": req_ref,
                "resource": resource,
                "quantity_needed": need,
                "reason": "No stock available",
            })

    return assignments, unmet
