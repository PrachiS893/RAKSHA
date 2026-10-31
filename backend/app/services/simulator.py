"""Flood scenario simulation engine managing multi-stage disaster progression.

Executes real backend agents, alert workflows, and request ingestion.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional
from sqlmodel import Session, delete, select
from app.agents.risk_agent import run_risk_agent_all
from app.constants import (
    AlertLevel,
    AlertStatus,
    RequestStatus,
    RiskLevel,
)
from app.demo_data import (
    FLOODED_ZONES_STAGE_3,
    SAMPLE_REQUESTS,
    STAGE_RAINFALL,
    STAGES,
)
from app.models import (
    AgentLog,
    Alert,
    Assignment,
    Delivery,
    Inventory,
    Region,
    Request,
    SimulationState,
)
from app.schemas import (
    SimulationHighestRisk,
    SimulationRegionStat,
    SimulationStateRead,
    SimulationStats,
)
from app.services.agent_log import log_agent
from app.services.alert_rules import LEVEL_LABELS
from app.services.notification import handle_risk_reports
from app.services.request_intake import create_request

logger = logging.getLogger(__name__)


class SimulationFinished(Exception):
    """Raised when advance is attempted on an already-completed simulation (stage 5)."""


def get_state(session: Session) -> int:
    """Retrieve current simulation stage integer, initializing to stage 1 if missing."""
    sim_state = session.get(SimulationState, 1)
    if sim_state is None:
        sim_state = SimulationState(id=1, stage=1)
        session.add(sim_state)
        session.commit()
        session.refresh(sim_state)
    return sim_state.stage


def get_stage_rainfall_by_id(session: Session, stage: int) -> dict[int, float]:
    """Map region names in STAGE_RAINFALL to database region IDs."""
    rainfall_by_name = STAGE_RAINFALL.get(stage, {})
    regions = session.exec(select(Region)).all()
    override_by_id: dict[int, float] = {}
    for r in regions:
        if r.id is None:
            continue
        if r.name in rainfall_by_name:
            override_by_id[r.id] = rainfall_by_name[r.name]
        else:
            for name_key, val in rainfall_by_name.items():
                if name_key in r.name or r.name in name_key:
                    override_by_id[r.id] = val
                    break
    return override_by_id


def handle_stage_2(session: Session) -> list[str]:
    """Execute Stage 2: Heavy rainfall forecast.
    
    Runs Risk Agent across all regions and drafts/dispatches alerts.
    """
    override_by_id = get_stage_rainfall_by_id(session, stage=2)
    reports = run_risk_agent_all(session, override_by_region=override_by_id, persist=True)
    created_alerts = handle_risk_reports(session, reports)

    events: list[str] = []
    for report in reports:
        events.append(f"{report.region} risk is now {report.risk_level.value}")

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

    return events


def handle_stage_3(session: Session) -> list[str]:
    """Execute Stage 3: Flood begins.

    Marks flooded zones, re-runs Risk Agent with increased rain, and intakes 4 emergency requests.
    """
    flooded_names: list[str] = []
    regions = session.exec(select(Region)).all()
    for r in regions:
        if any(fz in r.name or r.name in fz for fz in FLOODED_ZONES_STAGE_3):
            r.is_flooded = True
            flooded_names.append(r.name)
        else:
            r.is_flooded = False
        session.add(r)
    session.commit()

    override_by_id = get_stage_rainfall_by_id(session, stage=3)
    reports = run_risk_agent_all(session, override_by_region=override_by_id, persist=True)
    handle_risk_reports(session, reports)

    for req_data in SAMPLE_REQUESTS:
        create_request(
            session=session,
            text=req_data["text"],
            lat=req_data["lat"],
            lon=req_data["lon"],
            name=req_data.get("name"),
        )
    log_agent(session, agent="Orchestrator", message="4 emergency requests received")

    events: list[str] = [
        f"Flooding started in {', '.join(flooded_names)}",
        "Rainfall increased across all monitored zones",
        "4 emergency requests received",
    ]
    return events


def on_stage_4(session: Session) -> list[str]:
    """Hook function for Stage 4 (Triage and Allocation).

    TODO (Steps B8/B9):
      - Step B8: Execute Triage Agent to score and prioritize pending emergency requests.
      - Step B9: Execute Relief Allocation Agent to assign warehouse inventory to requests.
    """
    log_agent(session, agent="Orchestrator", message="Triage and allocation will run here")
    return ["Triage and allocation will run here (placeholder for steps B8/B9)"]


def on_stage_5(session: Session) -> list[str]:
    """Hook function for Stage 5 (Routes and Approval).

    TODO (Step B10):
      - Calculate safe delivery routes avoiding flooded zones.
      - Present full disaster response plan for human coordinator approval.
    """
    log_agent(
        session,
        agent="Orchestrator",
        message="Route calculation and final approval plan will run here",
    )
    return ["Route calculation and final approval plan will run here (placeholder for step B10)"]


def reset(session: Session) -> list[str]:
    """Reset simulation environment to Stage 1: Normal conditions.

    Clears operational tables, restores inventory, and sets regions to low risk.
    Keeps citizen subscriptions intact.
    """
    # Delete generated operational data
    session.exec(delete(Delivery))
    session.exec(delete(Assignment))
    session.exec(delete(Alert))
    session.exec(delete(Request))
    session.exec(delete(AgentLog))

    # Restore inventory stockpiles
    inventory_items = session.exec(select(Inventory)).all()
    for item in inventory_items:
        item.quantity = item.initial_quantity
        session.add(item)

    # Reset regions to baseline
    regions = session.exec(select(Region)).all()
    for r in regions:
        r.risk_level = RiskLevel.LOW.value
        r.rainfall_mm = 0.0
        r.is_flooded = False
        session.add(r)

    # Set simulation stage back to 1
    sim_state = session.get(SimulationState, 1)
    if sim_state is None:
        sim_state = SimulationState(id=1, stage=1)
    else:
        sim_state.stage = 1
        sim_state.updated_at = datetime.now(timezone.utc)
    session.add(sim_state)
    session.commit()

    log_agent(
        session,
        agent="Orchestrator",
        message="Simulation reset to stage 1: Normal conditions",
    )

    return ["Simulation reset to stage 1: Normal conditions"]


def advance(session: Session) -> list[str]:
    """Advance the simulation to the next stage, executing stage actions and returning events."""
    current_stage = get_state(session)
    if current_stage >= 5:
        raise SimulationFinished(
            "Simulation is already at stage 5 (final stage). Reset to start over."
        )

    next_stage = current_stage + 1
    sim_state = session.get(SimulationState, 1)
    if sim_state is None:
        sim_state = SimulationState(id=1, stage=next_stage)
    else:
        sim_state.stage = next_stage
        sim_state.updated_at = datetime.now(timezone.utc)
    session.add(sim_state)
    session.commit()

    stage_meta = next((s for s in STAGES if s["stage"] == next_stage), None)
    stage_name = stage_meta["name"] if stage_meta else f"Stage {next_stage}"

    log_agent(
        session,
        agent="Orchestrator",
        message=f"Entering stage {next_stage}: {stage_name}",
    )

    if next_stage == 2:
        events = handle_stage_2(session)
    elif next_stage == 3:
        events = handle_stage_3(session)
    elif next_stage == 4:
        events = on_stage_4(session)
    elif next_stage == 5:
        events = on_stage_5(session)
    else:
        events = []

    return events


def get_stats(session: Session) -> dict[str, Any]:
    """Compute aggregated operational metrics across the active simulation state."""
    regions = session.exec(select(Region).order_by(Region.id)).all()
    risk_rank = {
        RiskLevel.LOW.value: 0,
        RiskLevel.MODERATE.value: 1,
        RiskLevel.HIGH.value: 2,
        RiskLevel.SEVERE.value: 3,
    }

    if regions:
        # Highest risk using LOW < MODERATE < HIGH < SEVERE (ties: lowest region id)
        highest = max(
            regions,
            key=lambda r: (risk_rank.get(r.risk_level, 0), -(r.id or 0)),
        )
        highest_risk = {
            "region_id": highest.id,
            "region": highest.name,
            "risk_level": highest.risk_level,
        }
    else:
        highest_risk = None

    region_stats = [
        {
            "id": r.id,
            "name": r.name,
            "risk_level": r.risk_level,
            "rainfall_mm": r.rainfall_mm,
            "is_flooded": r.is_flooded,
        }
        for r in regions
    ]

    requests = session.exec(select(Request)).all()
    open_requests = sum(
        1 for req in requests if req.status != RequestStatus.ASSIGNED.value
    )

    alerts = session.exec(select(Alert)).all()
    pending_alerts = sum(1 for a in alerts if a.status == AlertStatus.DRAFT.value)
    sent_alerts = sum(1 for a in alerts if a.status == AlertStatus.SENT.value)

    inventory_items = session.exec(select(Inventory)).all()
    total_qty = sum(item.quantity for item in inventory_items)
    total_initial = sum(item.initial_quantity for item in inventory_items)
    if total_initial > 0:
        stock_remaining_pct = round((total_qty / total_initial) * 100, 1)
    else:
        stock_remaining_pct = 100.0

    return {
        "highest_risk": highest_risk,
        "regions": region_stats,
        "open_requests": open_requests,
        "pending_alerts": pending_alerts,
        "sent_alerts": sent_alerts,
        "stock_remaining_pct": stock_remaining_pct,
    }


def get_simulation_state_response(
    session: Session, events: Optional[list[str]] = None
) -> SimulationStateRead:
    """Format full simulation state response including stage description and current stats."""
    current_stage = get_state(session)
    stage_meta = next(
        (s for s in STAGES if s["stage"] == current_stage),
        STAGES[0],
    )
    stats_dict = get_stats(session)

    highest_risk_obj = (
        SimulationHighestRisk(**stats_dict["highest_risk"])
        if stats_dict["highest_risk"]
        else None
    )
    regions_list = [SimulationRegionStat(**r) for r in stats_dict["regions"]]

    stats_obj = SimulationStats(
        highest_risk=highest_risk_obj,
        regions=regions_list,
        open_requests=stats_dict["open_requests"],
        pending_alerts=stats_dict["pending_alerts"],
        sent_alerts=stats_dict["sent_alerts"],
        stock_remaining_pct=stats_dict["stock_remaining_pct"],
    )

    return SimulationStateRead(
        stage=current_stage,
        total_stages=5,
        name=stage_meta["name"],
        description=stage_meta["description"],
        can_advance=(current_stage < 5),
        label="Illustrative simulation, not a live emergency feed.",
        stats=stats_obj,
        events=events if events is not None else [],
    )
