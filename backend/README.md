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
> **Database Recreation Note**: Step B6 adds `is_flooded` to `region` and adds the `simulation_state` table. Step B7 added `approved_at` to `alert` and `recipient`, `detail` to `delivery`. To apply schema updates in your development environment, delete `raksha.db` and re-seed:
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
| **3** | **Flood begins** | Flooding starts in the lowest zones and four emergency requests arrive. | Marks Zone A and B as `is_flooded: true`; updates rainfall (no duplicate alerts created); ingests 4 sample citizen requests via `create_request`. |
| **4** | **Triage and allocation** | Requests are ranked and supplies are recommended. | Placeholder hook (`on_stage_4`) for Steps B8 (Triage) & B9 (Relief Allocation). |
| **5** | **Routes and approval** | Safe delivery routes are shown and the coordinator approves the plan. | Placeholder hook (`on_stage_5`) for Step B10 (Safe routing & Coordinator Plan). |

### Stage Rainfall & Risk Outputs
| Region | Vulnerability | Stage 2 Rainfall | Stage 2 Risk | Stage 3 Rainfall | Stage 3 Risk | Stage 3 Flooded? |
|---|---|---|---|---|---|---|
| **Zone A - Riverside** | `0.9` | 90 mm (adj. 126 mm) | **SEVERE** | 110 mm (adj. 154 mm) | **SEVERE** | **Yes** |
| **Zone B - Central Lowlands** | `0.6` | 70 mm (adj. 77 mm) | **HIGH** | 85 mm (adj. 93.5 mm) | **HIGH** | **Yes** |
| **Zone C - Eastern Uplands** | `0.3` | 40 mm (adj. 32 mm) | **MODERATE** | 50 mm (adj. 40 mm) | **MODERATE** | No |

### Speed & Offline Mode (`LLM_ENABLED`)
- Setting `LLM_ENABLED=false` in `.env` makes Stage 2 advance offline, fast (~0.15s), and deterministic using template alert text.
- With `LLM_ENABLED=true` and a valid `LLM_API_KEY`, the LLM dynamically drafts explanations and messages grounded on verified facts.

### Simulation Endpoints
- `GET /simulation`: Returns the active stage, metadata, and operational statistics with an empty `events` list.
- `POST /simulation/next`: Advances by one stage, runs the stage handler, and returns state with `events`. (Returns `409 Conflict` at Stage 5).
- `POST /simulation/reset`: Resets operational data and inventory back to Stage 1. Subscriptions remain untouched.

## Development Verification Endpoints (Dev Mode Only)

When `APP_ENV=dev`, additional development verification routes are mounted under `/dev`:
- `POST /dev/risk-check/{region_id}?rainfall_mm=<float>&persist=<bool>`: Runs the Risk Agent for a region.
- `POST /dev/draft-alert/{region_id}?rainfall_mm=<float>`: Runs Risk Agent and processes reports through the Notification Service.
- `POST /dev/llm-test`: Tests Groq structured output generation safely without exposing the API key.
- `POST /dev/telegram-test?chat_id=<str>`: Tests sending a message via Telegram Bot API safely without exposing tokens.
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
