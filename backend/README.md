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

- **Automatic Seeding (`AUTO_SEED`)**: By default, `AUTO_SEED=true` is set in `.env`. On application startup, if the database is unseeded (0 regions), demo regions, warehouses, inventory, and subscriptions are populated automatically.
- **Manual / Re-seeding**: To explicitly reset and seed the demo data at any time, run:
  ```bash
  python -m app.seed
  ```
  This clears all existing rows in foreign-key-safe order and re-inserts the demo data idempotently.

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

### LLM Integration (`google-genai`)
- Uses Google Gemini via the `google-genai` SDK (`LLM_MODEL`, default: `"gemini-2.5-flash"`).
- If `LLM_API_KEY` is empty, missing, or fails validation, the system falls back seamlessly to deterministic template explanations without crashing.

## Development Verification Endpoints (Dev Mode Only)

When `APP_ENV=dev`, additional development verification routes are mounted under `/dev`:
- `POST /dev/risk-check/{region_id}?rainfall_mm=<float>&persist=<bool>`: Runs the Risk Agent for a region.
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
