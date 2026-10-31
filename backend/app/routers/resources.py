"""Router for relief resource inventory and shortage forecasting."""

from fastapi import APIRouter, Depends
from sqlmodel import Session
from app.db import get_session
from app.schemas import ShortagesResponse
from app.services.shortage import predict_shortages

router = APIRouter(prefix="/resources", tags=["Resources"])


@router.get(
    "/shortages",
    response_model=ShortagesResponse,
    summary="Get predicted supply demand, stockpile adequacy, and shortfall estimates",
)
def get_resource_shortages(
    session: Session = Depends(get_session),
) -> ShortagesResponse:
    """Predict regional relief supply shortfalls based on active flood risk levels.

    Assumptions are illustrative demo estimates, not official civil forecasts.
    """
    shortages_data = predict_shortages(session)
    return ShortagesResponse(**shortages_data)
