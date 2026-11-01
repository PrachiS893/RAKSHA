"""Orchestrator service coordinating multi-agent workflows, handoffs, and hazard states."""

from dataclasses import dataclass, field
import logging
from typing import Any
from sqlmodel import Session, select
from app.agents.risk_agent import run_risk_agent_all
from app.constants import (
    AlertLevel,
    AlertStatus,
    RiskLevel,
)
from app.models import (
    Alert,
    Assignment,
    HazardZone,
    Region,
    Request,
)
from app.schemas import RiskReport
from app.services.agent_log import log_agent
from app.services.alert_rules import LEVEL_LABELS
from app.services.notification import handle_risk_reports
from app.services.request_intake import create_request

logger = logging.getLogger(__name__)


@dataclass
class AssessRiskResult:
    """Result of multi-region risk evaluation and alert drafting."""

    reports: list[RiskReport]
    alerts: list[Alert]
    events: list[str]


@dataclass
class ShortageResult:
    """Result of regional supply shortage forecasting."""

    shortages: dict[str, Any]
    events: list[str]


@dataclass
class RouteResult:
    """Result of route computation for relief assignments."""

    assignments: list[Assignment]
    events: list[str]


@dataclass
class ReliefPlanResult:
    """Result of request triage prioritization and warehouse stock allocation."""

    triage_results: list[Any]
    plan: Any
    routes_computed: list[Assignment] | None
    events: list[str]


@dataclass
class HazardsResult:
    """Result of hazard zone activation/deactivation."""

    hazards: list[HazardZone]
    events: list[str]


def assess_risk(
    session: Session,
    overrides: dict[int, float] | None = None,
    set_flooded: list[int] | None = None,
) -> AssessRiskResult:
    """Evaluate flood risk for all regions, optionally update flooded states, and draft alerts."""
    events: list[str] = []

    # Update flooded status if set_flooded is provided
    if set_flooded is not None:
        regions = session.exec(select(Region)).all()
        for r in regions:
            if r.id is not None and r.id in set_flooded:
                r.is_flooded = True
            else:
                r.is_flooded = False
            session.add(r)
        session.commit()

    # 1. Run Risk Agent across all monitored regions
    reports = run_risk_agent_all(session, override_by_region=overrides, persist=True)
    for report in reports:
        events.append(f"{report.region} risk is now {report.risk_level.value}")

    # 2. Orchestrator handoff log to Notification Service
    actionable_reports = [r for r in reports if r.risk_level != RiskLevel.LOW]
    log_agent(
        session,
        agent="Orchestrator",
        message=f"Passing {len(actionable_reports)} high-risk regions to Notification Service",
    )

    # 3. Notification service processes reports into draft / auto-sent alerts
    created_alerts = handle_risk_reports(session, reports)
    for alert in created_alerts:
        region = session.get(Region, alert.region_id)
        region_name = region.name if region else f"Region {alert.region_id}"
        try:
            lvl_enum = AlertLevel(alert.level)
            label = LEVEL_LABELS.get(lvl_enum, alert.level)
        except Exception:
            label = alert.level

        if alert.status == AlertStatus.SENT.value:
            events.append(f"{label} sent for {region_name}")
        else:
            events.append(f"{label} drafted for {region_name}, awaiting approval")

    return AssessRiskResult(reports=reports, alerts=created_alerts, events=events)


def predict_supply_shortages(session: Session) -> ShortageResult:
    """Predict supply deficits under active flood conditions and log warnings."""
    from app.services.shortage import predict_shortages

    shortage_data = predict_shortages(session)
    events: list[str] = []
    for res_info in shortage_data["resources"]:
        if res_info["status"] in ("SHORTAGE", "TIGHT"):
            r_name = res_info["resource"]
            stk = res_info["stock"]
            dem = res_info["predicted_demand"]
            status_label = res_info["status"]
            log_agent(
                session,
                agent="Relief",
                message=f"Shortage predicted: {r_name}, stock {stk} vs expected demand {dem}",
            )
            events.append(
                f"Shortage predicted: {r_name} ({status_label}, stock {stk} vs expected demand {dem})"
            )
    return ShortageResult(shortages=shortage_data, events=events)


def submit_request(
    session: Session,
    text: str,
    lat: float,
    lon: float,
    name: str | None = None,
    triage: bool = True,
) -> Request:
    """Single entry point for ingesting emergency distress requests."""
    return create_request(
        session=session,
        text=text,
        lat=lat,
        lon=lon,
        name=name,
        triage=triage,
    )


def compute_delivery_routes(session: Session, force: bool = True) -> RouteResult:
    """Compute safe delivery routes for all assignments avoiding active hazard zones."""
    from app.services.route_planner import compute_routes

    computed = compute_routes(session, force=force)
    assignments = session.exec(select(Assignment).order_by(Assignment.id)).all()

    events: list[str] = [f"Routes computed for {len(assignments)} assignments"]

    hazard_free_count = sum(1 for a in assignments if a.route and a.route.get("hazard_free"))
    providers = {
        a.route.get("provider")
        for a in assignments
        if a.route and a.route.get("provider")
    }
    provider_str = ", ".join(sorted(providers)) if providers else "none"

    events.append(
        f"{hazard_free_count} of {len(assignments)} routes avoid all hazard zones ({provider_str})"
    )

    for a in assignments:
        if not a.route:
            continue
        req_ref = f"R{a.request_id}"
        if not a.route.get("hazard_free"):
            warning = a.route.get("warning") or "Route crosses active hazard zone"
            events.append(f"{req_ref}: {warning}")
        elif a.route.get("warning"):
            events.append(f"{req_ref}: {a.route.get('warning')}")

    log_agent(
        session,
        agent="Orchestrator",
        message=f"Routes ready for {len(assignments)} assignments ({provider_str})",
    )

    return RouteResult(assignments=assignments, events=events)


def plan_relief(session: Session, with_routes: bool = True) -> ReliefPlanResult:
    """Coordinate triage prioritization, supply allocation, and optional hazard-avoiding delivery routes."""
    from app.agents.relief_agent import run_relief_agent
    from app.agents.triage_agent import run_triage_all

    # 1. Run Triage Agent on all pending distress calls
    triage_results = run_triage_all(session)
    events: list[str] = [f"Triage Agent ranked {len(triage_results)} requests"]
    for i, res in enumerate(triage_results):
        events.append(f"#{i+1} {res.ref}: {res.urgency.value} ({res.priority_score})")

    # 2. Orchestrator handoff log to Relief Agent
    log_agent(
        session,
        agent="Orchestrator",
        message=f"Passing {len(triage_results)} prioritized requests to Relief Agent",
    )

    # 3. Relief Agent proposes supply allocations from nearest warehouses
    plan = run_relief_agent(session, triage_first=False)
    events.append(
        f"Relief Agent proposed {len(plan.assignments)} assignments (awaiting coordinator approval)"
    )
    for u in plan.unmet:
        events.append(f"Unmet request {u.request_ref}: {u.resource} ({u.reason})")

    # 4. Optional routing if with_routes and hazard zones are active
    routes_computed: list[Assignment] | None = None
    if with_routes:
        active_hazards = session.exec(select(HazardZone).where(HazardZone.active == True)).all()
        if active_hazards:
            route_res = compute_delivery_routes(session, force=True)
            routes_computed = route_res.assignments
            events.extend(route_res.events)

    return ReliefPlanResult(
        triage_results=triage_results,
        plan=plan,
        routes_computed=routes_computed,
        events=events,
    )


def activate_hazards(session: Session, active: bool = True) -> HazardsResult:
    """Activate or deactivate simulated hazard zones and log orchestrator state change."""
    hazards = session.exec(select(HazardZone)).all()
    for h in hazards:
        h.active = active
        session.add(h)
    session.commit()

    msg = (
        f"{len(hazards)} hazard zones now active (simulated)"
        if active
        else f"{len(hazards)} hazard zones deactivated"
    )
    log_agent(session, agent="Orchestrator", message=msg)
    events = [msg]

    return HazardsResult(hazards=hazards, events=events)
