"""Development-only endpoints for manual testing, agent runs, and log verification."""

from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import Session, select
from app.agents.risk_agent import run_risk_agent
from app.db import get_session
from app.models import AgentLog, Region
from app.schemas import RiskReport, format_iso_utc

router = APIRouter(prefix="/dev", tags=["Dev (not for frontend)"])


class AgentLogRead(BaseModel):
    """Response schema for agent execution audit logs."""

    id: int
    agent: str
    message: str
    payload: Optional[dict[str, Any]] = None
    created_at: str


@router.post(
    "/risk-check/{region_id}",
    response_model=RiskReport,
    summary="Trigger the Risk Agent for a specific region (dev only)",
)
def dev_risk_check(
    region_id: int,
    rainfall_mm: Optional[float] = Query(default=None),
    persist: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> RiskReport:
    """Manually invoke the Risk Agent on a region with optional rainfall override."""
    region = session.get(Region, region_id)
    if not region:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Region with id {region_id} not found",
        )

    return run_risk_agent(
        session=session,
        region=region,
        override_rainfall_mm=rainfall_mm,
        persist=persist,
    )


@router.get(
    "/agent-logs",
    response_model=list[AgentLogRead],
    summary="Inspect recent agent audit logs, newest first (dev only)",
)
def get_agent_logs(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[AgentLogRead]:
    """Retrieve recent multi-agent system execution logs."""
    logs = session.exec(
        select(AgentLog).order_by(AgentLog.created_at.desc()).limit(limit)
    ).all()

    return [
        AgentLogRead(
            id=log.id,
            agent=log.agent,
            message=log.message,
            payload=log.payload,
            created_at=format_iso_utc(log.created_at),
        )
        for log in logs
    ]
