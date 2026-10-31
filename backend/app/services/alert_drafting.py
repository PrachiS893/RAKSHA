"""Disaster alert message drafting service combining LLM phrasing with strict validation and templates."""

import math
import re
from typing import Any, Optional
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from app.constants import AlertLevel
from app.models import Region, Warehouse
from app.services.alert_rules import LEVEL_LABELS
from app.services.llm import generate_json

ALERT_TEMPLATES: dict[AlertLevel, str] = {
    AlertLevel.ADVISORY: (
        "Advisory for {region}: heavy rain is expected (about {mm} mm in the next day). "
        "Stay alert, avoid low-lying areas and keep phones charged. "
        "Nearest relief point: {warehouse}, about {km} km away."
    ),
    AlertLevel.WARNING: (
        "Flood warning for {region}: heavy rainfall (about {mm} mm) may cause flooding. "
        "Move valuables and documents to higher ground, keep drinking water and medicines ready, "
        "and avoid flooded roads. Nearest relief point: {warehouse}, about {km} km away."
    ),
    AlertLevel.URGENT: (
        "URGENT flood warning for {region}: severe flooding is likely (about {mm} mm of rain). "
        "Move to higher ground now, stay away from flooded roads and electrical lines, "
        "and help children and elderly neighbours. Nearest relief point: {warehouse}, about {km} km away."
    ),
}

APPROVED_SAFETY_STEPS: dict[AlertLevel, list[str]] = {
    AlertLevel.ADVISORY: [
        "stay alert for updates",
        "avoid low-lying areas",
        "keep phones charged",
    ],
    AlertLevel.WARNING: [
        "move valuables and documents to higher ground",
        "keep drinking water and medicines ready",
        "avoid flooded roads",
    ],
    AlertLevel.URGENT: [
        "move to higher ground now",
        "stay away from flooded roads and electrical lines",
        "help children and elderly neighbours",
    ],
}

STAY_IN_PLACE_PHRASES: list[str] = [
    "stay indoors",
    "stay inside",
    "stay home",
    "shelter in place",
    "do not evacuate",
]

UNVERIFIED_PROMISES: list[str] = [
    "help is on the way",
    "rescue is coming",
]


class AlertDraft(BaseModel):
    """Pydantic schema requested from the LLM for drafting public alert text."""

    message: str = Field(description="Short public safety message for citizens")


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance between two points on the earth in kilometers."""
    radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


def nearest_warehouse(session: Session, region: Region) -> tuple[Warehouse, float]:
    """Find the nearest warehouse to a region's center using haversine distance.

    Returns:
        tuple of (nearest Warehouse model, distance in km)
    """
    warehouses = session.exec(select(Warehouse)).all()
    if not warehouses:
        raise ValueError("No warehouses registered in database")

    closest_warehouse = warehouses[0]
    min_distance = haversine_distance_km(
        region.center_lat, region.center_lon, closest_warehouse.lat, closest_warehouse.lon
    )

    for w in warehouses[1:]:
        dist = haversine_distance_km(region.center_lat, region.center_lon, w.lat, w.lon)
        if dist < min_distance:
            min_distance = dist
            closest_warehouse = w

    return closest_warehouse, min_distance


def build_facts(
    region: Region,
    risk_report_or_values: Any,
    alert_level: AlertLevel,
    warehouse: Warehouse,
    distance_km: float,
) -> dict[str, Any]:
    """Construct minimal factual dictionary strictly allowed for alert drafting."""
    if hasattr(risk_report_or_values, "rainfall_mm"):
        rain = risk_report_or_values.rainfall_mm
    elif isinstance(risk_report_or_values, dict):
        rain = risk_report_or_values.get("rainfall_mm", 0.0)
    else:
        rain = float(risk_report_or_values)

    return {
        "region": region.name,
        "alert_level": alert_level,
        "alert_level_label": LEVEL_LABELS[alert_level],
        "rainfall_mm": round(float(rain)),
        "nearest_warehouse": warehouse.name,
        "distance_km": round(float(distance_km), 1),
    }


def validate_drafted_message(
    message: Optional[str],
    facts: dict[str, Any],
    alert_level: Optional[AlertLevel] = None,
) -> bool:
    """Validate that drafted text complies with length, region mention, number restrictions, and safety guidance."""
    if not message or not isinstance(message, str):
        return False

    cleaned = message.strip()
    if not cleaned or len(cleaned) > 320:
        return False

    msg_lower = cleaned.lower()

    # Resolve alert level
    if alert_level is None:
        lvl_val = facts.get("alert_level")
        if isinstance(lvl_val, AlertLevel):
            alert_level = lvl_val
        elif isinstance(lvl_val, str):
            try:
                alert_level = AlertLevel(lvl_val)
            except ValueError:
                pass
        if alert_level is None:
            label = str(facts.get("alert_level_label", "")).lower()
            for lvl, lbl in LEVEL_LABELS.items():
                if lbl.lower() == label:
                    alert_level = lvl
                    break

    # Check region name (full name OR part before " - ")
    full_region = facts["region"]
    short_region = full_region.split(" - ")[0].strip()
    if (full_region.lower() not in msg_lower) and (short_region.lower() not in msg_lower):
        return False

    # Numbers allowed: rainfall integer, distance with 1 decimal, distance rounded, distance int
    rainfall_int = str(int(facts["rainfall_mm"]))
    dist_val = float(facts["distance_km"])
    dist_1dec = f"{dist_val:.1f}"
    dist_round = str(round(dist_val))
    dist_int = str(int(dist_val))
    allowed_numbers = {rainfall_int, dist_1dec, dist_round, dist_int}

    found_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", cleaned)
    for num in found_numbers:
        if num not in allowed_numbers:
            return False

    # For WARNING and URGENT, reject any message telling people to stay in place
    if alert_level in (AlertLevel.WARNING, AlertLevel.URGENT):
        for phrase in STAY_IN_PLACE_PHRASES:
            if phrase in msg_lower:
                return False

    # For URGENT, message must contain "higher ground"
    if alert_level == AlertLevel.URGENT:
        if "higher ground" not in msg_lower:
            return False

    # Reject a message containing "evacuate" unless facts include an evacuation instruction (they do not)
    has_evacuation_instruction = bool(facts.get("evacuation_instruction", False))
    if "evacuate" in msg_lower and not has_evacuation_instruction:
        return False

    # Reject unverified promises
    for promise in UNVERIFIED_PROMISES:
        if promise in msg_lower:
            return False

    return True


def draft_alert_message(
    session: Session, facts: dict[str, Any], alert_level: AlertLevel
) -> tuple[str, bool]:
    """Draft an alert message using LLM phrasing with template fallback.

    Returns:
        tuple of (final message string, used_llm: bool)
    """
    approved_steps = APPROVED_SAFETY_STEPS.get(alert_level, [])
    steps_text = "\n".join(f"- {s}" for s in approved_steps)

    prompt = (
        f"Verified Facts:\n"
        f"- Region: {facts['region']}\n"
        f"- Alert Level: {facts['alert_level_label']}\n"
        f"- Forecast Rainfall: {facts['rainfall_mm']} mm\n"
        f"- Nearest Relief Depot: {facts['nearest_warehouse']} ({facts['distance_km']} km away)\n\n"
        f"Approved Safety Steps (use ONLY these steps; rephrasing wording is allowed, but do not add any other advice):\n"
        f"{steps_text}\n\n"
        "Draft a public alert message adhering strictly to the constraints."
    )

    system_instruction = (
        "Write a short plain-language public safety message for citizens. "
        "Use ONLY the facts given. Do not invent places, numbers, times or phone numbers. "
        "Do not use any number except the rainfall mm and the distance in km given. "
        "Use ONLY the approved safety steps provided for this alert level; do not add any other advice. "
        "Mention the region and the nearest relief point. "
        "Maximum 300 characters. Never claim to be an official government forecast."
    )

    llm_output = generate_json(prompt=prompt, schema=AlertDraft, system=system_instruction)

    if llm_output and validate_drafted_message(llm_output.message, facts, alert_level):
        return llm_output.message.strip(), True

    # Fallback to deterministic template
    template = ALERT_TEMPLATES[alert_level]
    fallback_message = template.format(
        region=facts["region"],
        mm=facts["rainfall_mm"],
        warehouse=facts["nearest_warehouse"],
        km=facts["distance_km"],
    )
    return fallback_message, False
