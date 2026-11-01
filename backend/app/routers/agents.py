"""Agents status endpoint reporting health, activity, and log counts for core autonomous agents."""

import logging
from typing import Optional
from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select
from app.db import get_session
from app.models import AgentLog
from app.schemas import AgentStatusRead, format_iso_utc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agents"])

# Fixed registry of core autonomous agents and supporting operational services
AGENTS_REGISTRY: list[dict[str, str]] = [
    {"name": "Risk", "kind": "agent"},
    {"name": "Triage", "kind": "agent"},
    {"name": "Relief", "kind": "agent"},
    {"name": "Orchestrator", "kind": "agent"},
    {"name": "Notification", "kind": "service"},
]


@router.get(
    "/agents",
    response_model=list[AgentStatusRead],
    summary="Retrieve status, latest activity, and log counts for core agents and services",
)
def get_agents_status(
    session: Session = Depends(get_session),
) -> list[AgentStatusRead]:
    """Retrieve operational status and recent activity for the 5 fixed system entities."""
    results: list[AgentStatusRead] = []

    for entity in AGENTS_REGISTRY:
        agent_name = entity["name"]
        kind = entity["kind"]

        # 1. Total log count for this agent
        count_stmt = select(func.count(AgentLog.id)).where(AgentLog.agent == agent_name)
        log_count = session.exec(count_stmt).one() or 0

        # 2. Most recent log record
        newest_stmt = (
            select(AgentLog)
            .where(AgentLog.agent == agent_name)
            .order_by(AgentLog.id.desc())
            .limit(1)
        )
        newest_log = session.exec(newest_stmt).first()

        last_active = format_iso_utc(newest_log.created_at) if newest_log else None
        last_message = newest_log.message if newest_log else None

        results.append(
            AgentStatusRead(
                name=agent_name,
                kind=kind,
                last_active=last_active,
                last_message=last_message,
                log_count=log_count,
            )
        )

    return results
