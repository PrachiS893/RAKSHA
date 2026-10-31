"""Unit tests for alert mapping rules, coordinator approval checks, and severity ranking."""

from app.constants import AlertLevel, RiskLevel
from app.services.alert_rules import (
    LEVEL_LABELS,
    alert_level_for,
    alert_level_rank,
    requires_approval,
)


def test_alert_level_mapping_for_all_risk_levels() -> None:
    """Verify that all 4 risk levels map to expected alert levels (LOW produces None)."""
    assert alert_level_for(RiskLevel.LOW) is None
    assert alert_level_for("LOW") is None

    assert alert_level_for(RiskLevel.MODERATE) == AlertLevel.ADVISORY
    assert alert_level_for("MODERATE") == AlertLevel.ADVISORY

    assert alert_level_for(RiskLevel.HIGH) == AlertLevel.WARNING
    assert alert_level_for("HIGH") == AlertLevel.WARNING

    assert alert_level_for(RiskLevel.SEVERE) == AlertLevel.URGENT
    assert alert_level_for("SEVERE") == AlertLevel.URGENT


def test_requires_approval_flags() -> None:
    """Verify approval logic: MODERATE is automated, HIGH and SEVERE require coordinator review."""
    assert requires_approval(AlertLevel.ADVISORY) is False
    assert requires_approval("ADVISORY") is False

    assert requires_approval(AlertLevel.WARNING) is True
    assert requires_approval("WARNING") is True

    assert requires_approval(AlertLevel.URGENT) is True
    assert requires_approval("URGENT") is True


def test_alert_level_ranks_and_labels() -> None:
    """Verify severity rank ordering (ADVISORY < WARNING < URGENT) and presentation labels."""
    adv_rank = alert_level_rank(AlertLevel.ADVISORY)
    warn_rank = alert_level_rank(AlertLevel.WARNING)
    urg_rank = alert_level_rank(AlertLevel.URGENT)

    assert adv_rank < warn_rank < urg_rank

    assert LEVEL_LABELS[AlertLevel.ADVISORY] == "Advisory"
    assert LEVEL_LABELS[AlertLevel.WARNING] == "Warning"
    assert LEVEL_LABELS[AlertLevel.URGENT] == "Urgent warning"
