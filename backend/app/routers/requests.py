"""Router for citizen distress and emergency relief requests."""

from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from shapely.geometry import Point, shape
from sqlalchemy import nulls_last
from sqlmodel import Session, select
from app.config import settings
from app.constants import RequestStatus
from app.db import get_session
from app.models import Region, Request
from app.schemas import RequestCreate, RequestRead, ScoreFactorBreakdown, format_iso_utc
from app.services.request_intake import create_request as intake_create_request

router = APIRouter(prefix="/requests", tags=["Requests"])


def _to_request_read(req: Request, region_name: Optional[str] = None) -> RequestRead:
    """Format database Request model to additive RequestRead schema."""
    breakdown_models = None
    if req.score_breakdown:
        breakdown_models = [
            ScoreFactorBreakdown(**b) if isinstance(b, dict) else b
            for b in req.score_breakdown
        ]

    return RequestRead(
        id=req.id if req.id is not None else 0,
        ref=f"R{req.id}",
        text=req.text,
        name=req.name,
        lat=req.lat,
        lon=req.lon,
        region_id=req.region_id,
        region_name=region_name,
        status=req.status,
        resource_needed=req.resource_needed,
        people_count=req.people_count,
        urgency=req.urgency,
        priority_score=req.priority_score,
        reason=req.reason,
        need_summary=req.need_summary,
        triage_source=req.triage_source,
        needs_review=req.needs_review,
        score_breakdown=breakdown_models,
        created_at=format_iso_utc(req.created_at),
    )


@router.get(
    "",
    response_model=list[RequestRead],
    summary="List emergency requests sorted by priority and recency",
)
def list_requests(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    region_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
) -> list[RequestRead]:
    """Retrieve all requests with optional status and region filters."""
    # Pre-fetch region names for efficient mapping
    regions = session.exec(select(Region)).all()
    region_map: dict[int, str] = {r.id: r.name for r in regions if r.id is not None}

    # Query with sorting: priority_score desc (nulls last), then created_at desc
    query = select(Request).order_by(
        nulls_last(Request.priority_score.desc()), Request.created_at.desc()
    )

    if status_filter is not None:
        query = query.where(Request.status == status_filter)
    if region_id is not None:
        query = query.where(Request.region_id == region_id)

    requests = session.exec(query).all()

    return [
        _to_request_read(req, region_map.get(req.region_id) if req.region_id else None)
        for req in requests
    ]


@router.post(
    "",
    response_model=RequestRead,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new citizen distress request with automated region detection",
)
def create_request(
    payload: RequestCreate,
    session: Session = Depends(get_session),
) -> RequestRead:
    """Submit a citizen emergency request.

    Determines regional flood zone using Shapely point-in-polygon check.
    Triages on submit if TRIAGE_ON_SUBMIT is enabled.
    """
    db_request = intake_create_request(
        session=session,
        text=payload.text,
        lat=payload.lat,
        lon=payload.lon,
        name=payload.name,
        triage=settings.TRIAGE_ON_SUBMIT,
    )

    region_name: Optional[str] = None
    if db_request.region_id is not None:
        region = session.get(Region, db_request.region_id)
        if region is not None:
            region_name = region.name

    return _to_request_read(db_request, region_name)
