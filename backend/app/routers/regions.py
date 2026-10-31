"""Router for geographical flood regions."""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from app.db import get_session
from app.models import Region
from app.schemas import Coordinates, RegionRead

router = APIRouter(prefix="/regions", tags=["Regions"])


@router.get(
    "",
    response_model=list[RegionRead],
    summary="List all monitored geographical regions with risk metrics and boundaries",
)
def list_regions(session: Session = Depends(get_session)) -> list[RegionRead]:
    """Retrieve all geographical flood zones and their current risk status."""
    regions = session.exec(select(Region)).all()
    return [
        RegionRead(
            id=r.id,
            name=r.name,
            polygon=r.polygon,
            center=Coordinates(lat=r.center_lat, lon=r.center_lon),
            vulnerability=r.vulnerability,
            risk_level=r.risk_level,
            rainfall_mm=r.rainfall_mm,
            is_flooded=r.is_flooded,
            is_simulated_flood=r.is_simulated_flood,
        )
        for r in regions
    ]
