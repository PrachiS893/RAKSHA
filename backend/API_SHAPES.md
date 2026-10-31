# Raksha Backend API Shapes & Documentation

This document describes the exact JSON schemas and endpoint request/response contracts for the Raksha backend. It is designed for frontend developers building the React coordination dashboard.

---

## General Conventions

- **Simulation Flag**: All demo data is marked with simulation indicators (e.g., `"is_simulated_flood": true`, `"simulated": true`).
- **Coordinates**:
  - In GeoJSON (`Polygon`): `[longitude, latitude]` pairs in closed rings.
  - In flat objects/fields: `"lat"` (latitude) and `"lon"` (longitude).
- **Timestamps**: All datetimes are stored in UTC and formatted as ISO 8601 strings (e.g. `2026-10-31T10:00:00Z`).
- **Resource Units**: Quantities map to units:
  - `drinking_water` -> `"litres"`
  - `food_packet` -> `"packets"`
  - `medical_kit` -> `"kits"`
  - `rescue_boat` -> `"boats"`

---

## 1. Geographical Regions

### `GET /regions`
Lists all monitored flood zones, their boundary polygons, center points, and current risk metrics.

#### Response (`200 OK`)
```json
[
  {
    "id": 1,
    "name": "Zone A - Riverside",
    "polygon": {
      "type": "Polygon",
      "coordinates": [
        [
          [91.72, 26.16],
          [91.76, 26.16],
          [91.76, 26.20],
          [91.72, 26.20],
          [91.72, 26.16]
        ]
      ]
    },
    "center": {
      "lat": 26.18,
      "lon": 91.74
    },
    "vulnerability": 0.9,
    "risk_level": "LOW",
    "rainfall_mm": 0.0,
    "is_simulated_flood": true
  }
]
```

---

## 2. Warehouses & Inventory

### `GET /warehouses`
Lists all supply warehouses with their nested inventory resources and units.

#### Response (`200 OK`)
```json
[
  {
    "id": 1,
    "name": "Warehouse A - North Depot",
    "lat": 26.21,
    "lon": 91.74,
    "inventory": [
      {
        "resource": "drinking_water",
        "unit": "litres",
        "quantity": 300,
        "initial_quantity": 300
      },
      {
        "resource": "food_packet",
        "unit": "packets",
        "quantity": 200,
        "initial_quantity": 200
      },
      {
        "resource": "medical_kit",
        "unit": "kits",
        "quantity": 5,
        "initial_quantity": 5
      },
      {
        "resource": "rescue_boat",
        "unit": "boats",
        "quantity": 2,
        "initial_quantity": 2
      }
    ],
    "simulated": true
  }
]
```

---

## 3. Emergency Requests

### `GET /requests`
Returns citizen distress requests sorted by `priority_score` descending (nulls last), then `created_at` descending.

#### Query Parameters (Optional)
- `status` (string, optional): Filter by status (`received`, `prioritized`, `assigned`, `on_the_way`, `shortage`).
- `region_id` (integer, optional): Filter by region ID.

#### Response (`200 OK`)
```json
[
  {
    "id": 1,
    "text": "My father is diabetic and has run out of insulin. He is very weak.",
    "name": "Amit",
    "lat": 26.175,
    "lon": 91.745,
    "region_id": 1,
    "region_name": "Zone A - Riverside",
    "status": "received",
    "resource_needed": null,
    "people_count": null,
    "urgency": null,
    "priority_score": null,
    "reason": null,
    "created_at": "2026-10-31T07:30:00Z"
  }
]
```

---

### `POST /requests`
Submit a new citizen distress call. The system automatically performs a point-in-polygon check against flood zones to assign `region_id`. If the location is outside all zones, `region_id` is set to `null`.

#### Request Body
```json
{
  "text": "We have had no drinking water since last night. 6 people in the house.",
  "lat": 26.135,
  "lon": 91.735,
  "name": "Rina"
}
```

#### Validation Rules
- `text`: String between 3 and 1000 characters after whitespace trimming.
- `lat`: Float between -90.0 and 90.0.
- `lon`: Float between -180.0 and 180.0.
- `name`: Optional string.

#### Response (`201 Created`)
```json
{
  "id": 2,
  "text": "We have had no drinking water since last night. 6 people in the house.",
  "name": "Rina",
  "lat": 26.135,
  "lon": 91.735,
  "region_id": 2,
  "region_name": "Zone B - Central Lowlands",
  "status": "received",
  "resource_needed": null,
  "people_count": null,
  "urgency": null,
  "priority_score": null,
  "reason": null,
  "created_at": "2026-10-31T07:32:00Z"
}
```

---

## 4. Public Alerts Feed

### `GET /alerts`
Citizen alert feed. Returns approved and sent public safety alerts (excludes internal drafts), ordered newest first.

#### Query Parameters (Optional)
- `region_id` (integer, optional): Filter alerts by region ID.

#### Response (`200 OK`)
```json
[
  {
    "id": 1,
    "region_id": 1,
    "region_name": "Zone A - Riverside",
    "level": "WARNING",
    "message": "Water levels rising near river banks. Residents advised to prepare for evacuation.",
    "status": "sent",
    "approved_by": "coordinator",
    "created_at": "2026-10-31T07:00:00Z"
  }
]
```

---

## 5. Alert Subscriptions

### `POST /subscriptions`
Registers a citizen to receive emergency alerts for a given region.

#### Request Body
```json
{
  "region_id": 1,
  "name": "Citizen User",
  "telegram_chat_id": "123456789"
}
```

#### Validation & Errors
- If `region_id` does not exist: Returns `404 Not Found` with `{"detail": "Region with id <id> does not exist"}`.

#### Response (`201 Created`)
```json
{
  "id": 5,
  "region_id": 1,
  "region_name": "Zone A - Riverside",
  "name": "Citizen User",
  "telegram_chat_id": "123456789"
}
```
