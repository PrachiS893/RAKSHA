"""Tests for shortage prediction logic and GET /resources/shortages endpoint.

GOLDEN RULES:
- Shortage numbers are demo planning assumptions, not real forecasts.
"""

from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.constants import Resource, RiskLevel
from app.models import Region
from app.services.shortage import predict_shortages


def test_predict_shortages_flood_conditions(client_and_session: tuple[TestClient, Session]) -> None:
    _, session = client_and_session

    # Set risk levels: Zone A SEVERE, Zone B HIGH, Zone C MODERATE
    regions = session.exec(select(Region)).all()
    reg_map = {r.name: r for r in regions}

    reg_map["Zone A - Bharalumukh"].risk_level = RiskLevel.SEVERE.value
    reg_map["Zone B - Beltola"].risk_level = RiskLevel.HIGH.value
    reg_map["Zone C - Noonmati"].risk_level = RiskLevel.MODERATE.value
    for r in regions:
        session.add(r)
    session.commit()

    shortages = predict_shortages(session)
    assert shortages["simulated"] is True
    assert "Illustrative planning assumptions" in shortages["assumptions"]

    res_dict = {item["resource"]: item for item in shortages["resources"]}

    # Drinking water: demand 1340 vs stock 550, shortfall 790, SHORTAGE
    water = res_dict[Resource.DRINKING_WATER.value]
    assert water["unit"] == "litres"
    assert water["stock"] == 550
    assert water["predicted_demand"] == 1340
    assert water["shortfall"] == 790
    assert water["status"] == "SHORTAGE"

    # Food packets: demand 402 vs stock 360, shortfall 42, SHORTAGE
    food = res_dict[Resource.FOOD_PACKET.value]
    assert food["unit"] == "packets"
    assert food["stock"] == 360
    assert food["predicted_demand"] == 402
    assert food["shortfall"] == 42
    assert food["status"] == "SHORTAGE"

    # Medical kit: demand 7 vs stock 8, shortfall 0, TIGHT (8 < 7 * 1.25 = 8.75)
    medical = res_dict[Resource.MEDICAL_KIT.value]
    assert medical["unit"] == "kits"
    assert medical["stock"] == 8
    assert medical["predicted_demand"] == 7
    assert medical["shortfall"] == 0
    assert medical["status"] == "TIGHT"

    # Rescue boat: demand 6 vs stock 3, shortfall 3, SHORTAGE
    boat = res_dict[Resource.RESCUE_BOAT.value]
    assert boat["unit"] == "boats"
    assert boat["stock"] == 3
    assert boat["predicted_demand"] == 6
    assert boat["shortfall"] == 3
    assert boat["status"] == "SHORTAGE"

    # Verify regional breakdowns
    water_by_reg = {b["region"]: b["demand"] for b in water["by_region"]}
    assert water_by_reg["Zone A - Bharalumukh"] == 800.0
    assert water_by_reg["Zone B - Beltola"] == 480.0
    assert water_by_reg["Zone C - Noonmati"] == 60.0


def test_predict_shortages_all_low_conditions(client_and_session: tuple[TestClient, Session]) -> None:
    _, session = client_and_session

    # In seed data, all regions start as LOW risk
    shortages = predict_shortages(session)
    for res_info in shortages["resources"]:
        assert res_info["predicted_demand"] == 0
        assert res_info["shortfall"] == 0
        assert res_info["status"] == "OK"


def test_get_resources_shortages_endpoint(client_and_session: tuple[TestClient, Session]) -> None:
    client, session = client_and_session

    # Set risk levels to flood scenario
    regions = session.exec(select(Region)).all()
    for r in regions:
        if "Zone A" in r.name:
            r.risk_level = RiskLevel.SEVERE.value
        elif "Zone B" in r.name:
            r.risk_level = RiskLevel.HIGH.value
        elif "Zone C" in r.name:
            r.risk_level = RiskLevel.MODERATE.value
        session.add(r)
    session.commit()

    response = client.get("/resources/shortages")
    assert response.status_code == 200
    data = response.json()

    assert "as_of" in data
    assert data["simulated"] is True
    assert "Illustrative planning assumptions for the demo, not a real forecast." in data["assumptions"]

    resources = data["resources"]
    assert len(resources) == 4
    res_names = [r["resource"] for r in resources]
    assert res_names == [
        Resource.DRINKING_WATER.value,
        Resource.FOOD_PACKET.value,
        Resource.MEDICAL_KIT.value,
        Resource.RESCUE_BOAT.value,
    ]

    for item in resources:
        assert "resource" in item
        assert "unit" in item
        assert "stock" in item
        assert "predicted_demand" in item
        assert "shortfall" in item
        assert "status" in item
        assert "by_region" in item
        assert len(item["by_region"]) == 3
