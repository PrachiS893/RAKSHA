# Raksha Backend API Shapes & Documentation

This document describes the exact JSON schemas and endpoint request/response contracts for the Raksha backend. It is designed for frontend developers building the React coordination dashboard.

---

## General Conventions

- **Simulation Flag**: All demo data is marked with simulation indicators (e.g., `"is_simulated_flood": true`, `"simulated": true`).
- **Coordinates**:
  - In GeoJSON (`Polygon`, `LineString`, `MultiPolygon`): `[longitude, latitude]` pairs.
  - In flat objects/fields: `"lat"` (latitude) and `"lon"` (longitude).
  - **Leaflet Note**: Frontend libraries like Leaflet expect `[latitude, longitude]`. When rendering GeoJSON geometries, reverse the coordinate pairs: `([lon, lat]) => [lat, lon]`.
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
    "households_estimate": 400,
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

### `GET /resources/shortages`
Calculates predicted supply deficits across all monitored flood zones based on current risk levels and household population estimates.

> **Disclaimer**: *Illustrative planning assumptions for the demo, not a real forecast.*

#### Response (`200 OK`)
```json
{
  "as_of": "2026-10-31T15:30:00Z",
  "simulated": true,
  "assumptions": "Illustrative planning assumptions for the demo, not a real forecast.",
  "resources": [
    {
      "resource": "drinking_water",
      "unit": "litres",
      "stock": 550,
      "predicted_demand": 1340,
      "shortfall": 790,
      "status": "SHORTAGE",
      "by_region": [
        {
          "region_id": 1,
          "region": "Zone A - Riverside",
          "demand": 800.0
        },
        {
          "region_id": 2,
          "region": "Zone B - Central Lowlands",
          "demand": 480.0
        },
        {
          "region_id": 3,
          "region": "Zone C - Eastern Uplands",
          "demand": 60.0
        }
      ]
    },
    {
      "resource": "food_packet",
      "unit": "packets",
      "stock": 360,
      "predicted_demand": 402,
      "shortfall": 42,
      "status": "SHORTAGE",
      "by_region": [
        {
          "region_id": 1,
          "region": "Zone A - Riverside",
          "demand": 240.0
        },
        {
          "region_id": 2,
          "region": "Zone B - Central Lowlands",
          "demand": 144.0
        },
        {
          "region_id": 3,
          "region": "Zone C - Eastern Uplands",
          "demand": 18.0
        }
      ]
    },
    {
      "resource": "medical_kit",
      "unit": "kits",
      "stock": 8,
      "predicted_demand": 7,
      "shortfall": 0,
      "status": "TIGHT",
      "by_region": [
        {
          "region_id": 1,
          "region": "Zone A - Riverside",
          "demand": 4.0
        },
        {
          "region_id": 2,
          "region": "Zone B - Central Lowlands",
          "demand": 2.4
        },
        {
          "region_id": 3,
          "region": "Zone C - Eastern Uplands",
          "demand": 0.3
        }
      ]
    },
    {
      "resource": "rescue_boat",
      "unit": "boats",
      "stock": 3,
      "predicted_demand": 6,
      "shortfall": 3,
      "status": "SHORTAGE",
      "by_region": [
        {
          "region_id": 1,
          "region": "Zone A - Riverside",
          "demand": 3.2
        },
        {
          "region_id": 2,
          "region": "Zone B - Central Lowlands",
          "demand": 1.9
        },
        {
          "region_id": 3,
          "region": "Zone C - Eastern Uplands",
          "demand": 0.2
        }
      ]
    }
  ]
}
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
    "ref": "R1",
    "text": "My father is diabetic and has run out of insulin. He is very weak.",
    "name": "Amit",
    "lat": 26.175,
    "lon": 91.745,
    "region_id": 1,
    "region_name": "Zone A - Riverside",
    "status": "prioritized",
    "resource_needed": "medical_kit",
    "people_count": 1,
    "urgency": "CRITICAL",
    "priority_score": 88,
    "reason": "Life-threatening situation reported; Critical medical dependency; Zone at SEVERE flood risk.",
    "need_summary": "Father is diabetic and has run out of insulin.",
    "triage_source": "llm",
    "needs_review": false,
    "score_breakdown": [
      {
        "factor": "base_resource",
        "points": 30,
        "detail": "Primary resource needed: medical_kit"
      },
      {
        "factor": "life_threatening",
        "points": 30,
        "detail": "Immediate threat to life reported"
      },
      {
        "factor": "medical_dependency",
        "points": 15,
        "detail": "Dependent on critical medication or medical equipment"
      },
      {
        "factor": "no_supply_remaining",
        "points": 5,
        "detail": "Essential provisions completely exhausted"
      },
      {
        "factor": "zone_risk",
        "points": 8,
        "detail": "Located in zone evaluated at SEVERE flood risk"
      }
    ],
    "created_at": "2026-10-31T07:30:00Z"
  }
]
```

---

### `POST /requests`
Submit a new citizen distress call. The system automatically performs a point-in-polygon check against flood zones to assign `region_id`. If the location is outside all zones, `region_id` is set to `null`.

If `TRIAGE_ON_SUBMIT=true` (default setting in `.env`), the Triage Agent automatically evaluates the message upon submission, setting `status: "prioritized"` and populating `priority_score`, `urgency`, `reason`, `need_summary`, and `score_breakdown`. When `TRIAGE_ON_SUBMIT=false`, the request is saved with `status: "received"` and triage fields set to `null` until a triage run is triggered.

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
  "ref": "R2",
  "text": "We have had no drinking water since last night. 6 people in the house.",
  "name": "Rina",
  "lat": 26.135,
  "lon": 91.735,
  "region_id": 2,
  "region_name": "Zone B - Central Lowlands",
  "status": "prioritized",
  "resource_needed": "drinking_water",
  "people_count": 6,
  "urgency": "MEDIUM",
  "priority_score": 35,
  "reason": "Needs Drinking Water; 6 people affected; Provisions exhausted.",
  "need_summary": "We have had no drinking water since last night. 6 people in the house.",
  "triage_source": "llm",
  "needs_review": false,
  "score_breakdown": [
    {
      "factor": "base_resource",
      "points": 20,
      "detail": "Primary resource needed: drinking_water"
    },
    {
      "factor": "no_supply_remaining",
      "points": 5,
      "detail": "Essential provisions completely exhausted"
    },
    {
      "factor": "extra_people",
      "points": 5,
      "detail": "6 people affected (+5 for individuals beyond the first)"
    },
    {
      "factor": "zone_risk",
      "points": 5,
      "detail": "Located in zone evaluated at HIGH flood risk"
    }
  ],
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

## 6. Emergency Triage & Prioritization (B8)

### `POST /triage/run`
Executes the Triage Agent across citizen requests.
- When `force=false` (default): Triages only un-scored requests (`status: "received"`).
- When `force=true`: Re-evaluates and re-scores all requests in the database.
Returns the count of requests triaged in this run, along with the complete ranked list sorted by `priority_score desc, created_at asc, id asc`.

#### Query Parameters
- `force` (boolean, optional, default: `false`)

#### Response (`200 OK`)
```json
{
  "triaged": 4,
  "ranked": [
    {
      "request_id": 3,
      "ref": "R3",
      "urgency": "CRITICAL",
      "priority_score": 100,
      "reason": "Life-threatening situation reported; Person trapped; Immediate danger from rising water.",
      "resource_needed": "rescue_boat",
      "people_count": 1,
      "need_summary": "Elderly woman trapped on ground floor, water is waist-deep.",
      "source": "llm",
      "needs_review": false,
      "breakdown": [
        {
          "factor": "base_resource",
          "points": 30,
          "detail": "Primary resource needed: rescue_boat"
        },
        {
          "factor": "life_threatening",
          "points": 30,
          "detail": "Immediate threat to life reported"
        },
        {
          "factor": "trapped",
          "points": 10,
          "detail": "Person trapped or unable to self-evacuate"
        },
        {
          "factor": "immediate_danger",
          "points": 10,
          "detail": "Immediate environmental danger (e.g. rising floodwater)"
        },
        {
          "factor": "vulnerable_people",
          "points": 12,
          "detail": "Vulnerable people present (elderly, disabled/immobile)"
        },
        {
          "factor": "zone_risk",
          "points": 8,
          "detail": "Located in zone evaluated at SEVERE flood risk"
        }
      ]
    },
    {
      "request_id": 2,
      "ref": "R2",
      "urgency": "CRITICAL",
      "priority_score": 88,
      "reason": "Life-threatening situation reported; Critical medical dependency; Zone at SEVERE flood risk.",
      "resource_needed": "medical_kit",
      "people_count": 1,
      "need_summary": "Father is diabetic and has run out of insulin.",
      "source": "llm",
      "needs_review": false,
      "breakdown": [
        {
          "factor": "base_resource",
          "points": 30,
          "detail": "Primary resource needed: medical_kit"
        },
        {
          "factor": "life_threatening",
          "points": 30,
          "detail": "Immediate threat to life reported"
        },
        {
          "factor": "medical_dependency",
          "points": 15,
          "detail": "Dependent on critical medication or medical equipment"
        },
        {
          "factor": "no_supply_remaining",
          "points": 5,
          "detail": "Essential provisions completely exhausted"
        },
        {
          "factor": "zone_risk",
          "points": 8,
          "detail": "Located in zone evaluated at SEVERE flood risk"
        }
      ]
    }
  ]
}
```

---

### `POST /requests/{id}/triage`
Re-runs the Triage Agent on a single emergency request by ID, updates its DB record with fresh scoring and breakdown, and returns the resulting `TriageResult`. Returns `404 Not Found` if the request does not exist.

#### Response (`200 OK`)
```json
{
  "request_id": 2,
  "ref": "R2",
  "urgency": "CRITICAL",
  "priority_score": 88,
  "reason": "Life-threatening situation reported; Critical medical dependency; Zone at SEVERE flood risk.",
  "resource_needed": "medical_kit",
  "people_count": 1,
  "need_summary": "Father is diabetic and has run out of insulin.",
  "source": "llm",
  "needs_review": false,
  "breakdown": [
    {
      "factor": "base_resource",
      "points": 30,
      "detail": "Primary resource needed: medical_kit"
    },
    {
      "factor": "life_threatening",
      "points": 30,
      "detail": "Immediate threat to life reported"
    },
    {
      "factor": "medical_dependency",
      "points": 15,
      "detail": "Dependent on critical medication or medical equipment"
    },
    {
      "factor": "no_supply_remaining",
      "points": 5,
      "detail": "Essential provisions completely exhausted"
    },
    {
      "factor": "zone_risk",
      "points": 8,
      "detail": "Located in zone evaluated at SEVERE flood risk"
    }
  ]
}
```

---

### `POST /dev/triage-preview` (Dev Mode Only)
Preview triage feature extraction and priority score calculation without modifying database state.

#### Request Body
```json
{
  "text": "My father is diabetic and has run out of insulin. He is very weak.",
  "region_id": 1
}
```

#### Response (`200 OK`)
```json
{
  "result": {
    "request_id": 0,
    "ref": "R0",
    "urgency": "CRITICAL",
    "priority_score": 88,
    "reason": "Life-threatening situation reported; Critical medical dependency; Zone at SEVERE flood risk.",
    "resource_needed": "medical_kit",
    "people_count": 1,
    "need_summary": "Father is diabetic and has run out of insulin.",
    "source": "llm",
    "needs_review": false,
    "breakdown": [...]
  },
  "features": {
    "resource_needed": "medical_kit",
    "people_count": 1,
    "life_threatening": true,
    "life_threat_evidence": "insulin",
    "trapped": false,
    "immediate_danger": false,
    "medical_dependency": true,
    "no_supply_remaining": true,
    "elderly": false,
    "children": false,
    "disabled_or_immobile": false,
    "need_summary": "Father is diabetic and has run out of insulin."
  }
}
```

---

## 7. Relief Supply Coordination (B9)

> **Golden Rules**:
> - Allocation is a RECOMMENDATION. Stock is only reduced when a human coordinator approves.
> - Highest priority requests are served first; each request gets the NEAREST warehouse with sufficient stock.
> - Shortage numbers are demo planning assumptions, not real forecasts.

### Assignment Schema
```json
{
  "id": 1,
  "request_id": 3,
  "request_ref": "R3",
  "region_name": "Zone A - Riverside",
  "priority_score": 100,
  "urgency": "CRITICAL",
  "resource": "rescue_boat",
  "unit": "boats",
  "quantity": 1,
  "warehouse_id": 1,
  "warehouse": "Warehouse A - North Depot",
  "distance_km": 2.8,
  "partial": false,
  "unmet_quantity": 0,
  "reason": "Nearest warehouse with enough stock (2.8 km). Priority 100, CRITICAL.",
  "route": null,
  "approval_required": true,
  "approved": false,
  "approved_by": null,
  "approved_at": null,
  "request_status": "prioritized"
}
```

### `POST /relief/plan`
Generates an idempotent relief allocation recommendation without reducing warehouse inventory.
- **Query Parameter**: `triage_first` (`bool`, default: `true`). When true, runs triage on un-scored requests first.

### `GET /relief/plan`
Retrieves the active relief plan without re-evaluating allocations.

#### Response (`200 OK`)
```json
{
  "generated_at": "2026-10-31T15:30:00Z",
  "summary": {
    "requests_considered": 4,
    "assigned": 4,
    "partial": 0,
    "unmet": 0,
    "awaiting_approval": 4,
    "approved": 0
  },
  "assignments": [
    {
      "id": 1,
      "request_id": 3,
      "request_ref": "R3",
      "region_name": "Zone A - Riverside",
      "priority_score": 100,
      "urgency": "CRITICAL",
      "resource": "rescue_boat",
      "unit": "boats",
      "quantity": 1,
      "warehouse_id": 1,
      "warehouse": "Warehouse A - North Depot",
      "distance_km": 2.8,
      "partial": false,
      "unmet_quantity": 0,
      "reason": "Nearest warehouse with enough stock (2.8 km). Priority 100, CRITICAL.",
      "route": null,
      "approval_required": true,
      "approved": false,
      "approved_by": null,
      "approved_at": null,
      "request_status": "prioritized"
    }
  ],
  "unmet": []
}
```

### `POST /assignments/{id}/approve`
Approves a proposed assignment, decrements warehouse inventory, and transitions request status to `"assigned"`.
- **Request Body** (optional):
  ```json
  {
    "approved_by": "coordinator"
  }
  ```
- **Error (`404 Not Found`)**: If assignment does not exist.
- **Error (`409 Conflict`)**: If assignment is already approved or warehouse inventory is insufficient.

### `POST /plan/approve`
Approves all unapproved proposed assignments in a single transaction (all-or-nothing).
- **Request Body** (optional): `{"approved_by": "coordinator"}`
- **Response (`200 OK`)**:
  ```json
  {
    "approved": 4,
    "assignments": [ ... ]
  }
  ```
- **Error (`409 Conflict`)**: If any warehouse has insufficient inventory for the cumulative plan (nothing changes).

### `POST /assignments/{id}/dispatch`
Dispatches an approved assignment, transitioning request status to `"on_the_way"`.
- **Error (`409 Conflict`)**: If assignment is not yet approved.

---

## 8. Hazard Zones & Safe Route Planning (B10)

Raksha plans safe relief delivery routes connecting assigned warehouses to citizen distress locations while avoiding active flood hazard zones.

> **Disclaimer**: *Route avoids simulated hazard zones only. Real road conditions are not verified.*

### `GET /hazards`
Lists all simulated hazard zones, their bounding polygons, and active status.

#### Response (`200 OK`)
```json
[
  {
    "id": 1,
    "name": "Flooded underpass - north approach",
    "description": "Simulated flooded underpass blocking north approach",
    "polygon": {
      "type": "Polygon",
      "coordinates": [
        [
          [91.738, 26.188],
          [91.744, 26.188],
          [91.744, 26.194],
          [91.738, 26.194],
          [91.738, 26.188]
        ]
      ]
    },
    "active": true,
    "simulated": true
  },
  {
    "id": 2,
    "name": "River overflow - south approach",
    "description": "Simulated river overflow blocking south approach",
    "polygon": {
      "type": "Polygon",
      "coordinates": [
        [
          [91.732, 26.172],
          [91.738, 26.172],
          [91.738, 26.178],
          [91.732, 26.178],
          [91.732, 26.172]
        ]
      ]
    },
    "active": true,
    "simulated": true
  }
]
```

### Route Object Shape
When computed, an assignment's `"route"` property contains the following GeoJSON LineString and metadata:

```json
{
  "geometry": {
    "type": "LineString",
    "coordinates": [
      [91.74, 26.21],
      [91.7412, 26.2051],
      [91.7385, 26.1950],
      [91.735, 26.185]
    ]
  },
  "distance_km": 4.8,
  "duration_min": 7.1,
  "provider": "ors",
  "hazard_free": true,
  "avoided_hazards": [
    "Flooded underpass - north approach"
  ],
  "crossed_hazards": [],
  "warning": null,
  "attribution": "openrouteservice.org | © OpenStreetMap contributors",
  "disclaimer": "Route avoids simulated hazard zones only. Real road conditions are not verified.",
  "computed_at": "2026-10-31T15:30:00Z"
}
```

#### Route Providers
- `"cache"`: Exact cached route hit for the coordinate pair and active hazard set.
- `"ors"`: OpenRouteService API with active hazard zones passed to `options.avoid_polygons`.
- `"osrm"`: OSRM alternative routes evaluated against active hazards via Shapely.
- `"stale_cache"`: Cached route served during upstream outage (with warning).
- `"straight_line"`: Direct fallback LineString during complete outage (with warning).

### `POST /relief/routes`
Computes safe delivery routes for all assignments that do not yet have one (or for all assignments when `force=true`).

- **Query Parameters**:
  - `force` (bool, default `false`): When `true`, recomputes routes even if already assigned.
- **Response (`200 OK`)**:
  ```json
  {
    "computed": 4,
    "hazard_free": 4,
    "has_warnings": 0,
    "assignments": [
      {
        "id": 1,
        "request_id": 3,
        "request_ref": "R3",
        "region_name": "Zone A - Riverside",
        "priority_score": 100,
        "urgency": "CRITICAL",
        "resource": "rescue_boat",
        "unit": "boats",
        "quantity": 1,
        "warehouse_id": 1,
        "warehouse": "Warehouse A - North Depot",
        "distance_km": 21.3,
        "partial": false,
        "unmet_quantity": 0,
        "reason": "Nearest warehouse with enough stock (21.3 km). Priority 100, CRITICAL.",
        "route": { ... },
        "approval_required": true,
        "approved": false,
        "approved_by": null,
        "approved_at": null,
        "request_status": "prioritized"
      }
    ]
  }
  ```

### `POST /assignments/{id}/route`
Computes or refreshes the delivery route for a single assignment.

- **Query Parameters**:
  - `force` (bool, default `false`): When `true`, forces recalculation even if a route exists.
- **Response (`200 OK`)**: Updated `AssignmentRead` object with nested `route`.
- **Error (`404 Not Found`)**: If assignment does not exist.

---

## 9. Simulation State & Controls

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
    "stock_remaining_pct": 100.0,
    "assignments_pending": 0,
    "hazards_active": 0
  },
  "events": [
    "Zone A - Riverside risk is now SEVERE",
    "Zone B - Central Lowlands risk is now HIGH",
    "Zone C - Eastern Uplands risk is now MODERATE",
    "Urgent warning drafted for Zone A - Riverside, awaiting approval",
    "Warning drafted for Zone B - Central Lowlands, awaiting approval",
    "Advisory sent for Zone C - Eastern Uplands",
    "Shortage predicted: drinking_water (SHORTAGE, stock 550 vs expected demand 1340)",
    "Shortage predicted: food_packet (SHORTAGE, stock 360 vs expected demand 402)",
    "Shortage predicted: medical_kit (TIGHT, stock 8 vs expected demand 7)",
    "Shortage predicted: rescue_boat (SHORTAGE, stock 3 vs expected demand 6)",
    "Relief Agent proposed 4 assignments (awaiting coordinator approval)"
  ]
}
```

### Stage 3 & 5 Simulator Events Example
In Stage 3 ("Flood begins"):
```json
"events": [
  "Zone A - Riverside is now flooded",
  "Zone B - Central Lowlands is now flooded",
  "2 simulated hazard zones activated: Flooded underpass - north approach, River overflow - south approach",
  "Emergency request R1 received from Zone A - Riverside: drinking_water",
  "Emergency request R2 received from Zone B - Central Lowlands: medical_kit",
  "Emergency request R3 received from Zone A - Riverside: rescue_boat",
  "Emergency request R4 received from Zone A - Riverside: food_packet"
]
```

In Stage 5 ("Routes and approval"):
```json
"events": [
  "Routes computed for 4 assignments",
  "4 of 4 routes avoid all hazard zones (ors)"
]
```

---

## 10. Development Verification Endpoints (Dev Mode Only)

When `APP_ENV=dev`, additional development verification routes are mounted under `/dev`:
- `POST /dev/risk-check/{region_id}?rainfall_mm=<float>&persist=<bool>`: Runs the Risk Agent for a region.
- `POST /dev/draft-alert/{region_id}?rainfall_mm=<float>`: Runs Risk Agent and processes reports through the Notification Service.
- `POST /dev/llm-test`: Tests Groq structured output generation safely without exposing the API key.
- `POST /dev/telegram-test?chat_id=<str>`: Tests sending a message via Telegram Bot API safely without exposing tokens.
- `POST /dev/triage-preview`: Previews extraction features and calculated priority score without persisting to the database.
- `POST /dev/route-test`: Tests routing between warehouse and coordinates or arbitrary start/end points without modifying assignments.
- `POST /dev/hazards/activate?active=<bool>`: Toggles active status of all simulated hazard zones.
- `GET /dev/agent-logs?limit=20`: Returns recent audit logs created by agents (`agent_logs` table).
