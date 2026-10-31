"""Audit logging service for tracking agent actions and system telemetry."""

from typing import Any, Optional
from sqlmodel import Session
from app.models import AgentLog


def log_agent(
    session: Session, agent: str, message: str, payload: Optional[dict[str, Any]] = None
) -> AgentLog:
    """Record an agent execution event in the agent_logs table and commit."""
    log_entry = AgentLog(agent=agent, message=message, payload=payload)
    session.add(log_entry)
    session.commit()
    session.refresh(log_entry)
    return log_entry
