"""Route planning coordinator applying safe delivery routes to relief assignments.

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

from typing import Optional
from sqlmodel import Session, select
from app.models import Assignment, HazardZone, Request, Warehouse
from app.services.agent_log import log_agent
from app.services.routing import ProviderBreaker, get_route


def compute_routes(
    session: Session,
    force: bool = False,
) -> list[Assignment]:
    """Calculate and assign safe delivery routes for relief assignments avoiding active hazard zones.

    Operates across all proposed and approved assignments in the active plan.
    Routes are persisted directly on Assignment.route.
    """
    assignments = session.exec(select(Assignment).order_by(Assignment.id)).all()
    hazards = session.exec(select(HazardZone)).all()
    warehouses = {w.id: w for w in session.exec(select(Warehouse)).all() if w.id is not None}
    requests = {r.id: r for r in session.exec(select(Request)).all() if r.id is not None}

    breaker = ProviderBreaker()
    computed_assignments: list[Assignment] = []

    for a in assignments:
        if a.route is not None and not force:
            continue

        wh = warehouses.get(a.warehouse_id)
        req = requests.get(a.request_id)
        if not wh or not req:
            continue

        origin = (wh.lat, wh.lon)
        dest = (req.lat, req.lon)

        route = get_route(
            origin=origin,
            destination=dest,
            hazards=hazards,
            use_hazards=True,
            breaker=breaker,
        )
        a.route = route
        session.add(a)
        computed_assignments.append(a)

        # Log according to outcome
        req_ref = f"R{req.id}"
        wh_name = wh.name
        dist = route.get("distance_km", 0.0)
        dur = route.get("duration_min", 0.0)
        provider = route.get("provider", "unknown")
        hazard_free = route.get("hazard_free", True)
        avoided = route.get("avoided_hazards", [])
        crossed = route.get("crossed_hazards", [])

        if not hazard_free:
            log_msg = (
                f"WARNING: Route for {req_ref} crosses {len(crossed)} hazard zone(s): "
                f"{', '.join(crossed)} ({provider})"
            )
        elif provider in ("straight_line", "cache"):
            log_msg = (
                f"Route for {req_ref}: {wh_name} to request, {dist:.1f} km, {dur:.1f} min "
                f"({provider} fallback)"
            )
        else:
            hz_label = "hazard zone" if len(avoided) == 1 else "hazard zones"
            log_msg = (
                f"Route for {req_ref}: {wh_name} to request, {dist:.1f} km, {dur:.1f} min, "
                f"avoids {len(avoided)} {hz_label} ({provider})"
            )

        log_agent(session, agent="Relief", message=log_msg)

    session.commit()
    for a in computed_assignments:
        session.refresh(a)

    return computed_assignments
