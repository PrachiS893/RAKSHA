"""Tests for pure deterministic triage scoring and reason generation."""

import pytest
from app.constants import Resource, RiskLevel, Urgency
from app.schemas import TriageFeatures
from app.services.triage_scoring import build_reason, calculate_priority


def test_triage_scoring_four_benchmark_cases() -> None:
    """Verify exact scores and urgency bands for the 4 benchmark citizen requests."""
    # 1. Rina - Drinking Water in High risk zone
    rina_features = TriageFeatures(
        resource_needed=Resource.DRINKING_WATER,
        people_count=6,
        no_supply_remaining=True,
        need_summary="Need drinking water and food for family.",
    )
    score1, urgency1, breakdown1 = calculate_priority(
        rina_features, region_risk=RiskLevel.HIGH
    )
    assert score1 == 35  # Base 20 + no_supply 5 + extra_people(5) + zone 5
    assert urgency1 == Urgency.MEDIUM

    # 2. Amit - Insulin emergency in Severe risk zone
    amit_features = TriageFeatures(
        resource_needed=Resource.MEDICAL_KIT,
        people_count=1,
        life_threatening=True,
        medical_dependency=True,
        no_supply_remaining=True,
        need_summary="Father is diabetic and has run out of insulin.",
    )
    score2, urgency2, breakdown2 = calculate_priority(
        amit_features, region_risk=RiskLevel.SEVERE
    )
    assert score2 == 88  # Base 30 + life_threat 30 + med_dep 15 + no_supply 5 + zone 8
    assert urgency2 == Urgency.CRITICAL

    # 3. Mrs. Das - Trapped elderly with rising water in Severe risk zone
    das_features = TriageFeatures(
        resource_needed=Resource.RESCUE_BOAT,
        people_count=1,
        life_threatening=True,
        trapped=True,
        immediate_danger=True,
        elderly=True,
        disabled_or_immobile=True,
        need_summary="Elderly woman trapped on ground floor, water is waist-deep.",
    )
    score3, urgency3, breakdown3 = calculate_priority(
        das_features, region_risk=RiskLevel.SEVERE
    )
    assert score3 == 100  # Base 30 + life_threat 30 + trapped 10 + danger 10 + vuln(12) + zone 8 = 100
    assert urgency3 == Urgency.CRITICAL

    # 4. Pooja - Food packet for family with children in High risk zone
    pooja_features = TriageFeatures(
        resource_needed=Resource.FOOD_PACKET,
        people_count=5,
        children=True,
        need_summary="Need food for family including children.",
    )
    score4, urgency4, breakdown4 = calculate_priority(
        pooja_features, region_risk=RiskLevel.HIGH
    )
    assert score4 == 25  # Base 10 + children 6 + extra_people(4) + zone 5
    assert urgency4 == Urgency.LOW


def test_vulnerable_and_people_caps() -> None:
    """Verify that vulnerable individual bonus is capped at +12 and people count bonus at +6."""
    features = TriageFeatures(
        resource_needed=Resource.FOOD_PACKET,  # Base 10
        elderly=True,  # 6
        children=True,  # 6
        disabled_or_immobile=True,  # 6 -> subtotal 18, capped at 12
        people_count=20,  # 19 extra -> capped at 6
        need_summary="Large vulnerable group.",
    )
    score, urgency, breakdown = calculate_priority(features, region_risk=RiskLevel.LOW)
    # Base 10 + vuln_cap 12 + people_cap 6 + zone 0 = 28
    assert score == 28
    assert urgency == Urgency.LOW

    # Verify zero-point cap explanation entries are present
    vuln_cap_entry = next((b for b in breakdown if b["factor"] == "vulnerable_cap"), None)
    assert vuln_cap_entry is not None
    assert vuln_cap_entry["points"] == 0

    people_cap_entry = next((b for b in breakdown if b["factor"] == "extra_people_cap"), None)
    assert people_cap_entry is not None
    assert people_cap_entry["points"] == 0


def test_clamping_to_1_and_100() -> None:
    """Verify scores never exceed 100 and never drop below 1."""
    # Exceeding 100
    extreme_features = TriageFeatures(
        resource_needed=Resource.RESCUE_BOAT,  # 30
        life_threatening=True,  # 30
        trapped=True,  # 10
        immediate_danger=True,  # 10
        medical_dependency=True,  # 15
        no_supply_remaining=True,  # 5
        elderly=True,  # 6
        children=True,  # 6
        disabled_or_immobile=True,  # 6 (cap 12)
        people_count=10,  # cap 6
        need_summary="Catastrophic situation.",
    )
    # Unclamped = 30 + 30 + 10 + 10 + 15 + 5 + 12 + 6 + 8 = 126
    score, urgency, breakdown = calculate_priority(extreme_features, region_risk=RiskLevel.SEVERE)
    assert score == 100
    assert urgency == Urgency.CRITICAL

    clamping_entry = next((b for b in breakdown if b["factor"] == "clamping"), None)
    assert clamping_entry is not None
    assert clamping_entry["points"] == 0
    assert "100" in clamping_entry["detail"]


def test_breakdown_points_sum_equals_unclamped_score() -> None:
    """Verify sum of breakdown points equals the calculated unclamped sum."""
    features = TriageFeatures(
        resource_needed=Resource.MEDICAL_KIT,  # 30
        medical_dependency=True,  # 15
        elderly=True,  # 6
        people_count=3,  # 2 extra
        need_summary="Need insulin for grandmother.",
    )
    score, urgency, breakdown = calculate_priority(features, region_risk=RiskLevel.MODERATE)
    # 30 + 15 + 6 + 2 + 2 = 55
    assert score == 55
    assert urgency == Urgency.HIGH
    assert sum(b["points"] for b in breakdown) == 55


def test_build_reason_length_and_content() -> None:
    """Verify build_reason generates concise, informative summaries <= 160 characters."""
    features = TriageFeatures(
        resource_needed=Resource.RESCUE_BOAT,
        life_threatening=True,
        trapped=True,
        immediate_danger=True,
        elderly=True,
        need_summary="Stranded on roof with rising water.",
    )
    score, urgency, breakdown = calculate_priority(features, region_risk=RiskLevel.SEVERE)
    reason = build_reason(breakdown, features, region_risk=RiskLevel.SEVERE)

    assert isinstance(reason, str)
    assert len(reason) > 0
    assert len(reason) <= 160
    assert "Life-threatening" in reason or "trapped" in reason.lower()
