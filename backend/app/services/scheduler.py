"""Background scheduler service for optional periodic risk checks."""

import logging
from sqlmodel import Session, func, select
from app.db import engine
from app.models import Request, SimulationState
from app.services import orchestrator
from app.services.agent_log import log_agent

logger = logging.getLogger(__name__)


def scheduled_risk_check() -> None:
    """Run periodic flood risk assessment using live weather when system is idle.

    Only executes when simulation is at stage 1 and no requests exist in the database.
    Otherwise, logs 'Skipped scheduled check: simulation in progress' and returns.
    Opens its own database session and never raises an exception.
    """
    try:
        with Session(engine) as session:
            sim_state = session.get(SimulationState, 1)
            stage = sim_state.stage if sim_state else 1

            request_count = session.exec(select(func.count(Request.id))).one() or 0

            if stage > 1 or request_count > 0:
                log_agent(
                    session,
                    agent="Orchestrator",
                    message="Skipped scheduled check: simulation in progress",
                )
                return

            log_agent(
                session,
                agent="Orchestrator",
                message="Starting scheduled periodic risk check",
            )
            orchestrator.assess_risk(session, overrides=None)
    except Exception as exc:
        logger.exception("Error during scheduled_risk_check: %s", exc)
