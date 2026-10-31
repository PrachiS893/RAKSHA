"""Shared citizen emergency request intake service.

Provides reusable request persistence with automated geographical region detection.
"""

from typing import Optional
from shapely.geometry import Point, shape
from sqlmodel import Session, select
from app.constants import RequestStatus
from app.models import Region, Request


def create_request(
    session: Session,
    text: str,
    lat: float,
    lon: float,
    name: Optional[str] = None,
) -> Request:
    """Create and persist a new emergency relief request with automated region detection.

    Determines regional flood zone using Shapely point-in-polygon check.
    AI fields remain null until triage is executed.
    """
    regions = session.exec(select(Region)).all()
    target_region_id: Optional[int] = None

    # Point uses (longitude, latitude) matching GeoJSON [lon, lat] coordinate format
    request_point = Point(lon, lat)

    for region in regions:
        region_shape = shape(region.polygon)
        if region_shape.covers(request_point) or region_shape.contains(request_point):
            target_region_id = region.id
            break

    db_request = Request(
        text=text,
        name=name,
        lat=lat,
        lon=lon,
        region_id=target_region_id,
        status=RequestStatus.RECEIVED.value,
        resource_needed=None,
        people_count=None,
        urgency=None,
        priority_score=None,
        reason=None,
    )

    # TODO (Step B8): Call Triage Agent here to analyze text and set:
    # resource_needed, people_count, urgency, priority_score, and reason.

    session.add(db_request)
    session.commit()
    session.refresh(db_request)
    return db_request
