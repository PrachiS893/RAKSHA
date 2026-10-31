"""Unit tests for the pure deterministic risk calculation service."""

import pytest
from app.constants import RiskLevel
from app.services.risk import calculate_risk, risk_score_details


def test_calculate_risk_zero_mm_is_low() -> None:
    """Case 1: 0 mm rainfall always results in LOW risk regardless of vulnerability."""
    assert calculate_risk(0.0, 0.9) == RiskLevel.LOW
    assert calculate_risk(0.0, 0.3) == RiskLevel.LOW
    assert calculate_risk(0.0, 1.0) == RiskLevel.LOW


def test_calculate_risk_boundary_25() -> None:
    """Case 2: Threshold boundary at 25 mm adjusted rainfall (LOW vs MODERATE)."""
    # 24.9 * (0.5 + 0.5) = 24.9 mm -> LOW
    assert calculate_risk(24.9, 0.5) == RiskLevel.LOW
    # 25.0 * (0.5 + 0.5) = 25.0 mm -> exactly at boundary -> MODERATE
    assert calculate_risk(25.0, 0.5) == RiskLevel.MODERATE


def test_calculate_risk_boundary_65() -> None:
    """Case 3: Threshold boundary at 65 mm adjusted rainfall (MODERATE vs HIGH)."""
    # 64.9 * (0.5 + 0.5) = 64.9 mm -> MODERATE
    assert calculate_risk(64.9, 0.5) == RiskLevel.MODERATE
    # 65.0 * (0.5 + 0.5) = 65.0 mm -> exactly at boundary -> HIGH
    assert calculate_risk(65.0, 0.5) == RiskLevel.HIGH


def test_calculate_risk_boundary_115() -> None:
    """Case 4: Threshold boundary at 115 mm adjusted rainfall (HIGH vs SEVERE)."""
    # 114.9 * (0.5 + 0.5) = 114.9 mm -> HIGH
    assert calculate_risk(114.9, 0.5) == RiskLevel.HIGH
    # 115.0 * (0.5 + 0.5) = 115.0 mm -> exactly at boundary -> SEVERE
    assert calculate_risk(115.0, 0.5) == RiskLevel.SEVERE


def test_calculate_risk_vulnerability_ordering() -> None:
    """Case 5: Same rainfall produces higher or equal risk for higher vulnerability."""
    rainfall = 50.0
    # vulnerability 0.9: 50 * 1.4 = 70 mm -> HIGH
    high_vuln_risk = calculate_risk(rainfall, 0.9)
    # vulnerability 0.3: 50 * 0.8 = 40 mm -> MODERATE
    low_vuln_risk = calculate_risk(rainfall, 0.3)

    assert high_vuln_risk == RiskLevel.HIGH
    assert low_vuln_risk == RiskLevel.MODERATE
    # Verify ordering
    rank = {RiskLevel.LOW: 1, RiskLevel.MODERATE: 2, RiskLevel.HIGH: 3, RiskLevel.SEVERE: 4}
    assert rank[high_vuln_risk] >= rank[low_vuln_risk]


def test_calculate_risk_negative_raises() -> None:
    """Case 6: Negative rainfall raises ValueError."""
    with pytest.raises(ValueError, match="rainfall_mm cannot be negative"):
        calculate_risk(-1.0, 0.5)
    with pytest.raises(ValueError, match="rainfall_mm cannot be negative"):
        calculate_risk(-0.01, 0.9)


def test_calculate_risk_clamping_vulnerability_above_one() -> None:
    """Case 7: Vulnerability above 1.0 is clamped to 1.0."""
    # 10.0 * (0.5 + 1.0 clamped) = 15.0 mm -> LOW
    assert calculate_risk(10.0, 1.8) == RiskLevel.LOW
    # 90.0 * (0.5 + 1.0 clamped) = 135.0 mm -> SEVERE
    assert calculate_risk(90.0, 2.5) == RiskLevel.SEVERE


def test_calculate_risk_clamping_vulnerability_below_zero() -> None:
    """Case 8: Vulnerability below 0.0 is clamped to 0.0."""
    # 60.0 * (0.5 + 0.0 clamped) = 30.0 mm -> MODERATE
    assert calculate_risk(60.0, -0.5) == RiskLevel.MODERATE


def test_risk_score_details_structure() -> None:
    """Case 9: Verify details dictionary structure and values for audit logs."""
    details = risk_score_details(50.0, 0.9)
    assert details["rainfall_mm"] == 50.0
    assert details["zone_vulnerability"] == 0.9
    assert details["adjusted_mm"] == 70.0
    assert details["risk_level"] == "HIGH"
    assert "thresholds" in details
