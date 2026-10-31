"""Router for public flood safety alerts and coordinator approval workflows."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, col, select
from app.constants import AlertLevel, AlertStatus
from app.db import get_session
from app.models import Alert, Delivery, Region
from app.schemas import AlertApproveRequest, AlertRead, DeliveryRead, format_iso_utc
from app.services.alert_rules import LEVEL_LABELS, requires_approval
from app.services.notification import send_alert

router = APIRouter(prefix="/alerts", tags=["Alerts"])


def _to_alert_read(
    session: Session,
    alert: Alert,
    region_name: str,
    include_deliveries: bool = True,
) -> AlertRead:
    """Format an Alert SQLModel instance into the unified AlertRead response schema."""
    try:
        lvl = AlertLevel(alert.level)
        label = LEVEL_LABELS[lvl]
        req_approval = requires_approval(lvl)
    except (ValueError, KeyError):
        label = alert.level
        req_approval = True

    deliveries_read: list[DeliveryRead] = []
    if include_deliveries and alert.id is not None:
        deliveries = session.exec(
            select(Delivery).where(Delivery.alert_id == alert.id)
        ).all()
        deliveries_read = [
            DeliveryRead(
                channel=d.channel,
                status=d.status,
                recipient=d.recipient,
                detail=d.detail,
                sent_at=format_iso_utc(d.sent_at) if d.sent_at else None,
            )
            for d in deliveries
        ]

    return AlertRead(
        id=alert.id if alert.id is not None else 0,
        region_id=alert.region_id,
        region_name=region_name,
        level=alert.level,
        level_label=label,
        message=alert.message,
        status=alert.status,
        requires_approval=req_approval,
        approved_by=alert.approved_by,
        approved_at=format_iso_utc(alert.approved_at) if alert.approved_at else None,
        created_at=format_iso_utc(alert.created_at),
        deliveries=deliveries_read,
    )


@router.get(
    "",
    response_model=list[AlertRead],
    summary="List approved and sent public citizen alerts with delivery history",
)
def list_alerts(
    region_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
) -> list[AlertRead]:
    """Retrieve citizen alert feed containing only approved or sent alerts, newest first."""
    regions = session.exec(select(Region)).all()
    region_map: dict[int, str] = {r.id: r.name for r in regions if r.id is not None}

    query = (
        select(Alert)
        .where(
            col(Alert.status).in_([AlertStatus.APPROVED.value, AlertStatus.SENT.value])
        )
        .order_by(Alert.created_at.desc())
    )

    if region_id is not None:
        query = query.where(Alert.region_id == region_id)

    alerts = session.exec(query).all()
    return [
        _to_alert_read(
            session=session,
            alert=a,
            region_name=region_map.get(a.region_id, "Unknown Region"),
            include_deliveries=True,
        )
        for a in alerts
    ]


@router.get(
    "/pending",
    response_model=list[AlertRead],
    summary="List draft alerts awaiting human coordinator approval",
)
def list_pending_alerts(
    session: Session = Depends(get_session),
) -> list[AlertRead]:
    """Retrieve all draft alerts currently awaiting human coordinator review."""
    regions = session.exec(select(Region)).all()
    region_map: dict[int, str] = {r.id: r.name for r in regions if r.id is not None}

    alerts = session.exec(
        select(Alert)
        .where(Alert.status == AlertStatus.DRAFT.value)
        .order_by(Alert.created_at.desc())
    ).all()

    return [
        _to_alert_read(
            session=session,
            alert=a,
            region_name=region_map.get(a.region_id, "Unknown Region"),
            include_deliveries=False,
        )
        for a in alerts
    ]


@router.post(
    "/{id}/approve",
    response_model=AlertRead,
    summary="Approve and dispatch a draft alert",
)
def approve_alert(
    id: int,
    payload: Optional[AlertApproveRequest] = None,
    session: Session = Depends(get_session),
) -> AlertRead:
    """Approve a draft disaster alert, optionally applying an edited message, and trigger dispatch."""
    if payload is None:
        payload = AlertApproveRequest()

    alert = session.get(Alert, id)
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with id {id} not found",
        )

    if alert.status != AlertStatus.DRAFT.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Alert {id} is not in draft status (current: {alert.status})",
        )

    region = session.get(Region, alert.region_id)
    region_name = region.name if region else "Unknown Region"

    # Validate edited message if provided
    if payload.message is not None:
        edited = payload.message.strip()
        if len(edited) < 10 or len(edited) > 320:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Edited alert message must be between 10 and 320 characters",
            )
        short_region = region_name.split(" - ")[0].strip()
        if (region_name.lower() not in edited.lower()) and (
            short_region.lower() not in edited.lower()
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Edited alert message must reference the region name ('{region_name}')",
            )

    approved_alert = send_alert(
        session=session,
        alert=alert,
        approved_by=payload.approved_by,
        edited_message=payload.message,
    )

    return _to_alert_read(
        session=session,
        alert=approved_alert,
        region_name=region_name,
        include_deliveries=True,
    )
