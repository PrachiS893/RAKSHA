"""Router for managing flood scenario simulation and progression."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session
from app.db import get_session
from app.schemas import SimulationStateRead
from app.services.simulator import (
    SimulationFinished,
    advance,
    get_simulation_state_response,
    reset,
)

router = APIRouter(prefix="/simulation", tags=["Simulation"])


@router.get(
    "",
    response_model=SimulationStateRead,
    summary="Get the current simulation stage, operational metrics, and stage description",
)
def get_simulation_status(
    session: Session = Depends(get_session),
) -> SimulationStateRead:
    """Retrieve current simulation stage and system state with an empty events list."""
    return get_simulation_state_response(session, events=[])


@router.post(
    "/next",
    response_model=SimulationStateRead,
    summary="Advance the simulation to the next stage",
)
def advance_simulation(
    session: Session = Depends(get_session),
) -> SimulationStateRead:
    """Advance to the next simulation stage and execute that stage's backend actions.

    Returns HTTP 409 Conflict if the simulation is already at the final stage (stage 5).
    """
    try:
        events = advance(session)
    except SimulationFinished as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return get_simulation_state_response(session, events=events)


@router.post(
    "/reset",
    response_model=SimulationStateRead,
    summary="Reset the simulation back to Stage 1: Normal conditions",
)
def reset_simulation(
    session: Session = Depends(get_session),
) -> SimulationStateRead:
    """Reset the operational data, inventory, and regions back to Stage 1."""
    events = reset(session)
    return get_simulation_state_response(session, events=events)
