"""Relief Coordination Agent for proposing and managing supply allocations.

GOLDEN RULES:
- Allocation is a RECOMMENDATION. Stock is only reduced when a coordinator approves.
- Highest priority requests are served first; each request gets the NEAREST warehouse that has enough stock.
- Shortage numbers are demo planning assumptions, not real forecasts. Label them as such everywhere.
"""

from datetime import datetime, timezone
import logging
from typing import Optional
from sqlmodel import Session, delete, select
from app.agents.triage_agent import run_triage_all
from app.constants import RequestStatus, Resource
from app.models import Assignment, Inventory, Region, Request, Warehouse
from app.schemas import (
    AssignmentRead,
    ReliefPlan,
    ReliefPlanSummary,
    UnmetRequestItem,
    format_iso_utc,
)
from app.services.agent_log import log_agent
from app.services.allocation import RESOURCE_UNITS, allocate, quantity_needed

logger = logging.getLogger(__name__)


def build_assignment_read(
    session: Session,
    assignment: Assignment,
    req_map: Optional[dict[int, Request]] = None,
    wh_map: Optional[dict[int, Warehouse]] = None,
    reg_map: Optional[dict[int, Region]] = None,
) -> AssignmentRead:
    """Format an Assignment database record into the standardized AssignmentRead schema."""
    req = req_map.get(assignment.request_id) if req_map else session.get(Request, assignment.request_id)
    wh = wh_map.get(assignment.warehouse_id) if wh_map else session.get(Warehouse, assignment.warehouse_id)

    region_name: Optional[str] = None
    if req and req.region_id is not None:
        reg = reg_map.get(req.region_id) if reg_map else session.get(Region, req.region_id)
        if reg:
            region_name = reg.name

    unit = RESOURCE_UNITS.get(assignment.resource, "units")
    wh_name = wh.name if wh else f"Warehouse {assignment.warehouse_id}"

    return AssignmentRead(
        id=assignment.id if assignment.id is not None else 0,
        request_id=assignment.request_id,
        request_ref=f"R{assignment.request_id}",
        region_name=region_name,
        priority_score=req.priority_score if req else None,
        urgency=req.urgency if req else None,
        resource=assignment.resource,
        unit=unit,
        quantity=assignment.quantity,
        warehouse_id=assignment.warehouse_id,
        warehouse=wh_name,
        distance_km=assignment.distance_km,
        partial=assignment.partial,
        unmet_quantity=assignment.unmet_quantity,
        reason=assignment.reason,
        route=assignment.route,
        approval_required=assignment.approval_required,
        approved=assignment.approved,
        approved_by=assignment.approved_by,
        approved_at=format_iso_utc(assignment.approved_at) if assignment.approved_at else None,
        request_status=req.status if req else "prioritized",
    )


def get_current_relief_plan(session: Session) -> ReliefPlan:
    """Construct the active relief allocation plan from existing assignments and requests without recomputing."""
    assignments = session.exec(select(Assignment).order_by(Assignment.id)).all()
    requests = session.exec(select(Request)).all()
    warehouses = session.exec(select(Warehouse)).all()
    regions = session.exec(select(Region)).all()

    req_map = {r.id: r for r in requests if r.id is not None}
    wh_map = {w.id: w for w in warehouses if w.id is not None}
    reg_map = {rg.id: rg for rg in regions if rg.id is not None}

    # Format assignments
    assignment_reads = [
        build_assignment_read(session, a, req_map, wh_map, reg_map)
        for a in assignments
    ]

    # Sort assignments by priority_score desc, request created_at asc, id asc
    assignment_reads.sort(
        key=lambda ar: (
            -(ar.priority_score or 0),
            req_map[ar.request_id].created_at if ar.request_id in req_map else 0,
            ar.id,
        )
    )

    # Compute unmet list from requests with status "shortage" or prioritized with no assignment
    assigned_req_ids = {a.request_id for a in assignments}
    unmet_items: list[UnmetRequestItem] = []

    for req in requests:
        if req.id is None:
            continue
        if req.status == RequestStatus.SHORTAGE.value:
            need = quantity_needed(req.resource_needed, req.people_count)
            unmet_items.append(
                UnmetRequestItem(
                    request_id=req.id,
                    request_ref=f"R{req.id}",
                    resource=req.resource_needed,
                    quantity_needed=need,
                    reason="No stock available",
                )
            )
        elif req.status == RequestStatus.PRIORITIZED.value and req.id not in assigned_req_ids:
            if not req.resource_needed:
                reason = "Needs coordinator decision: no clear resource identified"
            else:
                reason = "No stock available"
            need = quantity_needed(req.resource_needed, req.people_count)
            unmet_items.append(
                UnmetRequestItem(
                    request_id=req.id,
                    request_ref=f"R{req.id}",
                    resource=req.resource_needed,
                    quantity_needed=need,
                    reason=reason,
                )
            )

    # Calculate summary metrics
    considered_req_ids = set(assigned_req_ids).union({u.request_id for u in unmet_items})
    assigned_count = sum(1 for a in assignments if not a.partial)
    partial_count = sum(1 for a in assignments if a.partial)
    awaiting_count = sum(1 for a in assignments if not a.approved)
    approved_count = sum(1 for a in assignments if a.approved)

    summary = ReliefPlanSummary(
        requests_considered=len(considered_req_ids),
        assigned=assigned_count,
        partial=partial_count,
        unmet=len(unmet_items),
        awaiting_approval=awaiting_count,
        approved=approved_count,
    )

    now = datetime.now(timezone.utc)
    return ReliefPlan(
        generated_at=format_iso_utc(now),
        summary=summary,
        assignments=assignment_reads,
        unmet=unmet_items,
    )


def run_relief_agent(session: Session, triage_first: bool = True) -> ReliefPlan:
    """Execute the Relief Coordination Agent pipeline to recommend warehouse supply allocations.

    Steps:
      1. If triage_first is True, invoke run_triage_all so any received requests are prioritized.
      2. Check available stockpiles across warehouses.
      3. Delete existing unapproved assignments for idempotent re-planning.
      4. Allocate supplies using the pure allocate algorithm (nearest warehouse with stock).
      5. Persist proposed assignments as unapproved recommendations.
      6. Update request statuses (prioritized or shortage).
      7. Return the ReliefPlan without modifying warehouse inventory.
    """
    # 1. Triage first if requested
    if triage_first:
        run_triage_all(session)

    # 2. Check supplies across warehouses
    warehouses = session.exec(select(Warehouse).order_by(Warehouse.id)).all()
    log_agent(
        session,
        agent="Relief",
        message=f"Checking supplies across {len(warehouses)} warehouses",
    )

    # 3. Delete existing unapproved assignments (idempotent re-planning)
    session.exec(delete(Assignment).where(Assignment.approved == False))
    session.commit()

    # 4. Consider requests with status "prioritized" or "shortage" only
    candidate_requests = session.exec(
        select(Request).where(
            Request.status.in_([
                RequestStatus.PRIORITIZED.value,
                RequestStatus.SHORTAGE.value,
            ])
        )
    ).all()

    # Read current warehouse inventory
    inventories = session.exec(select(Inventory)).all()
    warehouses_stock: dict[int, dict[str, int]] = {w.id: {} for w in warehouses if w.id is not None}
    for item in inventories:
        if item.warehouse_id in warehouses_stock:
            warehouses_stock[item.warehouse_id][item.resource] = item.quantity

    warehouse_coords: dict[int, tuple[float, float]] = {
        w.id: (w.lat, w.lon) for w in warehouses if w.id is not None
    }
    warehouse_names: dict[int, str] = {
        w.id: w.name for w in warehouses if w.id is not None
    }

    # 5. Execute pure allocation
    proposed_assignments, unmet_list = allocate(
        requests=candidate_requests,
        warehouses_stock=warehouses_stock,
        warehouse_coords=warehouse_coords,
        warehouse_names=warehouse_names,
    )

    # 6. Persist proposed assignments and log
    assigned_request_ids: set[int] = set()
    for a_data in proposed_assignments:
        assignment = Assignment(
            request_id=a_data["request_id"],
            warehouse_id=a_data["warehouse_id"],
            resource=a_data["resource"],
            quantity=a_data["quantity"],
            distance_km=a_data["distance_km"],
            partial=a_data["partial"],
            unmet_quantity=a_data["unmet_quantity"],
            reason=a_data["reason"],
            route=None,
            approval_required=True,
            approved=False,
            approved_by=None,
            approved_at=None,
        )
        session.add(assignment)
        assigned_request_ids.add(a_data["request_id"])

        # Log line per request
        req_ref = a_data["request_ref"]
        urg = a_data["urgency"]
        score = a_data["priority_score"]
        res = a_data["resource"]
        qty = a_data["quantity"]
        w_name = a_data["warehouse"]
        dist = a_data["distance_km"]
        log_agent(
            session,
            agent="Relief",
            message=f"{req_ref} ({urg} {score}): {res} x{qty} from {w_name} ({dist:.1f} km)",
        )

    # Log unmet requests
    for u in unmet_list:
        req = next((r for r in candidate_requests if r.id == u["request_id"]), None)
        urg = req.urgency if req else "LOW"
        score = req.priority_score if req else 0
        ref = u["request_ref"]
        res = u["resource"] or "unspecified"
        qty = u["quantity_needed"]
        log_agent(
            session,
            agent="Relief",
            message=f"{ref} ({urg} {score}): {res} unmet: {u['reason']}",
        )

    # 7. Update request statuses
    for req in candidate_requests:
        if req.id in assigned_request_ids:
            req.status = RequestStatus.PRIORITIZED.value
            session.add(req)
        elif not req.resource_needed:
            req.status = RequestStatus.PRIORITIZED.value
            req.needs_review = True
            session.add(req)
        else:
            req.status = RequestStatus.SHORTAGE.value
            session.add(req)

    session.commit()

    # 8. Log plan ready summary
    log_agent(
        session,
        agent="Relief",
        message=(
            f"Plan ready: {len(proposed_assignments)} assignments awaiting "
            f"coordinator approval, {len(unmet_list)} unmet"
        ),
    )

    # 9. Return current plan
    return get_current_relief_plan(session)
