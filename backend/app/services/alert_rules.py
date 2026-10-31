"""Pure deterministic rules for mapping risk levels to public disaster alert levels."""

from typing import Optional, Union
from app.constants import AlertLevel, RiskLevel

# Human-readable presentation labels for each alert severity level
LEVEL_LABELS: dict[AlertLevel, str] = {
    AlertLevel.ADVISORY: "Advisory",
    AlertLevel.WARNING: "Warning",
    AlertLevel.URGENT: "Urgent warning",
}

# Severity rank ordering (ADVISORY < WARNING < URGENT)
LEVEL_RANKS: dict[AlertLevel, int] = {
    AlertLevel.ADVISORY: 1,
    AlertLevel.WARNING: 2,
    AlertLevel.URGENT: 3,
}


def alert_level_for(risk_level: Union[RiskLevel, str]) -> Optional[AlertLevel]:
    """Map a region's assessed flood risk level to an alert level.

    LOW -> None (no alert issued)
    MODERATE -> ADVISORY
    HIGH -> WARNING
    SEVERE -> URGENT
    """
    if isinstance(risk_level, str):
        try:
            risk_level = RiskLevel(risk_level)
        except ValueError:
            return None

    if risk_level == RiskLevel.LOW:
        return None
    elif risk_level == RiskLevel.MODERATE:
        return AlertLevel.ADVISORY
    elif risk_level == RiskLevel.HIGH:
        return AlertLevel.WARNING
    elif risk_level == RiskLevel.SEVERE:
        return AlertLevel.URGENT
    return None


def requires_approval(alert_level: Union[AlertLevel, str]) -> bool:
    """Determine whether an alert level requires human coordinator approval.

    WARNING and URGENT require explicit human approval.
    ADVISORY is automated.
    """
    if isinstance(alert_level, str):
        try:
            alert_level = AlertLevel(alert_level)
        except ValueError:
            return True

    return alert_level in (AlertLevel.WARNING, AlertLevel.URGENT)


def alert_level_rank(level: Optional[Union[AlertLevel, str]]) -> int:
    """Return numeric severity rank for comparison (ADVISORY=1 < WARNING=2 < URGENT=3)."""
    if level is None:
        return 0
    if isinstance(level, str):
        try:
            level = AlertLevel(level)
        except ValueError:
            return 0
    return LEVEL_RANKS.get(level, 0)
