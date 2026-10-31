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
    "is_flooded": false,
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

## 4. Public Alerts Feed & Coordinator Approval

### `GET /alerts`
Citizen alert feed. Returns only alerts whose status is `"approved"` or `"sent"` (internal drafts and superseded alerts are excluded), ordered newest first.

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
    "level_label": "Warning",
    "message": "Flood warning for Zone A: heavy rainfall (about 80 mm) may cause flooding. Move valuables and documents to higher ground, keep drinking water and medicines ready, and avoid flooded roads. Nearest relief point: Warehouse A - North Depot, about 3.3 km away.",
    "status": "sent",
    "requires_approval": true,
    "approved_by": "Coordinator Sarah",
    "approved_at": "2026-10-31T07:10:00Z",
    "created_at": "2026-10-31T07:00:00Z",
    "deliveries": [
      {
        "channel": "in_app",
        "status": "sent",
        "recipient": null,
        "detail": null,
        "sent_at": "2026-10-31T07:10:00Z"
      },
      {
        "channel": "telegram",
        "status": "sent",
        "recipient": "Demo Citizen 1",
        "detail": null,
        "sent_at": "2026-10-31T07:10:01Z"
      },
      {
        "channel": "sms_sim",
        "status": "simulated",
        "recipient": "Demo Citizen 1",
        "detail": null,
        "sent_at": null
      }
    ]
  }
]
```

---

### `GET /alerts/pending`
Coordinator inbox feed. Returns all disaster alerts currently in `"draft"` status awaiting human coordinator review, newest first. Deliveries list is empty.

#### Response (`200 OK`)
```json
[
  {
    "id": 2,
    "region_id": 1,
    "region_name": "Zone A - Riverside",
    "level": "URGENT",
    "level_label": "Urgent warning",
    "message": "URGENT flood warning for Zone A - Riverside: severe flooding is likely (about 125 mm of rain). Move to higher ground now, stay away from flooded roads and electrical lines, and help children and elderly neighbours. Nearest relief point: Warehouse A - North Depot, about 3.3 km away.",
    "status": "draft",
    "requires_approval": true,
    "approved_by": null,
    "approved_at": null,
    "created_at": "2026-10-31T07:15:00Z",
    "deliveries": []
  }
]
```

---

### `POST /alerts/{id}/approve`
Human coordinator approves a draft alert, triggers automated multi-channel delivery (in-app, Telegram, simulated SMS), and transitions status to `"sent"`.

#### Request Body (Optional)
```json
{
  "approved_by": "Coordinator Sarah",
  "message": "Flood warning for Zone A: 80 mm rainfall expected. Move belongings to higher ground. Nearest depot: Warehouse A - North Depot, 3.3 km."
}
```
*Note: If `message` is omitted, the original drafted message is dispatched.*

#### Validation Rules & Status Codes
- If the alert does not exist: Returns `404 Not Found`.
- If the alert is not in `"draft"` status (e.g. already sent or superseded): Returns `409 Conflict`.
- If an edited `message` is provided:
  - Must be between 10 and 320 characters.
  - Must reference the region name (either the full name e.g. `"Zone A - Riverside"` or the short name e.g. `"Zone A"`).
  - Fails with `422 Unprocessable Entity` if non-compliant.

#### Response (`200 OK`)
Returns the approved and dispatched `Alert` object with full `deliveries` history.

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

---

## 6. Simulation State & Controls

> **Disclaimer**: *Illustrative simulation, not a live emergency feed.*

The simulator progresses the disaster response scenario across 5 structured stages through real backend workflows (Risk Agent evaluation, alert drafting, coordinator approvals, and request intake).

### `GET /simulation`
Retrieves the active simulation stage, metadata, and operational statistics with an empty `events` list.

### `POST /simulation/next`
Advances the scenario by one stage, executes the corresponding real backend handler, and returns the updated state with human-readable `events`.
- **Error (`409 Conflict`)**: Returned if already at terminal stage 5:
  ```json
  {
    "detail": "Simulation is already at stage 5 (final stage). Reset to start over."
  }
  ```

### `POST /simulation/reset`
Resets the simulation to Stage 1 ("Normal conditions"), restoring all warehouse inventories to 100%, resetting regions to `LOW` risk and unflooded, and clearing operational alerts, requests, and deliveries. (Citizen subscriptions are kept intact).

### Response Schema (`200 OK`)
*(Returned by `GET /simulation`, `POST /simulation/next`, and `POST /simulation/reset`)*

```json
{
  "stage": 2,
  "total_stages": 5,
  "name": "Heavy rainfall forecast",
  "description": "The Risk Agent flags regions. Warnings are drafted for the coordinator.",
  "can_advance": true,
  "label": "Illustrative simulation, not a live emergency feed.",
  "stats": {
    "highest_risk": {
      "region_id": 1,
      "region": "Zone A - Riverside",
      "risk_level": "SEVERE"
    },
    "regions": [
      {
        "id": 1,
        "name": "Zone A - Riverside",
        "risk_level": "SEVERE",
        "rainfall_mm": 90.0,
        "is_flooded": false
      },
      {
        "id": 2,
        "name": "Zone B - Central Lowlands",
        "risk_level": "HIGH",
        "rainfall_mm": 70.0,
        "is_flooded": false
      },
      {
        "id": 3,
        "name": "Zone C - Eastern Uplands",
        "risk_level": "MODERATE",
        "rainfall_mm": 40.0,
        "is_flooded": false
      }
    ],
    "open_requests": 0,
    "pending_alerts": 2,
    "sent_alerts": 1,
    "stock_remaining_pct": 100.0
  },
  "events": [
    "Zone A - Riverside risk is now SEVERE",
    "Zone B - Central Lowlands risk is now HIGH",
    "Zone C - Eastern Uplands risk is now MODERATE",
    "Urgent warning drafted for Zone A - Riverside, awaiting approval",
    "Warning drafted for Zone B - Central Lowlands, awaiting approval",
    "Advisory sent for Zone C - Eastern Uplands"
  ]
}
```
