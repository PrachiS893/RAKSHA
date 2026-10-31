"""Triage scoring service providing deterministic priority calculation and reason generation.

GOLDEN RULE:
The LLM ONLY extracts facts stated in the citizen's message.
Python calculates the priority score. The LLM never produces, suggests or changes a score or urgency.
"""

from typing import Any, Optional
from app.constants import Resource, RiskLevel, Urgency
from app.schemas import ScoreFactorBreakdown, TriageFeatures

# Weights constants dictionary for easy inspection, auditing, and tuning
TRIAGE_WEIGHTS: dict[str, Any] = {
    "base_resource": {
        Resource.RESCUE_BOAT: 30,
        Resource.MEDICAL_KIT: 30,
        Resource.DRINKING_WATER: 20,
        Resource.FOOD_PACKET: 10,
        None: 10,
    },
    "situational": {
        "life_threatening": 30,
        "trapped": 10,
        "immediate_danger": 10,
        "medical_dependency": 15,
        "no_supply_remaining": 5,
    },
    "vulnerable": {
        "elderly": 6,
        "children": 6,
        "disabled_or_immobile": 6,
        "cap": 12,
    },
    "people": {
        "per_extra_person": 1,
        "cap": 6,
    },
    "zone_risk": {
        RiskLevel.SEVERE: 8,
        RiskLevel.HIGH: 5,
        RiskLevel.MODERATE: 2,
        RiskLevel.LOW: 0,
        None: 0,
    },
}

URGENCY_BANDS: list[tuple[int, Urgency]] = [
    (75, Urgency.CRITICAL),
    (55, Urgency.HIGH),
    (30, Urgency.MEDIUM),
    (0, Urgency.LOW),
]


def calculate_priority(
    features: TriageFeatures, region_risk: Optional[RiskLevel] = None
) -> tuple[int, Urgency, list[dict[str, Any]]]:
    """Calculate deterministic triage priority score, urgency tier, and itemized breakdown.

    Returns:
        tuple of (clamped priority_score 1..100, Urgency, breakdown list of dicts)
    """
    breakdown: list[dict[str, Any]] = []

    # 1. Base points by resource
    base_res = features.resource_needed
    base_pts = TRIAGE_WEIGHTS["base_resource"].get(base_res, 10)
    res_label = base_res.value if base_res else "unspecified"
    breakdown.append({
        "factor": "base_resource",
        "points": base_pts,
        "detail": f"Primary resource needed: {res_label}",
    })

    # 2. Situational factors
    if features.life_threatening:
        pts = TRIAGE_WEIGHTS["situational"]["life_threatening"]
        breakdown.append({
            "factor": "life_threatening",
            "points": pts,
            "detail": "Immediate threat to life reported",
        })

    if features.medical_dependency:
        pts = TRIAGE_WEIGHTS["situational"]["medical_dependency"]
        breakdown.append({
            "factor": "medical_dependency",
            "points": pts,
            "detail": "Dependent on critical medication or medical equipment",
        })

    if features.trapped:
        pts = TRIAGE_WEIGHTS["situational"]["trapped"]
        breakdown.append({
            "factor": "trapped",
            "points": pts,
            "detail": "Person trapped or unable to self-evacuate",
        })

    if features.immediate_danger:
        pts = TRIAGE_WEIGHTS["situational"]["immediate_danger"]
        breakdown.append({
            "factor": "immediate_danger",
            "points": pts,
            "detail": "Immediate environmental danger (e.g. rising floodwater)",
        })

    if features.no_supply_remaining:
        pts = TRIAGE_WEIGHTS["situational"]["no_supply_remaining"]
        breakdown.append({
            "factor": "no_supply_remaining",
            "points": pts,
            "detail": "Essential provisions completely exhausted",
        })

    # 3. Vulnerable individuals (capped at +12)
    vuln_subtotal = 0
    vuln_labels: list[str] = []
    if features.elderly:
        vuln_subtotal += TRIAGE_WEIGHTS["vulnerable"]["elderly"]
        vuln_labels.append("elderly")
    if features.children:
        vuln_subtotal += TRIAGE_WEIGHTS["vulnerable"]["children"]
        vuln_labels.append("children")
    if features.disabled_or_immobile:
        vuln_subtotal += TRIAGE_WEIGHTS["vulnerable"]["disabled_or_immobile"]
        vuln_labels.append("disabled/immobile")

    vuln_cap = TRIAGE_WEIGHTS["vulnerable"]["cap"]
    vuln_points = min(vuln_subtotal, vuln_cap)
    if vuln_points > 0:
        breakdown.append({
            "factor": "vulnerable_people",
            "points": vuln_points,
            "detail": f"Vulnerable people present ({', '.join(vuln_labels)})",
        })
        if vuln_subtotal > vuln_cap:
            breakdown.append({
                "factor": "vulnerable_cap",
                "points": 0,
                "detail": f"Vulnerable bonus capped at +{vuln_cap} (uncapped was +{vuln_subtotal})",
            })

    # 4. Extra people beyond the first (+1 each, capped at +6)
    count = features.people_count if features.people_count is not None else 1
    extra_people = max(0, count - 1)
    extra_cap = TRIAGE_WEIGHTS["people"]["cap"]
    extra_points = min(extra_people, extra_cap)
    if extra_points > 0:
        breakdown.append({
            "factor": "extra_people",
            "points": extra_points,
            "detail": f"{count} people affected (+{extra_points} for individuals beyond the first)",
        })
        if extra_people > extra_cap:
            breakdown.append({
                "factor": "extra_people_cap",
                "points": 0,
                "detail": f"People bonus capped at +{extra_cap}",
            })

    # 5. Zone flood risk context
    risk_pts = TRIAGE_WEIGHTS["zone_risk"].get(region_risk, 0)
    if risk_pts > 0 and region_risk:
        breakdown.append({
            "factor": "zone_risk",
            "points": risk_pts,
            "detail": f"Located in zone evaluated at {region_risk.value} flood risk",
        })

    # Unclamped sum equals sum of contributing factors
    unclamped_score = sum(b["points"] for b in breakdown)
    final_score = max(1, min(100, unclamped_score))

    if unclamped_score != final_score:
        breakdown.append({
            "factor": "clamping",
            "points": 0,
            "detail": f"Final score clamped to {final_score} from unclamped total {unclamped_score}",
        })

    # Determine urgency tier
    urgency = Urgency.LOW
    for threshold, band in URGENCY_BANDS:
        if final_score >= threshold:
            urgency = band
            break

    return final_score, urgency, breakdown


def build_reason(
    breakdown: list[dict[str, Any]],
    features: TriageFeatures,
    region_risk: Optional[RiskLevel],
) -> str:
    """Construct deterministic concise rationale from top contributing score factors.

    Takes up to the 3 largest non-base factors and formats a readable summary under 160 characters.
    """
    factor_phrases: dict[str, str] = {
        "life_threatening": "Life-threatening situation reported",
        "medical_dependency": "Critical medical dependency",
        "trapped": "Person trapped",
        "immediate_danger": "Immediate danger from rising water",
        "vulnerable_people": "Vulnerable individuals present",
        "zone_risk": f"Zone at {region_risk.value} flood risk" if region_risk else "High flood risk zone",
        "no_supply_remaining": "Provisions exhausted",
        "extra_people": f"{features.people_count or 1} people affected",
    }

    # Filter out base_resource and 0-point cap/clamping notes
    contributing = [
        b for b in breakdown
        if b["factor"] != "base_resource" and b["points"] > 0 and b["factor"] in factor_phrases
    ]

    # Sort descending by points
    contributing.sort(key=lambda b: b["points"], reverse=True)
    top_factors = contributing[:3]

    phrases: list[str] = [factor_phrases[b["factor"]] for b in top_factors]

    # If fewer than 3 factors, prepend resource need
    if len(phrases) < 3 and features.resource_needed:
        res_text = features.resource_needed.value.replace("_", " ").title()
        phrases.insert(0, f"Needs {res_text}")

    if not phrases:
        phrases = ["General emergency assistance requested"]

    reason = "; ".join(phrases) + "."
    if len(reason) > 160:
        reason = reason[:157] + "..."
    return reason
