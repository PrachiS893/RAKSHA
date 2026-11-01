"""Development-only endpoints for manual testing, agent runs, and log verification."""

from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
import httpx
from pydantic import BaseModel
from sqlmodel import Session, select
from app.agents.risk_agent import run_risk_agent
from app.config import settings
from app.db import get_session
from app.models import AgentLog, Region
from app.routers.alerts import _to_alert_read
from app.schemas import (
    AgentLogRead,
    AlertRead,
    RiskReport,
    ScoreFactorBreakdown,
    TriageFeatures,
    TriagePreviewRequest,
    TriagePreviewResponse,
    TriageResult,
    format_iso_utc,
)
from app.services.llm import generate_json
from app.services.notification import handle_risk_reports
from app.services.triage_extraction import extract_features, extract_with_rules
from app.services.triage_scoring import build_reason, calculate_priority

router = APIRouter(prefix="/dev", tags=["Dev (not for frontend)"])


class TelegramTestResponse(BaseModel):
    """Response schema for Telegram test send operation."""

    ok: bool
    detail: str


class LLMTestResponse(BaseModel):
    """Response schema for LLM test execution."""

    ok: bool
    model: str
    detail: str


class TinyAnswerSchema(BaseModel):
    """Minimal schema for validating LLM structured output connectivity."""

    answer: str


@router.post(
    "/risk-check/{region_id}",
    response_model=RiskReport,
    summary="Trigger the Risk Agent for a specific region (dev only)",
)
def dev_risk_check(
    region_id: int,
    rainfall_mm: Optional[float] = Query(default=None),
    persist: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> RiskReport:
    """Manually invoke the Risk Agent on a region with optional rainfall override."""
    region = session.get(Region, region_id)
    if not region:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Region with id {region_id} not found",
        )

    return run_risk_agent(
        session=session,
        region=region,
        override_rainfall_mm=rainfall_mm,
        persist=persist,
    )


@router.post(
    "/draft-alert/{region_id}",
    response_model=list[AlertRead],
    summary="Run Risk Agent and generate draft/auto alerts for a region (dev only)",
)
def dev_draft_alert(
    region_id: int,
    rainfall_mm: Optional[float] = Query(default=None),
    session: Session = Depends(get_session),
) -> list[AlertRead]:
    """Execute Risk Agent on region with persist=True, process via Notification Service, and return created alerts."""
    region = session.get(Region, region_id)
    if not region:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Region with id {region_id} not found",
        )

    report = run_risk_agent(
        session=session,
        region=region,
        override_rainfall_mm=rainfall_mm,
        persist=True,
    )
    created_alerts = handle_risk_reports(session, [report])

    regions = session.exec(select(Region)).all()
    region_map: dict[int, str] = {r.id: r.name for r in regions if r.id is not None}

    return [
        _to_alert_read(
            session=session,
            alert=a,
            region_name=region_map.get(a.region_id, "Unknown Region"),
            include_deliveries=True,
        )
        for a in created_alerts
    ]


@router.post(
    "/telegram-test",
    response_model=TelegramTestResponse,
    summary="Send a test message to Telegram without exposing credentials (dev only)",
)
def dev_telegram_test(
    chat_id: str = Query(..., description="Target Telegram chat ID"),
) -> TelegramTestResponse:
    """Send a demo test message via Telegram Bot API with safe error handling."""
    token = settings.TELEGRAM_BOT_TOKEN.strip() if settings.TELEGRAM_BOT_TOKEN else ""
    if not token:
        return TelegramTestResponse(ok=False, detail="no bot token configured")

    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": "[DEMO] Raksha test message",
                },
            )
            if resp.is_success:
                return TelegramTestResponse(ok=True, detail="delivered")
            return TelegramTestResponse(ok=False, detail=f"HTTP {resp.status_code}")
    except Exception as exc:
        return TelegramTestResponse(ok=False, detail=exc.__class__.__name__)


@router.post(
    "/llm-test",
    response_model=LLMTestResponse,
    summary="Test LLM structured output connectivity via Groq (dev only)",
)
def dev_llm_test() -> LLMTestResponse:
    """Invoke generate_json with a minimal schema to test Groq connectivity safely."""
    if not settings.LLM_ENABLED:
        return LLMTestResponse(
            ok=False,
            model=settings.LLM_MODEL,
            detail="LLM_ENABLED is false",
        )
    if not settings.LLM_API_KEY or not settings.LLM_API_KEY.strip():
        return LLMTestResponse(
            ok=False,
            model=settings.LLM_MODEL,
            detail="no LLM_API_KEY configured",
        )

    result = generate_json(
        prompt="Reply with the word ok",
        schema=TinyAnswerSchema,
    )
    if result is not None:
        return LLMTestResponse(
            ok=True,
            model=settings.LLM_MODEL,
            detail=f"received valid response: {result.answer}",
        )
    return LLMTestResponse(
        ok=False,
        model=settings.LLM_MODEL,
        detail="generate_json returned None (call failed or validation error)",
    )


@router.get(
    "/agent-logs",
    response_model=list[AgentLogRead],
    summary="Inspect recent agent audit logs, newest first (dev only)",
)
def get_agent_logs(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[AgentLogRead]:
    """Retrieve recent multi-agent system execution logs."""
    logs = session.exec(
        select(AgentLog).order_by(AgentLog.created_at.desc()).limit(limit)
    ).all()

    return [
        AgentLogRead(
            id=log.id,
            agent=log.agent,
            message=log.message,
            payload=log.payload,
            created_at=format_iso_utc(log.created_at),
        )
        for log in logs
    ]


@router.post(
    "/triage-preview",
    response_model=TriagePreviewResponse,
    summary="Preview triage extraction and scoring without persisting to database (dev only)",
)
def dev_triage_preview(
    payload: TriagePreviewRequest,
    session: Session = Depends(get_session),
) -> TriagePreviewResponse:
    """Extract structured features and calculate deterministic priority without modifying database state."""
    from app.constants import RiskLevel
    from app.schemas import ScoreFactorBreakdown, TriageResult

    try:
        features, source, needs_review = extract_features(session, payload.text)
    except Exception:
        features = extract_with_rules(payload.text)
        source = "rules"
        needs_review = True

    region_risk: Optional[RiskLevel] = None
    if payload.region_id is not None:
        region = session.get(Region, payload.region_id)
        if region and region.risk_level:
            try:
                region_risk = RiskLevel(region.risk_level)
            except ValueError:
                region_risk = None

    priority_score, urgency, breakdown_dicts = calculate_priority(features, region_risk)
    reason = build_reason(breakdown_dicts, features, region_risk)
    breakdown_models = [ScoreFactorBreakdown(**b) for b in breakdown_dicts]

    result = TriageResult(
        request_id=0,
        ref="R0",
        urgency=urgency,
        priority_score=priority_score,
        reason=reason,
        resource_needed=features.resource_needed,
        people_count=features.people_count,
        need_summary=features.need_summary,
        source=source,
        needs_review=needs_review,
        breakdown=breakdown_models,
    )
    return TriagePreviewResponse(result=result, features=features)


@router.post(
    "/route-test",
    summary="Test route calculation without persisting (dev only)",
)
def dev_route_test(
    warehouse_id: int = Query(...),
    lat: float = Query(...),
    lon: float = Query(...),
    use_hazards: bool = Query(default=True),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Calculate and return a test route between a warehouse and destination coordinates without storing."""
    from app.models import HazardZone, Warehouse
    from app.services.routing import get_route

    wh = session.get(Warehouse, warehouse_id)
    if not wh:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Warehouse with id {warehouse_id} not found",
        )

    hazards = session.exec(select(HazardZone)).all()
    route = get_route(
        origin=(wh.lat, wh.lon),
        destination=(lat, lon),
        hazards=hazards,
        use_hazards=use_hazards,
    )
    return route


@router.post(
    "/hazards/activate",
    summary="Bulk activate or deactivate all hazard zones (dev only)",
)
def dev_hazards_activate(
    active: bool = Query(...),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Toggle all simulated hazard zones active or inactive for testing."""
    from app.models import HazardZone

    hazards = session.exec(select(HazardZone)).all()
    for h in hazards:
        h.active = active
        session.add(h)
    session.commit()
    return {"updated": len(hazards), "active": active}
