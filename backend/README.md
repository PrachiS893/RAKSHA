# Raksha Backend

Raksha is a multi-agent AI system backend for flood risk warning, emergency request triage, and relief coordination.
It exposes a clean, well-documented FastAPI REST API designed for human coordinator oversight and frontend integration.

## Setup Instructions

### Prerequisites
- Python 3.11+

### Windows (PowerShell)
```powershell
# 1. Navigate to backend directory
cd backend

# 2. Create virtual environment
py -3 -m venv .venv

# 3. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r requirements.txt

# 5. Copy environment variables
Copy-Item .env.example .env
```

### macOS / Linux (Bash)
```bash
# 1. Navigate to backend directory
cd backend

# 2. Create virtual environment
python3 -m venv .venv

# 3. Activate virtual environment
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Copy environment variables
cp .env.example .env
```

## Database & Seeding

The application uses SQLModel with SQLite (`raksha.db`).

> [!IMPORTANT]
> **Database Recreation Note**: Step B6 added `is_flooded` to `region` and `simulation_state`. Step B7 added `approved_at` to `alert` and `recipient`, `detail` to `delivery`. Step B8 added `need_summary`, `triage_source`, `needs_review`, and `score_breakdown` to `request`. Step B9 added `households_estimate` to `region` and `distance_km`, `partial`, `unmet_quantity`, `reason`, `approval_required`, `approved_by`, `approved_at`, `created_at` to `assignment`. Step B10 adds the `hazard_zone` table and `route` JSON column to `assignment`. To apply schema updates in your development environment, delete `raksha.db` and re-seed:
> ```powershell
> Remove-Item raksha.db -ErrorAction SilentlyContinue
> python -m app.seed
> ```

- **Automatic Seeding (`AUTO_SEED`)**: By default, `AUTO_SEED=true` is set in `.env`. On application startup, if the database is unseeded (0 regions), demo regions, warehouses, inventory, and subscriptions are populated automatically.
- **Manual / Re-seeding**: To explicitly reset and seed the demo data at any time, run:
  ```bash
  python -m app.seed
  ```
  This clears all existing rows in foreign-key-safe order and re-inserts the demo data idempotently. If `DEMO_TELEGRAM_CHAT_ID` is set in `.env`, `"Demo Citizen 1"` is linked to that chat ID on seed.

## Risk Scoring & Risk Agent (B4 & B5)

> [!NOTE]
> **Risk estimates are a demo heuristic, not an official flood forecast.**

### The Golden Rule
The LLM only writes concise explanatory text (`reason` and recommended `action`). The risk level **ALWAYS** comes from the pure Python function `calculate_risk`. The LLM never decides, changes, or overrides a risk level or number.

### Risk Calculation Formula
$$\text{adjusted\_mm} = \text{rainfall\_mm} \times (0.5 + \text{clamped\_vulnerability})$$
where `vulnerability` is clamped between `0.0` and `1.0`.

### Thresholds Table
| Adjusted Rainfall Range | Risk Level | Meaning | Default Action |
|---|---|---|---|
| `< 25.0 mm` | **LOW** | Minimal flood hazard | No action needed; keep monitoring. |
| `25.0 mm <= x < 65.0 mm` | **MODERATE** | Watch advisories | Issue an advisory and keep monitoring. |
| `65.0 mm <= x < 115.0 mm` | **HIGH** | Significant flood risk | Prepare emergency supplies and draft a warning. |
| `>= 115.0 mm` | **SEVERE** | Extreme flood conditions | Prepare supplies, stage rescue boats and draft an urgent warning. |

### Weather Data Source & Caching
- **Attribution**: *Weather data by Open-Meteo.com* (free for non-commercial use, no API key required).
- Fetches 48h hourly precipitation from `https://api.open-meteo.com/v1/forecast` and computes the next 24-hour total starting from the current UTC hour.
- **Cache**: Successful API responses are cached as JSON in `WEATHER_CACHE_DIR` (default: `data/weather_cache/`) by rounded coordinates.
- **Resilience**: If the API call fails or times out (`WEATHER_TIMEOUT_SECONDS`, default: 8s), the service retries once, then serves from local cache with source `"cache"`. If no cache exists, it falls back to 0.0 mm with source `"unavailable"` without raising errors to callers.
- **Simulator Override**: Passing `override_mm` bypasses the network entirely and returns source `"simulated"`.

### LLM Integration (Groq)
- Uses Groq's OpenAI-compatible API directly with `httpx` (`POST https://api.groq.com/openai/v1/chat/completions`).
- Obtain an API key from [console.groq.com/keys](https://console.groq.com/keys).
- Model: `LLM_MODEL` (default: `"openai/gpt-oss-20b"`).
- Settings: `LLM_API_KEY` (empty by default), `LLM_MODEL`, `LLM_ENABLED` (default: `true`), `LLM_TIMEOUT_SECONDS` (default: `10`).
- If `LLM_ENABLED=false`, `LLM_API_KEY` is empty, or LLM call fails validation, the system falls back seamlessly to deterministic template explanations without crashing.
- Structured outputs use `response_format: {"type": "json_schema", ...}` with automatic fallback to `{"type": "json_object"}` if the model does not support native schema parsing.

## Notification Service & Disaster Alerts (B7)

The Notification Service generates, deduplicates, and dispatches multi-channel disaster warnings to citizen feeds and subscribers.

> [!NOTE]
> Telegram messages are labelled `[DEMO - simulated scenario]`. Simulated SMS is logged only in the database; nothing real is sent over cellular networks.

### Alert Rules & Coordinator Approvals
| Risk Level | Alert Level | Level Label | Requires Coordinator Approval | Default Action |
|---|---|---|---|---|
| **LOW** | *None* | *None* | N/A | No alert issued |
| **MODERATE** | **ADVISORY** | Advisory | **No (Auto-approved)** | Auto-sent to citizen feed & subscribers |
| **HIGH** | **WARNING** | Warning | **Yes (Coordinator required)** | Held in `/alerts/pending` until approved |
| **SEVERE** | **URGENT** | Urgent warning | **Yes (Coordinator required)** | Held in `/alerts/pending` until approved |

- **Deduplication**: Duplicate assessments at the same or lower severity are ignored. If a higher-severity alert is drafted, it supersedes previous draft alerts for the region.
- **Auditing**: Every alert records `approved_by` and `approved_at` timestamps upon dispatch.

### Telegram Setup (Optional)
To send live messages to Telegram during demonstrations:
1. Add your bot token to `.env`: `TELEGRAM_BOT_TOKEN="<your-bot-token>"`.
2. Add your chat ID to `.env`: `DEMO_TELEGRAM_CHAT_ID="<your-chat-id>"`.
3. Re-seed the database: `python -m app.seed`. (This connects "Demo Citizen 1" in Zone A to your chat).
4. Verify connection safely with `POST /dev/telegram-test?chat_id=<your-chat-id>`.

## Flood Simulator (B6)

> **Disclaimer**: *Illustrative simulation, not a live emergency feed.*

The simulator advances a multi-stage flood emergency scenario using real backend modules—including the Risk Agent, Notification Service alert drafting, coordinator approvals, and shared request intake.

### Simulation Stages
| Stage | Name | Description | Backend Actions Triggered |
|---|---|---|---|
| **1** | **Normal conditions** | Risk is low everywhere. No alerts, no requests, stock at 100%. | Baseline initial state or after reset. |
| **2** | **Heavy rainfall forecast** | The Risk Agent flags regions. Warnings are drafted for the coordinator. | Runs Risk Agent across all regions with Stage 2 rainfall; auto-dispatches Zone C Advisory, drafts Zone A Urgent and Zone B Warning. |
| **3** | **Flood begins** | Flooding starts in the lowest zones, hazard zones activate, and four emergency requests arrive. | Marks Zone A and B as `is_flooded: true`; activates 2 simulated hazard zones; updates rainfall (no duplicate alerts created); ingests 4 sample citizen requests via `create_request`. |
| **4** | **Triage and allocation** | Requests are ranked and supplies are recommended. | Runs Triage Agent (`on_stage_4`), scoring and ranking all 4 emergency requests; runs Relief Agent to generate proposed supply allocations from nearest warehouses. |
| **5** | **Routes and approval** | Safe delivery routes are shown and the coordinator approves the plan. | Computes safe delivery routes for all assignments avoiding active hazard zones (`on_stage_5`); coordinator approves the plan. |

### Stage Rainfall & Risk Outputs
| Region | Vulnerability | Stage 2 Rainfall | Stage 2 Risk | Stage 3 Rainfall | Stage 3 Risk | Stage 3 Flooded? |
|---|---|---|---|---|---|---|
| **Zone A - Bharalumukh** | `0.9` | 90 mm (adj. 126 mm) | **SEVERE** | 110 mm (adj. 154 mm) | **SEVERE** | **Yes** |
| **Zone B - Beltola** | `0.6` | 70 mm (adj. 77 mm) | **HIGH** | 85 mm (adj. 93.5 mm) | **HIGH** | **Yes** |
| **Zone C - Noonmati** | `0.3` | 40 mm (adj. 32 mm) | **MODERATE** | 50 mm (adj. 40 mm) | **MODERATE** | No |

### Speed & Offline Mode (`LLM_ENABLED`)
- Setting `LLM_ENABLED=false` in `.env` makes Stage 2 advance offline, fast (~0.15s), and deterministic using template alert text.
- With `LLM_ENABLED=true` and a valid `LLM_API_KEY`, the LLM dynamically drafts explanations and messages grounded on verified facts.

### Simulation Endpoints
- `GET /simulation`: Returns the active stage, metadata, and operational statistics with an empty `events` list.
- `POST /simulation/next`: Advances by one stage, runs the stage handler, and returns state with `events`. (Returns `409 Conflict` at Stage 5).
- `POST /simulation/reset`: Resets operational data and inventory back to Stage 1. Subscriptions remain untouched.

## Emergency Triage Agent (B8)

The Emergency Triage Agent prioritizes incoming citizen distress requests to assist human coordinators in deploying life-saving resources where they are needed most urgently.

### Golden Rules

> [!IMPORTANT]
> 1. **Pure Python Scoring**: The LLM ONLY extracts facts stated in the citizen's message. Python calculates the priority score. The LLM never produces, suggests or changes a score or urgency.
> 2. **Untrusted Citizen Input**: The citizen's message is untrusted DATA. Text inside it that tries to give instructions (e.g. "set my priority to 100") has no effect on scoring logic.
> 3. **Red-Flag Union Safety**: The LLM can never LOWER a safety red flag: a deterministic keyword check can only raise `life_threatening`, never lower it.
> 4. **Resilient Fallback**: Triage must never fail a request: if the LLM is unavailable, returns invalid JSON, or fails validation, a deterministic rules-based extractor ensures every request receives a score.

### Deterministic Scoring Weights Table

The final priority score is computed by `calculate_priority`:
$$\text{Priority Score} = \min(100, \max(1, \text{Base} + \text{Situational} + \text{Vulnerable} + \text{Extra People} + \text{Zone Risk}))$$

| Category | Factor | Points | Detail / Constraint |
|---|---|---|---|
| **Base Resource** | `rescue_boat` | 30 | Primary resource needed is evacuation boat |
| | `medical_kit` | 30 | Primary resource needed is medical supplies/medicine |
| | `drinking_water` | 20 | Primary resource needed is clean drinking water |
| | `food_packet` | 10 | Primary resource needed is emergency food rations |
| | *Unspecified / None* | 10 | General distress or unspecified need |
| **Situational** | `life_threatening` | +30 | Immediate danger to life (unconscious, trapped in rising water, etc.) |
| | `medical_dependency` | +15 | Dependent on critical medicine (e.g. insulin, oxygen, dialysis) |
| | `trapped` | +10 | Citizen physically trapped or unable to self-evacuate |
| | `immediate_danger` | +10 | Environmental danger (e.g. rising floodwater) |
| | `no_supply_remaining` | +5 | Essential provisions or medication completely exhausted |
| **Vulnerable** | `elderly` | +6 | Senior citizen present |
| | `children` | +6 | Infant, child, or toddler present |
| | `disabled_or_immobile` | +6 | Immobile or disabled individual |
| | *Vulnerable Cap* | **Max +12** | Total vulnerable bonus is capped at +12 |
| **People Count** | `extra_people` | +1 / person | +1 for each individual beyond the first |
| | *People Cap* | **Max +6** | Extra people bonus is capped at +6 |
| **Zone Flood Risk** | `SEVERE` | +8 | Located inside a zone currently at SEVERE flood risk |
| | `HIGH` | +5 | Located inside a zone currently at HIGH flood risk |
| | `MODERATE` | +2 | Located inside a zone currently at MODERATE flood risk |
| | `LOW` / Outside | +0 | Low risk zone or outside known flood polygons |

### Urgency Bands

| Priority Score Range | Urgency Band | Operational Meaning |
|---|---|---|
| `75 - 100` | **CRITICAL** | Immediate life threat; dispatch rescue boats or critical medical kits immediately. |
| `55 - 74` | **HIGH** | Urgent distress; rapid dispatch required within next priority wave. |
| `30 - 54` | **MEDIUM** | Standard relief need; schedule for regular delivery run. |
| `1 - 29` | **LOW** | Non-critical assistance; fulfilled as supplies and routing permit. |

### Configuration (`TRIAGE_ON_SUBMIT`)

- In `.env`, `TRIAGE_ON_SUBMIT` defaults to `true`. Newly created requests via `POST /requests` are triaged immediately upon intake.
- When `TRIAGE_ON_SUBMIT=false`, requests arrive in `status: "received"` and remain unscored until `POST /triage/run` is called or Stage 4 of the simulator advances.

### Triage Endpoints

- `POST /triage/run?force=<bool>`: Evaluates un-scored requests (or all requests if `force=true`) and returns the sorted ranking list.
- `POST /requests/{id}/triage`: Re-runs triage on a specific request and updates its record in the database.
- `POST /dev/triage-preview`: Previews extraction features and calculated priority score without persisting to the database.

## Relief Supply Coordination (B9)

> [!IMPORTANT]
> **Golden Rules**:
> 1. **Allocation is a RECOMMENDATION**: Inventory stock is only deducted when a human coordinator approves an assignment.
> 2. **Priority-First Nearest Fulfillment**: Highest priority requests are served first; each request is paired with the nearest warehouse that has enough stock.
> 3. **Illustrative Planning Assumptions**: Shortage numbers and regional demand are illustrative demo planning assumptions, not real forecasts.

### Shortage Prediction Assumptions

Demand for each region is calculated deterministically from:
$$\text{demand} = \text{households\_estimate} \times \text{AFFECTED\_FRACTION}[\text{risk\_level}] \times \text{PER\_AFFECTED\_HOUSEHOLD}[\text{resource}]$$

#### Affected Households Fraction by Risk Level
| Risk Level | Affected Fraction | Description |
|---|---|---|
| `LOW` | `0.00` (0%) | Normal baseline; no relief aid required |
| `MODERATE` | `0.02` (2%) | Localized waterlogging; minor aid required |
| `HIGH` | `0.08` (8%) | Severe street flooding; significant aid required |
| `SEVERE` | `0.20` (20%) | Critical inundation; widespread emergency supplies required |

#### Planning Supply Requirements per Affected Household
| Resource | Standard Unit | Quantity per Affected Household |
|---|---|---|
| `drinking_water` | litres | 10 L |
| `food_packet` | packets | 3 packets |
| `medical_kit` | kits | 0.05 kits (1 kit per 20 households) |
| `rescue_boat` | boats | 0.04 boats (1 boat per 25 households) |

#### Deficit Status Thresholds
- **`SHORTAGE`**: Total stockpile across warehouses < Predicted demand.
- **`TIGHT`**: Stockpile is sufficient for predicted demand, but less than $1.25 \times \text{demand}$ (`TIGHT_MARGIN = 1.25`).
- **`OK`**: Stockpile $\ge 1.25 \times \text{demand}$ (or demand is 0).

### Request Allocation Rules

When allocating supplies to distress calls (`POST /relief/plan`):
1. **Quantity Needed**:
   - `drinking_water`: 3 litres per person (`people_count` None counts as 1).
   - `food_packet`: 3 packets per person (`people_count` None counts as 1).
   - `medical_kit`: 1 kit per request.
   - `rescue_boat`: 1 boat per request.
2. **Warehouse Selection**:
   - Warehouses with stock $\ge$ quantity needed are ranked by Haversine distance from the request coordinates (ties broken by larger remaining stock).
   - If no single warehouse has enough stock, a partial assignment is created from the warehouse with the highest available stock, and the remaining need is flagged in `unmet_quantity`.
   - If all warehouses have 0 stock, the request is marked unmet with `status: "shortage"`.
   - Requests without an identified resource are marked unmet with reason *"Needs coordinator decision: no clear resource identified"*.

### Human Coordinator Approval Flow

1. **Plan Generation (`POST /relief/plan`)**: Proposes assignments and stores them with `approved: false`. Warehouse inventory is **unchanged**.
2. **Individual Approval (`POST /assignments/{id}/approve`)**: Coordinator approves an assignment. Warehouse inventory is decremented, assignment marked `approved: true`, and request status becomes `"assigned"`.
3. **Plan Approval (`POST /plan/approve`)**: Approves all pending assignments in a single atomic transaction. Fails with 409 if any warehouse inventory is insufficient.
4. **Dispatch (`POST /assignments/{id}/dispatch`)**: Transitions request status to `"on_the_way"`. (Requires prior approval).

## Safe Delivery Routing (B10)

Raksha plans relief delivery routes that connect assigned warehouses to distress request locations while dynamically avoiding active flood hazard zones.

> [!IMPORTANT]
> **Golden Rules**:
> 1. **Hazard Avoidance & Verification**: Routes avoid simulated hazard zones where the routing provider allows it, and **EVERY** route is re-checked with Shapely. If a route crosses an active hazard zone, it is flagged (`hazard_free: false`), never hidden.
> 2. **Mandatory Disclaimer**: Raksha cannot guarantee real road safety without verified real-time road data. Every route response carries the disclaimer: *"Route avoids simulated hazard zones only. Real road conditions are not verified."*
> 3. **Never Crash the Demo**: The routing service uses a multi-tier fallback chain (Cache -> ORS -> OSRM -> Stale Cache -> Straight-line) protected by a circuit breaker so the demo never fails.
> 4. **Key Security**: Never log or store the ORS API key. It goes only in the `Authorization` header. On failures, log only HTTP status codes or exception class names.

### The 5-Stage Routing Provider Chain

1. **Exact Local Cache (`data/route_cache/`)**:
   - Cache keys are MD5 hashes computed from start coordinates, end coordinates, routing profile, and sorted active hazard IDs.
   - If an exact match exists on disk, it is served immediately (`provider: "cache"`).
2. **OpenRouteService (ORS)**:
   - When `ORS_API_KEY` is configured in `.env`, calls `POST https://api.openrouteservice.org/v2/directions/{profile}/geojson`.
   - Sends active hazard zone bounding polygons via `options.avoid_polygons` (GeoJSON MultiPolygon) so the ORS routing engine computes a route circumventing flooded areas.
3. **Open Source Routing Machine (OSRM)**:
   - Public demo endpoint (`https://router.project-osrm.org/route/v1/driving/{lon},{lat};{lon},{lat}?alternatives=true&geometries=geojson&overview=full`).
   - Requests primary and alternative routes, evaluates each candidate route against active hazard polygons with Shapely, and selects the first hazard-free path.
4. **Stale Local Cache**:
   - If live API calls fail or time out, Raksha looks for any existing cached route between the same coordinate endpoints (even if active hazards have changed).
   - If found, it returns the geometry with `provider: "stale_cache"` and a warning.
5. **Straight-Line Fallback**:
   - If no provider or cached route is available, constructs a 2-point direct GeoJSON LineString between the warehouse and the request location.
   - Computes Haversine distance and estimates duration at an assumed average speed of 30 km/h, returning `provider: "straight_line"` with a warning explaining that live routing was unavailable.

### Circuit Breaker (`ProviderBreaker`)
- Each live provider (ORS and OSRM) is wrapped in a stateful circuit breaker.
- After 2 consecutive failures (`FAILURE_THRESHOLD = 2`), the breaker trips into OPEN state for 60 seconds (`COOLDOWN_SECONDS = 60.0`).
- While open, requests fail fast to the next provider in the chain without stalling on timeouts.

### Shapely Hazard Audit
- Every route candidate from any provider is audited using Shapely:
  $$\text{LineString}(\text{coords}) \cap \text{MultiPolygon}(\text{active hazards})$$
- If the intersection length exceeds $0.00005^\circ$ (~5.5 meters), the intersecting hazard names are recorded in `crossed_hazards` and `hazard_free` is set to `false`.
- Touch points or zero-length intersections are filtered out so that touching the boundary does not raise false positives.

### Pre-warming the Route Cache
- You can pre-warm the route cache ahead of a presentation by stepping through the simulator (`POST /simulation/next` through Stage 5) or by testing routes with `POST /dev/route-test`.
- Once cached, routes are served instantly offline without network access.

### Frontend Coordinate Convention Note
- **GeoJSON**: `[longitude, latitude]` per the GeoJSON RFC 7946 standard.
- **Leaflet**: Expects `[latitude, longitude]`. When rendering with Leaflet, swap coordinates:
  ```js
  const latLngs = route.geometry.coordinates.map(([lon, lat]) => [lat, lon]);
  ```

## Development Verification Endpoints (Dev Mode Only)

When `APP_ENV=dev`, additional development verification routes are mounted under `/dev`:
- `POST /dev/risk-check/{region_id}?rainfall_mm=<float>&persist=<bool>`: Runs the Risk Agent for a region.
- `POST /dev/draft-alert/{region_id}?rainfall_mm=<float>`: Runs Risk Agent and processes reports through the Notification Service.
- `POST /dev/llm-test`: Tests Groq structured output generation safely without exposing the API key.
- `POST /dev/telegram-test?chat_id=<str>`: Tests sending a message via Telegram Bot API safely without exposing tokens.
- `POST /dev/triage-preview`: Previews extraction features and calculated priority score without persisting to the database.
- `POST /dev/route-test`: Tests routing between warehouse and coordinates or arbitrary start/end points without modifying assignments.
- `POST /dev/hazards/activate?active=<bool>`: Toggles active status of all simulated hazard zones.
- `GET /dev/agent-logs?limit=20`: Returns recent audit logs created by agents (`agent_logs` table).

## Running the API

Start the development server with hot reload:
```bash
uvicorn app.main:app --reload
```

- API Base URL: `http://127.0.0.1:8000`
- Interactive Swagger UI: `http://127.0.0.1:8000/docs`
- Health Check: `http://127.0.0.1:8000/health`
- Complete Schema Contracts: See [`API_SHAPES.md`](./API_SHAPES.md)

## Running Tests

Execute the automated test suite (in-memory SQLite with StaticPool):
```bash
pytest
```
