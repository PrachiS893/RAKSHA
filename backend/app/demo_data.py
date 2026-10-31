"""Centralized demo data constants for the Raksha flood-response system."""

from typing import Any
from app.constants import Resource, RiskLevel

# Zone code mapping for clean referencing and renaming
ZONE_CODES: dict[str, str] = {
    "A": "Zone A - Bharalumukh",
    "B": "Zone B - Beltola",
    "C": "Zone C - Noonmati",
}

# 3 non-overlapping zones in Guwahati, Assam
# Coordinates format: [longitude, latitude] in closed rings
DEMO_REGIONS: list[dict[str, Any]] = [
    {
        "name": ZONE_CODES["A"],
        "vulnerability": 0.9,
        "center_lat": 26.166952,
        "center_lon": 91.755809,
        "risk_level": RiskLevel.LOW.value,
        "rainfall_mm": 0.0,
        "is_simulated_flood": True,
        "households_estimate": 400,
        "polygon": {
            "type": "Polygon",
            "coordinates": [
                [
                    [91.73425, 26.17962],
                    [91.77854, 26.17620],
                    [91.78112, 26.15606],
                    [91.73155, 26.15664],
                    [91.73425, 26.17962],
                ]
            ],
        },
    },
    {
        "name": ZONE_CODES["B"],
        "vulnerability": 0.6,
        "center_lat": 26.133165,
        "center_lon": 91.777143,
        "risk_level": RiskLevel.LOW.value,
        "rainfall_mm": 0.0,
        "is_simulated_flood": True,
        "households_estimate": 600,
        "polygon": {
            "type": "Polygon",
            "coordinates": [
                [
                    [91.73103, 26.15540],
                    [91.82442, 26.15500],
                    [91.82862, 26.11391],
                    [91.72794, 26.10952],
                    [91.73103, 26.15540],
                ]
            ],
        },
    },
    {
        "name": ZONE_CODES["C"],
        "vulnerability": 0.3,
        "center_lat": 26.189464,
        "center_lon": 91.793816,
        "risk_level": RiskLevel.LOW.value,
        "rainfall_mm": 0.0,
        "is_simulated_flood": True,
        "households_estimate": 300,
        "polygon": {
            "type": "Polygon",
            "coordinates": [
                [
                    [91.76966, 26.19950],
                    [91.81626, 26.20262],
                    [91.81631, 26.17809],
                    [91.77163, 26.17724],
                    [91.76966, 26.19950],
                ]
            ],
        },
    },
]

# Relief warehouses located in Guwahati
DEMO_WAREHOUSES: list[dict[str, Any]] = [
    {
        "name": "Warehouse A - Fancy Bazaar",
        "lat": 26.177680,
        "lon": 91.734750,
        "inventory": [
            {"resource": Resource.DRINKING_WATER.value, "quantity": 300, "initial_quantity": 300},
            {"resource": Resource.FOOD_PACKET.value, "quantity": 200, "initial_quantity": 200},
            {"resource": Resource.MEDICAL_KIT.value, "quantity": 5, "initial_quantity": 5},
            {"resource": Resource.RESCUE_BOAT.value, "quantity": 2, "initial_quantity": 2},
        ],
    },
    {
        "name": "Warehouse B - Khanapara",
        "lat": 26.119845,
        "lon": 91.822915,
        "inventory": [
            {"resource": Resource.DRINKING_WATER.value, "quantity": 150, "initial_quantity": 150},
            {"resource": Resource.FOOD_PACKET.value, "quantity": 100, "initial_quantity": 100},
            {"resource": Resource.MEDICAL_KIT.value, "quantity": 2, "initial_quantity": 2},
            {"resource": Resource.RESCUE_BOAT.value, "quantity": 1, "initial_quantity": 1},
        ],
    },
    {
        "name": "Warehouse C - Noonmati",
        "lat": 26.184660,
        "lon": 91.774080,
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
    {"region_name": ZONE_CODES["A"], "name": "Demo Citizen 1", "telegram_chat_id": None},
    {"region_name": ZONE_CODES["A"], "name": "Demo Citizen 2", "telegram_chat_id": None},
    {"region_name": ZONE_CODES["B"], "name": "Demo Citizen 3", "telegram_chat_id": None},
    {"region_name": ZONE_CODES["C"], "name": "Demo Citizen 4", "telegram_chat_id": None},
]

# Clearly marked constant for sample request coordinates (lat, lon)
SAMPLE_REQUEST_LOCATIONS: dict[str, dict[str, float]] = {
    "elderly_trapped": {"lat": 26.166420, "lon": 91.756246},  # Zone A representative point
    "insulin": {"lat": 26.166420, "lon": 91.766246},          # Zone A east offset (+0.01 deg east)
    "water": {"lat": 26.134455, "lon": 91.778070},            # Zone B representative point
    "food": {"lat": 26.134455, "lon": 91.788070},             # Zone B east offset (+0.01 deg east)
}

# Sample citizen requests reserved for the future simulator (do NOT insert during seed)
SAMPLE_REQUESTS: list[dict[str, Any]] = [
    {
        "text": "We have had no drinking water since last night. 6 people in the house.",
        "name": "Rina",
        "lat": SAMPLE_REQUEST_LOCATIONS["water"]["lat"],
        "lon": SAMPLE_REQUEST_LOCATIONS["water"]["lon"],
    },
    {
        "text": "My father is diabetic and has run out of insulin. He is very weak.",
        "name": "Amit",
        "lat": SAMPLE_REQUEST_LOCATIONS["insulin"]["lat"],
        "lon": SAMPLE_REQUEST_LOCATIONS["insulin"]["lon"],
    },
    {
        "text": "Elderly woman trapped on the first floor, water is rising and she cannot walk.",
        "name": "Neighbour of Mrs. Das",
        "lat": SAMPLE_REQUEST_LOCATIONS["elderly_trapped"]["lat"],
        "lon": SAMPLE_REQUEST_LOCATIONS["elderly_trapped"]["lon"],
    },
    {
        "text": "Need food for five people including two small children.",
        "name": "Pooja",
        "lat": SAMPLE_REQUEST_LOCATIONS["food"]["lat"],
        "lon": SAMPLE_REQUEST_LOCATIONS["food"]["lon"],
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

# 24h forecast rainfall (in mm) keyed by zone code for simulation stages
STAGE_RAINFALL: dict[int, dict[str, float]] = {
    2: {
        "A": 90.0,
        "B": 70.0,
        "C": 40.0,
    },
    3: {
        "A": 110.0,
        "B": 85.0,
        "C": 50.0,
    },
}

# Monitored zones marked flooded during Stage 3 keyed by zone code
FLOODED_ZONES_STAGE_3: list[str] = [
    "A",
    "B",
]

# Clearly marked constant for hazard zone centres (lat, lon)
HAZARD_CENTRES: dict[str, dict[str, float]] = {
    "hazard_1": {"lat": 26.172050, "lon": 91.745498},  # Midpoint Warehouse A -> Elderly trapped
    "hazard_2": {"lat": 26.127150, "lon": 91.800492},  # Midpoint Warehouse B -> Water request
}

# Simulated hazard zones for routing avoidance (small localized obstacle boxes, ~0.003 deg on each side)
HAZARD_ZONES: list[dict[str, Any]] = [
    {
        "name": "Flooded underpass - north approach",
        "description": "Severe localized waterlogging blocking the underpass on the north arterial road.",
        "polygon": {
            "type": "Polygon",
            "coordinates": [
                [
                    [91.743998, 26.170550],
                    [91.746998, 26.170550],
                    [91.746998, 26.173550],
                    [91.743998, 26.173550],
                    [91.743998, 26.170550],
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
                    [91.798992, 26.125650],
                    [91.801992, 26.125650],
                    [91.801992, 26.128650],
                    [91.798992, 26.128650],
                    [91.798992, 26.125650],
                ]
            ],
        },
        "active": False,
        "simulated": True,
    },
]
