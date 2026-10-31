"""Delivery service dispatching disaster alerts across in-app, Telegram, and simulated SMS."""

from datetime import datetime, timezone
import logging
from typing import Optional
import httpx
from sqlmodel import Session
from app.config import settings
from app.constants import AlertLevel, Channel
from app.models import Alert, Delivery, Subscription
from app.services.alert_rules import LEVEL_LABELS

logger = logging.getLogger(__name__)


def _get_level_label(level: str) -> str:
    """Get presentation label for alert level string."""
    try:
        return LEVEL_LABELS[AlertLevel(level)]
    except (ValueError, KeyError):
        return level


def deliver_in_app(session: Session, alert: Alert) -> list[Delivery]:
    """Record an in-app alert delivery."""
    now = datetime.now(timezone.utc)
    delivery = Delivery(
        alert_id=alert.id,
        channel=Channel.IN_APP.value,
        status="sent",
        recipient=None,
        detail=None,
        sent_at=now,
    )
    session.add(delivery)
    session.commit()
    session.refresh(delivery)
    return [delivery]


def deliver_telegram(
    session: Session, alert: Alert, subscriptions: list[Subscription]
) -> list[Delivery]:
    """Send alert via Telegram Bot API to subscribed citizens.

    SECURITY NOTE:
    The bot token is inside the request URL. Never log or store the URL, the token,
    or raw exception strings containing secrets. On failure, store only HTTP status
    codes or exception class names. Never raises exceptions.
    """
    token = settings.TELEGRAM_BOT_TOKEN.strip() if settings.TELEGRAM_BOT_TOKEN else ""
    if not token:
        delivery = Delivery(
            alert_id=alert.id,
            channel=Channel.TELEGRAM.value,
            status="skipped",
            recipient=None,
            detail="no bot token configured",
            sent_at=None,
        )
        session.add(delivery)
        session.commit()
        session.refresh(delivery)
        return [delivery]

    linked_subs = [
        s for s in subscriptions if s.telegram_chat_id and s.telegram_chat_id.strip()
    ]
    if not linked_subs:
        delivery = Delivery(
            alert_id=alert.id,
            channel=Channel.TELEGRAM.value,
            status="skipped",
            recipient=None,
            detail="no linked subscribers",
            sent_at=None,
        )
        session.add(delivery)
        session.commit()
        session.refresh(delivery)
        return [delivery]

    message_text = f"[DEMO - simulated scenario] {alert.message}"
    deliveries: list[Delivery] = []

    # Safe API endpoint - token is kept isolated
    telegram_url = f"https://api.telegram.org/bot{token}/sendMessage"

    for sub in linked_subs:
        status = "failed"
        detail: Optional[str] = None
        sent_at: Optional[datetime] = None

        try:
            with httpx.Client(timeout=8.0) as client:
                response = client.post(
                    telegram_url,
                    json={
                        "chat_id": sub.telegram_chat_id,
                        "text": message_text,
                    },
                )
                if response.is_success:
                    status = "sent"
                    sent_at = datetime.now(timezone.utc)
                else:
                    status = "failed"
                    detail = f"HTTP {response.status_code}"
        except Exception as exc:
            status = "failed"
            # Store only exception class name - never raw str(exc) which could contain URL/token
            detail = exc.__class__.__name__

        deliv = Delivery(
            alert_id=alert.id,
            channel=Channel.TELEGRAM.value,
            status=status,
            recipient=sub.name,
            detail=detail,
            sent_at=sent_at,
        )
        session.add(deliv)
        deliveries.append(deliv)

    session.commit()
    for d in deliveries:
        session.refresh(d)

    return deliveries


def deliver_sms_sim(
    session: Session, alert: Alert, subscriptions: list[Subscription]
) -> list[Delivery]:
    """Record simulated SMS notifications for each subscriber in the region."""
    deliveries: list[Delivery] = []
    for sub in subscriptions:
        deliv = Delivery(
            alert_id=alert.id,
            channel=Channel.SMS_SIM.value,
            status="simulated",
            recipient=sub.name,
            detail=None,
            sent_at=None,
        )
        session.add(deliv)
        deliveries.append(deliv)

    session.commit()
    for d in deliveries:
        session.refresh(d)

    return deliveries
