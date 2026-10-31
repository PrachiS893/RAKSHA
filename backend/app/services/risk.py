"""Deterministic flood risk scoring service for Raksha.

GOLDEN RULE:
The LLM only writes explanatory text. The risk level ALWAYS comes from the
pure Python function `calculate_risk`. The LLM never decides, changes, or
overrides a risk level or number.
"""

from typing import Any
from app.constants import RiskLevel

# Thresholds on adjusted precipitation (adjusted_mm).
# NOTE: These thresholds are loosely inspired by meteorological heavy/very heavy rainfall
# categories and represent a DEMO heuristic for hackathon simulation, not an official flood forecast.
RISK_THRESHOLDS: dict[str, tuple[float, float]] = {
    RiskLevel.LOW.value: (0.0, 25.0),
    RiskLevel.MODERATE.value: (25.0, 65.0),
    RiskLevel.HIGH.value: (65.0, 115.0),
    RiskLevel.SEVERE.value: (115.0, float("inf")),
}


def calculate_risk(rainfall_mm: float, zone_vulnerability: float) -> RiskLevel:
    """Calculate deterministic flood risk level based on rainfall and terrain vulnerability.

    Formula:
        adjusted_mm = rainfall_mm * (0.5 + clamped_vulnerability)

    Args:
        rainfall_mm: Total forecast rainfall in millimeters (must be >= 0).
        zone_vulnerability: Zone terrain vulnerability factor (clamped to [0.0, 1.0]).

    Returns:
        RiskLevel Enum member (LOW, MODERATE, HIGH, SEVERE).

    Raises:
        ValueError: If rainfall_mm is negative.
    """
    if rainfall_mm < 0:
        raise ValueError("rainfall_mm cannot be negative")

    # Clamp vulnerability to 0.0 .. 1.0
    clamped_vulnerability = max(0.0, min(1.0, float(zone_vulnerability)))

    # Compute vulnerability-weighted rainfall
    adjusted_mm = rainfall_mm * (0.5 + clamped_vulnerability)

    if adjusted_mm < 25.0:
        return RiskLevel.LOW
    elif adjusted_mm < 65.0:
        return RiskLevel.MODERATE
    elif adjusted_mm < 115.0:
        return RiskLevel.HIGH
    else:
        return RiskLevel.SEVERE


def risk_score_details(rainfall_mm: float, zone_vulnerability: float) -> dict[str, Any]:
    """Return risk calculation details including adjusted_mm and thresholds for logging.

    GOLDEN RULE:
    The risk level returned here is computed deterministically by calculate_risk.
    """
    if rainfall_mm < 0:
        raise ValueError("rainfall_mm cannot be negative")

    clamped_vulnerability = max(0.0, min(1.0, float(zone_vulnerability)))
    adjusted_mm = rainfall_mm * (0.5 + clamped_vulnerability)
    risk_level = calculate_risk(rainfall_mm, zone_vulnerability)

    return {
        "rainfall_mm": rainfall_mm,
        "zone_vulnerability": clamped_vulnerability,
        "adjusted_mm": round(adjusted_mm, 2),
        "risk_level": risk_level.value,
        "thresholds": {
            "LOW": "< 25 mm",
            "MODERATE": "25 - 64.9 mm",
            "HIGH": "65 - 114.9 mm",
            "SEVERE": ">= 115 mm",
        },
    }
