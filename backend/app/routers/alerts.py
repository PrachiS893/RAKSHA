"""Router for public flood safety alerts."""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select
from app.constants import AlertStatus
from app.db import get_session
from app.models import Alert, Region
from app.schemas import AlertRead, format_iso_utc

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get(
    "",
    response_model=list[AlertRead],
    summary="List public citizen flood alerts (excluding drafts)",
)
def list_alerts(
    region_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
) -> list[AlertRead]:
    """Retrieve public emergency alerts that are not in draft status, newest first."""
    # Pre-fetch region names
    regions = session.exec(select(Region)).all()
    region_map: dict[int, str] = {r.id: r.name for r in regions if r.id is not None}

    query = (
        select(Alert)
        .where(Alert.status != AlertStatus.DRAFT.value)
        .order_by(Alert.created_at.desc())
    )

    if region_id is not None:
        query = query.where(Alert.region_id == region_id)

    alerts = session.exec(query).all()

    return [
        AlertRead(
            id=a.id,
            region_id=a.region_id,
            region_name=region_map.get(a.region_id, "Unknown Region"),
            level=a.level,
            message=a.message,
            status=a.status,
            approved_by=a.approved_by,
            created_at=format_iso_utc(a.created_at),
        )
        for a in alerts
    ]
