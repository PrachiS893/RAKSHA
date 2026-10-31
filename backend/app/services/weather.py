"""Weather service integrating Open-Meteo API with local caching and fallbacks."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Literal, Optional
import httpx
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


class RainfallForecast(BaseModel):
    """24-hour rainfall forecast data model."""

    lat: float
    lon: float
    rainfall_mm_24h: float
    source: Literal["open-meteo", "cache", "simulated", "unavailable"]
    fetched_at: datetime


def _get_cache_path(lat: float, lon: float) -> Path:
    """Get cache file path for given coordinates."""
    cache_dir = Path(settings.WEATHER_CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{round(lat, 2):.2f}_{round(lon, 2):.2f}.json"
    return cache_dir / filename


def _parse_hourly_precipitation(data: dict[str, Any], current_utc: datetime) -> float:
    """Calculate 24-hour total precipitation starting from the current UTC hour."""
    hourly = data.get("hourly")
    if not isinstance(hourly, dict):
        raise ValueError("Missing 'hourly' object in Open-Meteo response")

    times = hourly.get("time")
    precipitations = hourly.get("precipitation")

    if not isinstance(times, list) or not isinstance(precipitations, list):
        raise ValueError("Invalid 'time' or 'precipitation' lists in Open-Meteo response")

    if len(times) != len(precipitations) or len(times) == 0:
        raise ValueError("Mismatched or empty hourly data in Open-Meteo response")

    current_hour_str = current_utc.strftime("%Y-%m-%dT%H:00")
    start_idx = 0
    found = False

    for i, t in enumerate(times):
        if str(t) >= current_hour_str:
            start_idx = i
            found = True
            break

    if not found:
        start_idx = max(0, len(times) - 24)

    window = precipitations[start_idx : start_idx + 24]
    total_mm = sum(float(p) for p in window if p is not None)
    return round(total_mm, 2)


def get_rainfall_forecast(
    lat: float, lon: float, override_mm: Optional[float] = None
) -> RainfallForecast:
    """Fetch 24-hour rainfall forecast for given latitude and longitude.

    If override_mm is provided, returns simulated forecast without making network calls.
    Otherwise attempts to call Open-Meteo with one retry. Falls back to cached data
    if network/parsing fails, or returns 0.0 with source 'unavailable' if no cache exists.
    """
    now = datetime.now(timezone.utc)

    # 1. Override check (used by simulation scenarios)
    if override_mm is not None:
        return RainfallForecast(
            lat=lat,
            lon=lon,
            rainfall_mm_24h=round(float(override_mm), 2),
            source="simulated",
            fetched_at=now,
        )

    cache_file = _get_cache_path(lat, lon)

    # 2. Network call with one retry
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "precipitation",
        "forecast_days": 2,
        "timezone": "UTC",
    }

    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=settings.WEATHER_TIMEOUT_SECONDS) as client:
                response = client.get(OPEN_METEO_URL, params=params)
                response.raise_for_status()
                data = response.json()
                total_mm = _parse_hourly_precipitation(data, now)

                # Write successful result to cache
                cache_payload = {
                    "lat": lat,
                    "lon": lon,
                    "rainfall_mm_24h": total_mm,
                    "fetched_at": now.isoformat(),
                }
                cache_file.write_text(json.dumps(cache_payload), encoding="utf-8")

                return RainfallForecast(
                    lat=lat,
                    lon=lon,
                    rainfall_mm_24h=total_mm,
                    source="open-meteo",
                    fetched_at=now,
                )
        except Exception as exc:
            logger.warning(
                "Open-Meteo API attempt %d/%d failed for (%f, %f): %s",
                attempt,
                max_attempts,
                lat,
                lon,
                exc,
            )

    # 3. Fallback to cache if available
    if cache_file.exists():
        try:
            cached_data = json.loads(cache_file.read_text(encoding="utf-8"))
            cached_time = datetime.fromisoformat(cached_data["fetched_at"])
            logger.info("Loaded rainfall forecast from cache for (%f, %f)", lat, lon)
            return RainfallForecast(
                lat=lat,
                lon=lon,
                rainfall_mm_24h=float(cached_data["rainfall_mm_24h"]),
                source="cache",
                fetched_at=cached_time,
            )
        except Exception as exc:
            logger.warning("Failed to read weather cache file %s: %s", cache_file, exc)

    # 4. Final fallback when unavailable
    logger.error("Weather data unavailable for (%f, %f). Falling back to 0.0 mm", lat, lon)
    return RainfallForecast(
        lat=lat,
        lon=lon,
        rainfall_mm_24h=0.0,
        source="unavailable",
        fetched_at=now,
    )
