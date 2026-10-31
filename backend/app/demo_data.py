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
        "households_estimate": 400,
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
        "households_estimate": 600,
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
        "households_estimate": 300,
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

# 5 predefined stages of the flood response scenario
STAGES: list[dict[str, Any]] = [
    {
        "stage": 1,
        "name": "Normal conditions",
        "description": "Risk is low everywhere. No alerts, no requests, stock at 100%.",
    },
    {
        "stage": 2,
        "name": "Heavy rainfall forecast",
        "description": "The Risk Agent flags regions. Warnings are drafted for the coordinator.",
    },
    {
        "stage": 3,
        "name": "Flood begins",
        "description": "Flooding starts in the lowest zones and four emergency requests arrive.",
    },
    {
        "stage": 4,
        "name": "Triage and allocation",
        "description": "Requests are ranked and supplies are recommended.",
    },
    {
        "stage": 5,
        "name": "Routes and approval",
        "description": "Safe delivery routes are shown and the coordinator approves the plan.",
    },
]

# 24h forecast rainfall (in mm) by region name for simulation stages
STAGE_RAINFALL: dict[int, dict[str, float]] = {
    2: {
        "Zone A - Riverside": 90.0,
        "Zone B - Central Lowlands": 70.0,
        "Zone C - Eastern Uplands": 40.0,
    },
    3: {
        "Zone A - Riverside": 110.0,
        "Zone B - Central Lowlands": 85.0,
        "Zone C - Eastern Uplands": 50.0,
    },
}

# Monitored zones marked flooded during Stage 3
FLOODED_ZONES_STAGE_3: list[str] = [
    "Zone A - Riverside",
    "Zone B - Central Lowlands",
]

# Simulated hazard zones for routing avoidance (small localized obstacle boxes)
HAZARD_ZONES: list[dict[str, Any]] = [
    {
        "name": "Flooded underpass - north approach",
        "description": "Severe localized waterlogging blocking the underpass on the north arterial road.",
        "polygon": {
            "type": "Polygon",
            "coordinates": [
                [
                    [91.738, 26.193],
                    [91.744, 26.193],
                    [91.744, 26.198],
                    [91.738, 26.198],
                    [91.738, 26.193],
                ]
            ],
        },
        "active": False,
        "simulated": True,
    },
    {
        "name": "River overflow - south approach",
        "description": "River surge overflowing low-lying roadway on the southern corridor.",
        "polygon": {
            "type": "Polygon",
            "coordinates": [
                [
                    [91.741, 26.113],
                    [91.747, 26.113],
                    [91.747, 26.118],
                    [91.741, 26.118],
                    [91.741, 26.113],
                ]
            ],
        },
        "active": False,
        "simulated": True,
    },
]
