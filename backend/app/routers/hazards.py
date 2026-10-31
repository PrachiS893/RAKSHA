"""Router for monitored hazard zones and obstacles."""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from app.db import get_session
from app.models import HazardZone
from app.schemas import HazardZoneRead

router = APIRouter(prefix="/hazards", tags=["Hazards"])


@router.get(
    "",
    response_model=list[HazardZoneRead],
    summary="List all simulated hazard zones",
)
def list_hazards(session: Session = Depends(get_session)) -> list[HazardZoneRead]:
    """Retrieve all simulated hazard zones (active or inactive) with their boundary polygons."""
    hazards = session.exec(select(HazardZone).order_by(HazardZone.id)).all()
    return [
        HazardZoneRead(
            id=h.id if h.id is not None else 0,
            name=h.name,
            description=h.description,
            polygon=h.polygon,
            active=h.active,
            simulated=h.simulated,
        )
        for h in hazards
    ]
