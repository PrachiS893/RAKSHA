"""Relief routing and approval endpoints for disaster supply operations.

GOLDEN RULES:
- Allocation is a RECOMMENDATION. Stock is only reduced when a coordinator approves.
- Highest priority requests are served first; each request gets the NEAREST warehouse that has enough stock.
- Shortage numbers are demo planning assumptions, not real forecasts. Label them as such everywhere.
"""

from datetime import datetime, timezone
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select
from app.agents.relief_agent import (
    build_assignment_read,
    get_current_relief_plan,
    run_relief_agent,
)
from app.constants import RequestStatus
from app.db import get_session
from app.models import Assignment, HazardZone, Inventory, Request, Warehouse
from app.schemas import (
    AssignmentApproveRequest,
    AssignmentRead,
    PlanApproveResponse,
    ReliefPlan,
    RoutesComputeResponse,
)
from app.services.agent_log import log_agent
from app.services.route_planner import compute_routes
from app.services.routing import get_route

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Relief"])


@router.post(
    "/relief/plan",
    response_model=ReliefPlan,
    summary="Generate relief allocation plan",
)
def generate_relief_plan(
    triage_first: bool = Query(
        default=True,
        description="Whether to execute emergency triage on pending requests before allocation planning.",
    ),
    session: Session = Depends(get_session),
) -> ReliefPlan:
    """Propose deterministic supply allocations for prioritized requests without reducing warehouse inventory."""
    return run_relief_agent(session, triage_first=triage_first)


@router.get(
    "/relief/plan",
    response_model=ReliefPlan,
    summary="Get current relief allocation plan",
)
def read_relief_plan(
    session: Session = Depends(get_session),
) -> ReliefPlan:
    """Retrieve existing proposed and approved assignments and unmet requests without recomputing."""
    return get_current_relief_plan(session)


@router.post(
    "/assignments/{id}/approve",
    response_model=AssignmentRead,
    summary="Approve a relief assignment",
)
def approve_assignment(
    id: int,
    payload: Optional[AssignmentApproveRequest] = None,
    session: Session = Depends(get_session),
) -> AssignmentRead:
    """Approve a proposed assignment, decrementing warehouse inventory and updating request status to assigned."""
    if payload is None:
        payload = AssignmentApproveRequest()
    approved_by = payload.approved_by or "coordinator"

    assignment = session.get(Assignment, id)
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assignment with id {id} not found",
        )
    if assignment.approved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Assignment {id} is already approved",
        )

    # Check warehouse inventory
    inv = session.exec(
        select(Inventory).where(
            Inventory.warehouse_id == assignment.warehouse_id,
            Inventory.resource == assignment.resource,
        )
    ).first()

    avail = inv.quantity if inv else 0
    if not inv or inv.quantity < assignment.quantity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Insufficient stock in warehouse {assignment.warehouse_id} for "
                f"{assignment.resource}: need {assignment.quantity}, available {avail}"
            ),
        )

    # Deduct inventory stock
    inv.quantity -= assignment.quantity
    session.add(inv)

    now = datetime.now(timezone.utc)
    assignment.approved = True
    assignment.approved_by = approved_by
    assignment.approved_at = now
    session.add(assignment)

    req = session.get(Request, assignment.request_id)
    if req:
        req.status = RequestStatus.ASSIGNED.value
        session.add(req)

    session.commit()
    session.refresh(assignment)

    log_agent(
        session,
        agent="Relief",
        message=f"Assignment {assignment.id} approved by {approved_by}",
    )

    return build_assignment_read(session, assignment)


@router.post(
    "/plan/approve",
    response_model=PlanApproveResponse,
    summary="Approve all proposed relief assignments",
)
def approve_entire_plan(
    payload: Optional[AssignmentApproveRequest] = None,
    session: Session = Depends(get_session),
) -> PlanApproveResponse:
    """Approve all unapproved assignments in a single transaction.

    Verifies adequate warehouse inventory for all assignments before applying deductions (all-or-nothing).
    """
    if payload is None:
        payload = AssignmentApproveRequest()
    approved_by = payload.approved_by or "coordinator"

    unapproved = session.exec(
        select(Assignment).where(Assignment.approved == False).order_by(Assignment.id)
    ).all()

    if not unapproved:
        return PlanApproveResponse(approved=0, assignments=[])

    # Check total requirements per warehouse and resource
    needed_by_wh_res: dict[tuple[int, str], int] = {}
    for a in unapproved:
        key = (a.warehouse_id, a.resource)
        needed_by_wh_res[key] = needed_by_wh_res.get(key, 0) + a.quantity

    for (wid, res), total_needed in needed_by_wh_res.items():
        inv = session.exec(
            select(Inventory).where(
                Inventory.warehouse_id == wid,
                Inventory.resource == res,
            )
        ).first()
        avail = inv.quantity if inv else 0
        if avail < total_needed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Insufficient stock in warehouse {wid} for {res}: "
                    f"need {total_needed}, available {avail}. Plan approval rejected."
                ),
            )

    # Deduct inventory stock and mark assignments approved
    now = datetime.now(timezone.utc)
    for a in unapproved:
        inv = session.exec(
            select(Inventory).where(
                Inventory.warehouse_id == a.warehouse_id,
                Inventory.resource == a.resource,
            )
        ).first()
        if inv:
            inv.quantity -= a.quantity
            session.add(inv)

        a.approved = True
        a.approved_by = approved_by
        a.approved_at = now
        session.add(a)

        req = session.get(Request, a.request_id)
        if req:
            req.status = RequestStatus.ASSIGNED.value
            session.add(req)

    session.commit()

    log_agent(
        session,
        agent="Relief",
        message=f"Plan approved: {len(unapproved)} assignments approved by {approved_by}",
    )

    assignment_reads = [build_assignment_read(session, a) for a in unapproved]
    return PlanApproveResponse(
        approved=len(unapproved),
        assignments=assignment_reads,
    )


@router.post(
    "/assignments/{id}/dispatch",
    response_model=AssignmentRead,
    summary="Dispatch an approved assignment",
)
def dispatch_assignment(
    id: int,
    session: Session = Depends(get_session),
) -> AssignmentRead:
    """Dispatch an approved relief assignment, updating request status to on_the_way."""
    assignment = session.get(Assignment, id)
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assignment with id {id} not found",
        )
    if not assignment.approved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Assignment {id} must be approved before dispatch",
        )

    req = session.get(Request, assignment.request_id)
    if req:
        req.status = RequestStatus.ON_THE_WAY.value
        session.add(req)
        session.commit()

    req_ref = f"R{req.id}" if req and req.id else f"R{assignment.request_id}"
    log_agent(
        session,
        agent="Relief",
        message=f"Assignment {assignment.id} dispatched ({req_ref} on the way)",
    )

    return build_assignment_read(session, assignment)


@router.post(
    "/relief/routes",
    response_model=RoutesComputeResponse,
    summary="Compute safe delivery routes for all assignments",
)
def compute_all_routes(
    force: bool = Query(
        default=False,
        description="Whether to recompute routes for assignments that already have one.",
    ),
    session: Session = Depends(get_session),
) -> RoutesComputeResponse:
    """Calculate and attach hazard-avoiding delivery routes to active assignments."""
    computed = compute_routes(session, force=force)
    all_assignments = session.exec(select(Assignment).order_by(Assignment.id)).all()
    reads = [build_assignment_read(session, a) for a in all_assignments]
    return RoutesComputeResponse(
        computed=len(computed),
        assignments=reads,
    )


@router.post(
    "/assignments/{id}/route",
    response_model=AssignmentRead,
    summary="Calculate route for a specific assignment",
)
def compute_single_assignment_route(
    id: int,
    force: bool = Query(
        default=False,
        description="Whether to recompute if route already exists.",
    ),
    session: Session = Depends(get_session),
) -> AssignmentRead:
    """Calculate and attach a hazard-avoiding delivery route for a single assignment."""
    assignment = session.get(Assignment, id)
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assignment with id {id} not found",
        )

    if assignment.route is None or force:
        wh = session.get(Warehouse, assignment.warehouse_id)
        req = session.get(Request, assignment.request_id)
        if not wh or not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Associated warehouse or request not found",
            )

        hazards = session.exec(select(HazardZone)).all()
        route = get_route(
            origin=(wh.lat, wh.lon),
            destination=(req.lat, req.lon),
            hazards=hazards,
            use_hazards=True,
        )
        assignment.route = route
        session.add(assignment)
        session.commit()
        session.refresh(assignment)

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

    return build_assignment_read(session, assignment)
