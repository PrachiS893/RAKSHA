"""Risk Assessment Agent for evaluating regional flood hazards and recommending actions.

GOLDEN RULE:
The LLM only writes explanatory text. The risk level ALWAYS comes from the
pure Python function `calculate_risk`. The LLM never decides, changes, or
overrides a risk level or number.
"""

from datetime import datetime, timezone
import logging
from typing import Optional
from sqlmodel import Session, select
from app.constants import RiskLevel
from app.models import Region
from app.schemas import RiskExplanation, RiskReport
from app.services.agent_log import log_agent
from app.services.llm import generate_json
from app.services.risk import calculate_risk, risk_score_details
from app.services.weather import get_rainfall_forecast

logger = logging.getLogger(__name__)

# Template fallback actions based strictly on calculate_risk result
TEMPLATE_ACTIONS: dict[RiskLevel, str] = {
    RiskLevel.LOW: "No action needed; keep monitoring.",
    RiskLevel.MODERATE: "Issue an advisory and keep monitoring.",
    RiskLevel.HIGH: "Prepare emergency supplies and draft a warning.",
    RiskLevel.SEVERE: "Prepare supplies, stage rescue boats and draft an urgent warning.",
}


def run_risk_agent(
    session: Session,
    region: Region,
    override_rainfall_mm: Optional[float] = None,
    persist: bool = True,
) -> RiskReport:
    """Execute risk assessment pipeline for a specific region.

    Steps:
      1. Log check and fetch 24h rainfall forecast.
      2. Log rainfall value and source.
      3. Compute risk level using pure calculate_risk function and log details.
      4. Query LLM for concise reason and action strictly grounded on verified facts.
      5. Fallback to template text if LLM output unavailable or invalid.
      6. Update region risk_level and rainfall_mm in DB if persist=True.
      7. Return RiskReport.
    """
    # 1. Log checking rainfall forecast
    log_agent(session, agent="Risk", message=f"Checking rainfall forecast for {region.name}")
    forecast = get_rainfall_forecast(
        lat=region.center_lat,
        lon=region.center_lon,
        override_mm=override_rainfall_mm,
    )

    # 2. Log the rainfall value and source
    log_agent(
        session,
        agent="Risk",
        message=f"Forecast for {region.name}: {forecast.rainfall_mm_24h:.1f} mm (source: {forecast.source})",
        payload={"rainfall_mm": forecast.rainfall_mm_24h, "source": forecast.source},
    )

    # 3. Call calculate_risk and risk_score_details
    risk_level = calculate_risk(forecast.rainfall_mm_24h, region.vulnerability)
    details = risk_score_details(forecast.rainfall_mm_24h, region.vulnerability)

    log_agent(
        session,
        agent="Risk",
        message=f"Risk level {risk_level.value} (adjusted rainfall {details['adjusted_mm']} mm)",
        payload=details,
    )

    # 4. Ask the LLM (via generate_json) for ONLY {"reason": str, "action": str}
    prompt = (
        f"Region: {region.name}\n"
        f"Vulnerability: {region.vulnerability}\n"
        f"Forecast 24h Rainfall: {forecast.rainfall_mm_24h:.1f} mm\n"
        f"Rainfall Source: {forecast.source}\n"
        f"Calculated Risk Level: {risk_level.value}\n"
        "Provide a concise reason (max 30 words) and recommended action (max 20 words)."
    )
    system_instruction = (
        "You are an assistant for emergency flood coordinators. Write plain language based strictly "
        "on the verified facts provided. Do not invent numbers, places, or events. Do not change or restate "
        "a different risk level. The reason must be at most 30 words. The action must be at most 20 words."
    )

    explanation = generate_json(
        prompt=prompt,
        schema=RiskExplanation,
        system=system_instruction,
    )

    # 5. Handle LLM or Template Text
    if explanation is not None:
        reason = explanation.reason
        action = explanation.action
        log_agent(
            session,
            agent="Risk",
            message=f"Generated explanation using LLM for {region.name}",
        )
    else:
        reason = (
            f"Forecast rainfall of {forecast.rainfall_mm_24h:.0f} mm in the next 24 hours "
            f"({forecast.source}) on a zone with vulnerability {region.vulnerability}."
        )
        action = TEMPLATE_ACTIONS.get(
            risk_level, "No action needed; keep monitoring."
        )
        log_agent(
            session,
            agent="Risk",
            message=f"Generated explanation using template text for {region.name}",
        )

    # 6. If persist is True, update the region in DB
    if persist:
        region.risk_level = risk_level.value
        region.rainfall_mm = forecast.rainfall_mm_24h
        session.add(region)
        session.commit()
        session.refresh(region)

    now = datetime.now(timezone.utc)

    # 7. Return RiskReport
    # CRITICAL: risk_level MUST ALWAYS equal calculate_risk output!
    return RiskReport(
        region_id=region.id if region.id is not None else 0,
        region=region.name,
        risk_level=risk_level,
        rainfall_mm=forecast.rainfall_mm_24h,
        rainfall_source=forecast.source,
        reason=reason,
        action=action,
        generated_at=now,
        simulated=True,
    )


def run_risk_agent_all(
    session: Session,
    override_by_region: Optional[dict[int, float]] = None,
    persist: bool = True,
) -> list[RiskReport]:
    """Execute risk assessment pipeline across all registered geographical regions."""
    regions = session.exec(select(Region).order_by(Region.id)).all()
    reports: list[RiskReport] = []

    for r in regions:
        override = (
            override_by_region.get(r.id)
            if override_by_region and r.id is not None
            else None
        )
        report = run_risk_agent(
            session=session,
            region=r,
            override_rainfall_mm=override,
            persist=persist,
        )
        reports.append(report)

    return reports
