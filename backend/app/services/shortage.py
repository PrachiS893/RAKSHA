"""Shortage prediction service for disaster relief supply planning.

GOLDEN RULE:
Shortage numbers are demo planning assumptions, not real forecasts.
Label them as such everywhere.
"""

from datetime import datetime, timezone
import math
from typing import Any
from sqlmodel import Session, select
from app.constants import Resource, RiskLevel
from app.models import Inventory, Region
from app.schemas import format_iso_utc

# Share of households expected to need aid based on regional flood risk level
AFFECTED_FRACTION: dict[str, float] = {
    RiskLevel.LOW.value: 0.0,
    RiskLevel.MODERATE.value: 0.02,
    RiskLevel.HIGH.value: 0.08,
    RiskLevel.SEVERE.value: 0.20,
}

# Average supply units required per affected household
PER_AFFECTED_HOUSEHOLD: dict[str, float] = {
    Resource.DRINKING_WATER.value: 10.0,  # litres
    Resource.FOOD_PACKET.value: 3.0,  # packets
    Resource.MEDICAL_KIT.value: 0.05,  # kits
    Resource.RESCUE_BOAT.value: 0.04,  # boats
}

# Unit labels per resource type
RESOURCE_UNITS: dict[str, str] = {
    Resource.DRINKING_WATER.value: "litres",
    Resource.FOOD_PACKET.value: "packets",
    Resource.MEDICAL_KIT.value: "kits",
    Resource.RESCUE_BOAT.value: "boats",
}

# All four resources in standardized order
RESOURCE_ORDER: list[str] = [
    Resource.DRINKING_WATER.value,
    Resource.FOOD_PACKET.value,
    Resource.MEDICAL_KIT.value,
    Resource.RESCUE_BOAT.value,
]

# Stock adequacy buffer threshold
TIGHT_MARGIN: float = 1.25


def predict_shortages(session: Session) -> dict[str, Any]:
    """Calculate predicted regional supply demand, current stockpile adequacy, and shortfalls.

    Uses current region risk levels and warehouse inventories.
    Returns structured dictionary matching ShortagesResponse schema.
    """
    regions = session.exec(select(Region).order_by(Region.id)).all()
    inventory_items = session.exec(select(Inventory)).all()

    # Pre-aggregate stock by resource
    stock_by_resource: dict[str, int] = {res: 0 for res in RESOURCE_ORDER}
    for item in inventory_items:
        if item.resource in stock_by_resource:
            stock_by_resource[item.resource] += item.quantity

    resources_data: list[dict[str, Any]] = []

    for res in RESOURCE_ORDER:
        unit = RESOURCE_UNITS[res]
        stock = stock_by_resource[res]
        per_hh = PER_AFFECTED_HOUSEHOLD[res]

        by_region: list[dict[str, Any]] = []
        unrounded_total_demand = 0.0

        for r in regions:
            fraction = AFFECTED_FRACTION.get(r.risk_level, 0.0)
            reg_demand = r.households_estimate * fraction * per_hh
            unrounded_total_demand += reg_demand
            by_region.append({
                "region_id": r.id if r.id is not None else 0,
                "region": r.name,
                "demand": round(reg_demand, 1),
            })

        predicted_demand = math.ceil(unrounded_total_demand)
        shortfall = max(0, predicted_demand - stock)

        if predicted_demand == 0:
            status = "OK"
        elif stock < predicted_demand:
            status = "SHORTAGE"
        elif stock < predicted_demand * TIGHT_MARGIN:
            status = "TIGHT"
        else:
            status = "OK"

        resources_data.append({
            "resource": res,
            "unit": unit,
            "stock": stock,
            "predicted_demand": predicted_demand,
            "shortfall": shortfall,
            "status": status,
            "by_region": by_region,
        })

    now = datetime.now(timezone.utc)
    return {
        "as_of": format_iso_utc(now),
        "simulated": True,
        "assumptions": (
            "Illustrative planning assumptions for the demo, not a real forecast."
        ),
        "resources": resources_data,
    }
