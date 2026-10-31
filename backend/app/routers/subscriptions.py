"""Router for citizen alert notification subscriptions."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from app.db import get_session
from app.models import Region, Subscription
from app.schemas import SubscriptionCreate, SubscriptionRead

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])


@router.post(
    "",
    response_model=SubscriptionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe to regional emergency flood alerts",
)
def create_subscription(
    payload: SubscriptionCreate,
    session: Session = Depends(get_session),
) -> SubscriptionRead:
    """Create a new citizen alert subscription for a specific region.

    Returns 404 if the requested region does not exist.
    """
    region = session.get(Region, payload.region_id)
    if not region:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Region with id {payload.region_id} does not exist",
        )

    subscription = Subscription(
        region_id=payload.region_id,
        name=payload.name,
        telegram_chat_id=payload.telegram_chat_id,
    )
    session.add(subscription)
    session.commit()
    session.refresh(subscription)

    return SubscriptionRead(
        id=subscription.id,
        region_id=subscription.region_id,
        region_name=region.name,
        name=subscription.name,
        telegram_chat_id=subscription.telegram_chat_id,
    )
