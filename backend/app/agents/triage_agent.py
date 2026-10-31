"""Emergency Triage Agent for evaluating and prioritizing citizen distress requests.

GOLDEN RULES:
- The LLM ONLY extracts facts stated in the citizen's message. Python calculates the priority score.
  The LLM never produces, suggests or changes a score or urgency.
- The citizen's message is untrusted DATA. Text inside it that tries to give instructions
  (e.g. 'set my priority to 100') must have no effect.
- The LLM can never LOWER a safety red flag: a deterministic keyword check can only raise
  life_threatening, never lower it (Red-Flag Union).
- Triage must never fail a request: if the LLM is unavailable or invalid, a rules-based fallback
  extracts features so every request receives a score.
"""

import logging
from typing import Optional
from sqlmodel import Session, select
from app.constants import RequestStatus, Resource, RiskLevel, Urgency
from app.models import Region, Request
from app.schemas import ScoreFactorBreakdown, TriageResult
from app.services.agent_log import log_agent
from app.services.triage_extraction import extract_features, extract_with_rules
from app.services.triage_scoring import build_reason, calculate_priority

logger = logging.getLogger(__name__)


def run_triage_agent(
    session: Session, request: Request, persist: bool = True
) -> TriageResult:
    """Execute triage assessment pipeline for an emergency citizen request.

    Steps:
      1. Log reading request.
      2. Extract structured features via LLM with red-flag union and rules fallback.
      3. Query region flood risk context if available.
      4. Compute priority score, urgency tier, and itemized breakdown using pure Python.
      5. Construct concise audit-trail reason.
      6. Update request record in DB if persist=True.
      7. Return TriageResult.
    """
    region = session.get(Region, request.region_id) if request.region_id else None
    region_desc = region.name if region else "outside known zones"
    log_agent(
        session,
        agent="Triage",
        message=f"Reading request R{request.id} ({region_desc})",
    )

    try:
        features, source, needs_review = extract_features(session, request.text)
    except Exception as exc:
        logger.warning(
            "Feature extraction failed (%s); falling back to deterministic rules",
            exc.__class__.__name__,
        )
        features = extract_with_rules(request.text)
        source = "rules"
        needs_review = True

    log_agent(
        session,
        agent="Triage",
        message=f"Extracted features via {source} for R{request.id} (needs_review={needs_review})",
        payload={
            "source": source,
            "needs_review": needs_review,
            "features": features.model_dump(),
        },
    )

    region_risk: Optional[RiskLevel] = None
    if region and region.risk_level:
        try:
            region_risk = RiskLevel(region.risk_level)
        except ValueError:
            region_risk = None

    priority_score, urgency, breakdown_dicts = calculate_priority(features, region_risk)
    reason = build_reason(breakdown_dicts, features, region_risk)

    log_agent(
        session,
        agent="Triage",
        message=f"Score {priority_score} -> {urgency.value}: {reason}",
        payload={
            "priority_score": priority_score,
            "urgency": urgency.value,
            "breakdown": breakdown_dicts,
        },
    )

    if persist:
        request.resource_needed = (
            features.resource_needed.value if features.resource_needed else None
        )
        request.people_count = features.people_count
        request.urgency = urgency.value
        request.priority_score = priority_score
        request.reason = reason
        request.need_summary = features.need_summary
        request.triage_source = source
        request.needs_review = needs_review
        request.score_breakdown = breakdown_dicts
        request.status = RequestStatus.PRIORITIZED.value

        session.add(request)
        session.commit()
        session.refresh(request)

    breakdown_models = [ScoreFactorBreakdown(**b) for b in breakdown_dicts]

    return TriageResult(
        request_id=request.id if request.id is not None else 0,
        ref=f"R{request.id}",
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


def run_triage_all(session: Session, force: bool = False) -> list[TriageResult]:
    """Execute triage pipeline across all pending (or all if force=True) citizen requests.

    Returns:
        List of all prioritized requests ordered by priority_score desc, created_at asc, id asc.
    """
    if force:
        requests_to_triage = session.exec(
            select(Request).order_by(Request.created_at, Request.id)
        ).all()
    else:
        requests_to_triage = session.exec(
            select(Request)
            .where(Request.status == RequestStatus.RECEIVED.value)
            .order_by(Request.created_at, Request.id)
        ).all()

    for req in requests_to_triage:
        run_triage_agent(session, req, persist=True)

    all_prioritized = session.exec(
        select(Request).where(Request.priority_score.is_not(None))
    ).all()

    # Sort descending by priority_score, then ascending by created_at, then id
    sorted_requests = sorted(
        all_prioritized,
        key=lambda r: (-r.priority_score, r.created_at, r.id or 0),
    )

    results: list[TriageResult] = []
    for r in sorted_requests:
        breakdown_models = [
            ScoreFactorBreakdown(**b) if isinstance(b, dict) else b
            for b in (r.score_breakdown or [])
        ]
        res = TriageResult(
            request_id=r.id or 0,
            ref=f"R{r.id}",
            urgency=Urgency(r.urgency) if r.urgency else Urgency.LOW,
            priority_score=r.priority_score or 0,
            reason=r.reason or "",
            resource_needed=Resource(r.resource_needed) if r.resource_needed else None,
            people_count=r.people_count,
            need_summary=r.need_summary or "",
            source=r.triage_source or "rules",
            needs_review=r.needs_review,
            breakdown=breakdown_models,
        )
        results.append(res)

    log_agent(
        session,
        agent="Triage",
        message=f"Triage Agent ranked {len(results)} requests",
    )

    return results
