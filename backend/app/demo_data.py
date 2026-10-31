"""Centralized demo data constants for the Raksha flood-response system."""

from typing import Any
from app.constants import Resource, RiskLevel

# 3 rectangular zones near Guwahati, Assam
# Coordinates format: [longitude, latitude] in closed rings
DEMO_REGIONS: list[dict[str, Any]] = [
    {
        "name": "Zone A - Riverside",
        "vulnerability": 0.9,
        "center_lat": 26.18,
        "center_lon": 91.74,
        "risk_level": RiskLevel.LOW.value,
        "rainfall_mm": 0.0,
        "is_simulated_flood": True,
        "polygon": {
            "type": "Polygon",
            "coordinates": [
                [
                    [91.72, 26.16],
                    [91.76, 26.16],
                    [91.76, 26.20],
                    [91.72, 26.20],
                    [91.72, 26.16],
                ]
            ],
        },
    },
    {
        "name": "Zone B - Central Lowlands",
        "vulnerability": 0.6,
        "center_lat": 26.14,
        "center_lon": 91.74,
        "risk_level": RiskLevel.LOW.value,
        "rainfall_mm": 0.0,
        "is_simulated_flood": True,
        "polygon": {
            "type": "Polygon",
            "coordinates": [
                [
                    [91.72, 26.12],
                    [91.76, 26.12],
                    [91.76, 26.16],
                    [91.72, 26.16],
                    [91.72, 26.12],
                ]
            ],
        },
    },
    {
        "name": "Zone C - Eastern Uplands",
        "vulnerability": 0.3,
        "center_lat": 26.14,
        "center_lon": 91.79,
        "risk_level": RiskLevel.LOW.value,
        "rainfall_mm": 0.0,
        "is_simulated_flood": True,
        "polygon": {
            "type": "Polygon",
            "coordinates": [
                [
                    [91.77, 26.12],
                    [91.81, 26.12],
                    [91.81, 26.16],
                    [91.77, 26.16],
                    [91.77, 26.12],
                ]
            ],
        },
    },
]

# Relief warehouses placed outside the active flood zones
DEMO_WAREHOUSES: list[dict[str, Any]] = [
    {
        "name": "Warehouse A - North Depot",
        "lat": 26.21,
        "lon": 91.74,
        "inventory": [
            {"resource": Resource.DRINKING_WATER.value, "quantity": 300, "initial_quantity": 300},
            {"resource": Resource.FOOD_PACKET.value, "quantity": 200, "initial_quantity": 200},
            {"resource": Resource.MEDICAL_KIT.value, "quantity": 5, "initial_quantity": 5},
            {"resource": Resource.RESCUE_BOAT.value, "quantity": 2, "initial_quantity": 2},
        ],
    },
    {
        "name": "Warehouse B - Central Depot",
        "lat": 26.11,
        "lon": 91.74,
        "inventory": [
            {"resource": Resource.DRINKING_WATER.value, "quantity": 150, "initial_quantity": 150},
            {"resource": Resource.FOOD_PACKET.value, "quantity": 100, "initial_quantity": 100},
            {"resource": Resource.MEDICAL_KIT.value, "quantity": 2, "initial_quantity": 2},
            {"resource": Resource.RESCUE_BOAT.value, "quantity": 1, "initial_quantity": 1},
        ],
    },
    {
        "name": "Warehouse C - East Depot",
        "lat": 26.14,
        "lon": 91.82,
        "inventory": [
            {"resource": Resource.DRINKING_WATER.value, "quantity": 100, "initial_quantity": 100},
            {"resource": Resource.FOOD_PACKET.value, "quantity": 60, "initial_quantity": 60},
            {"resource": Resource.MEDICAL_KIT.value, "quantity": 1, "initial_quantity": 1},
            {"resource": Resource.RESCUE_BOAT.value, "quantity": 0, "initial_quantity": 0},
        ],
    },
]

# Demo alert notification subscribers mapped by region name
DEMO_SUBSCRIPTIONS: list[dict[str, Any]] = [
    {"region_name": "Zone A - Riverside", "name": "Demo Citizen 1", "telegram_chat_id": None},
    {"region_name": "Zone A - Riverside", "name": "Demo Citizen 2", "telegram_chat_id": None},
    {"region_name": "Zone B - Central Lowlands", "name": "Demo Citizen 3", "telegram_chat_id": None},
    {"region_name": "Zone C - Eastern Uplands", "name": "Demo Citizen 4", "telegram_chat_id": None},
]

# Sample citizen requests reserved for the future simulator (do NOT insert during seed)
SAMPLE_REQUESTS: list[dict[str, Any]] = [
    {
        "text": "We have had no drinking water since last night. 6 people in the house.",
        "name": "Rina",
        "lat": 26.135,
        "lon": 91.735,
    },
    {
        "text": "My father is diabetic and has run out of insulin. He is very weak.",
        "name": "Amit",
        "lat": 26.175,
        "lon": 91.745,
    },
    {
        "text": "Elderly woman trapped on the first floor, water is rising and she cannot walk.",
        "name": "Neighbour of Mrs. Das",
        "lat": 26.185,
        "lon": 91.735,
    },
    {
        "text": "Need food for five people including two small children.",
        "name": "Pooja",
        "lat": 26.125,
        "lon": 91.75,
    },
]
