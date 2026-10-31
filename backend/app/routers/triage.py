"""Router for emergency triage and prioritization of citizen requests."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select
from app.agents.triage_agent import run_triage_agent, run_triage_all
from app.constants import RequestStatus
from app.db import get_session
from app.models import Request
from app.schemas import TriageResult, TriageRunResponse

router = APIRouter(tags=["Triage"])


@router.post(
    "/triage/run",
    response_model=TriageRunResponse,
    summary="Run triage agent across pending or all emergency requests",
)
def triage_run(
    force: bool = Query(
        default=False,
        description="If True, re-triages all requests. If False, triages only un-triaged (status=received) requests.",
    ),
    session: Session = Depends(get_session),
) -> TriageRunResponse:
    """Execute the Triage Agent to score and prioritize emergency requests.

    Returns the count of requests triaged in this run along with all ranked requests.
    """
    if force:
        to_triage = session.exec(select(Request)).all()
    else:
        to_triage = session.exec(
            select(Request).where(Request.status == RequestStatus.RECEIVED.value)
        ).all()
    to_triage_count = len(to_triage)

    ranked = run_triage_all(session=session, force=force)
    return TriageRunResponse(triaged=to_triage_count, ranked=ranked)


@router.post(
    "/requests/{request_id}/triage",
    response_model=TriageResult,
    summary="Re-run triage for a specific emergency request",
)
def triage_single_request(
    request_id: int,
    session: Session = Depends(get_session),
) -> TriageResult:
    """Re-run the Triage Agent on a single emergency request and update its record in the database."""
    db_request = session.get(Request, request_id)
    if db_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Request {request_id} not found",
        )

    result = run_triage_agent(session=session, request=db_request, persist=True)
    return result
