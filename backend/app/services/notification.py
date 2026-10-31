"""Notification service managing alert lifecycle, deduplication, approvals, and multi-channel dispatch."""

from datetime import datetime, timezone
import logging
from typing import Optional
from sqlmodel import Session, select
from app.constants import AlertStatus
from app.models import Alert, Region, Subscription
from app.schemas import RiskReport
from app.services.agent_log import log_agent
from app.services.alert_drafting import (
    build_facts,
    draft_alert_message,
    nearest_warehouse,
)
from app.services.alert_rules import (
    LEVEL_LABELS,
    alert_level_for,
    alert_level_rank,
    requires_approval,
)
from app.services.delivery import (
    deliver_in_app,
    deliver_sms_sim,
    deliver_telegram,
)

logger = logging.getLogger(__name__)


def create_alert_from_report(
    session: Session, region: Region, risk_report: RiskReport
) -> Optional[Alert]:
    """Evaluate a RiskReport and create/send an alert if thresholds are met.

    Deduplication rules:
      - Ignores if an active/pending alert with equal or higher severity already exists.
      - Supersedes lower-severity draft alerts.
    """
    level = alert_level_for(risk_report.risk_level)
    if level is None:
        return None

    new_rank = alert_level_rank(level)

    # Fetch existing alerts for this region
    existing_alerts = session.exec(
        select(Alert).where(Alert.region_id == region.id)
    ).all()

    # Deduplication & superseding check
    for existing in existing_alerts:
        existing_rank = alert_level_rank(existing.level)
        # If an equal or higher severity alert is draft, approved, or sent -> deduplicate
        if existing.status in (
            AlertStatus.DRAFT.value,
            AlertStatus.APPROVED.value,
            AlertStatus.SENT.value,
        ):
            if existing_rank >= new_rank:
                logger.info(
                    "Deduplicating alert for region %d: existing %s >= new %s",
                    region.id,
                    existing.level,
                    level.value,
                )
                return None
        # If a lower-level alert is in draft, supersede it
        if existing.status == AlertStatus.DRAFT.value and existing_rank < new_rank:
            existing.status = AlertStatus.SUPERSEDED.value
            session.add(existing)

    session.commit()

    # Find nearest warehouse and compile verified facts
    warehouse, distance_km = nearest_warehouse(session, region)
    facts = build_facts(region, risk_report, level, warehouse, distance_km)

    # Draft message
    message, used_llm = draft_alert_message(session, facts, level)

    # Create new draft alert
    alert = Alert(
        region_id=region.id,
        level=level.value,
        message=message,
        status=AlertStatus.DRAFT.value,
        approved_by=None,
        approved_at=None,
    )
    session.add(alert)
    session.commit()
    session.refresh(alert)

    label = LEVEL_LABELS.get(level, level.value)
    text_source = "LLM text" if used_llm else "template text"
    log_agent(
        session,
        agent="Notification",
        message=f"Drafted {label} for {region.name} ({text_source})",
        payload={"alert_id": alert.id, "level": alert.level, "used_llm": used_llm},
    )

    # Automated advisory vs coordinator approval requirement
    if not requires_approval(level):
        return send_alert(session, alert, approved_by="system (auto-advisory)")

    log_agent(
        session,
        agent="Notification",
        message="Awaiting coordinator approval",
        payload={"alert_id": alert.id, "region_id": region.id, "level": alert.level},
    )
    return alert


def send_alert(
    session: Session,
    alert: Alert,
    approved_by: str,
    edited_message: Optional[str] = None,
) -> Alert:
    """Approve and dispatch an alert across in-app, Telegram, and SMS channels."""
    if edited_message is not None:
        alert.message = edited_message.strip()

    alert.approved_by = approved_by
    alert.approved_at = datetime.now(timezone.utc)

    # Fetch subscribers
    subscriptions = session.exec(
        select(Subscription).where(Subscription.region_id == alert.region_id)
    ).all()

    # Execute deliveries
    in_app_deliveries = deliver_in_app(session, alert)
    tg_deliveries = deliver_telegram(session, alert, subscriptions)
    sms_deliveries = deliver_sms_sim(session, alert, subscriptions)

    alert.status = AlertStatus.SENT.value
    session.add(alert)
    session.commit()
    session.refresh(alert)

    # Summarize dispatch outcomes
    tg_sent = sum(1 for d in tg_deliveries if d.status == "sent")
    tg_skipped = sum(1 for d in tg_deliveries if d.status == "skipped")
    tg_failed = sum(1 for d in tg_deliveries if d.status == "failed")
    tg_summary = f"{tg_sent} sent, {tg_skipped} skipped, {tg_failed} failed"
    sms_count = len(sms_deliveries)

    log_agent(
        session,
        agent="Notification",
        message=(
            f"Dispatched {alert.level} alert for region {alert.region_id}: "
            f"in_app (1 sent), telegram ({tg_summary}), sms_sim ({sms_count} simulated)"
        ),
        payload={
            "alert_id": alert.id,
            "region_id": alert.region_id,
            "level": alert.level,
            "in_app": len(in_app_deliveries),
            "telegram_sent": tg_sent,
            "telegram_skipped": tg_skipped,
            "telegram_failed": tg_failed,
            "sms_simulated": sms_count,
        },
    )
    return alert


def handle_risk_reports(session: Session, reports: list[RiskReport]) -> list[Alert]:
    """Process multiple RiskReports and generate alerts where warranted."""
    created_alerts: list[Alert] = []
    for report in reports:
        region = session.get(Region, report.region_id)
        if region:
            alert = create_alert_from_report(session, region, report)
            if alert is not None:
                created_alerts.append(alert)
    return created_alerts
