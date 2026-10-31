"""Tests for the weather forecast service integration, caching, and fallbacks."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import MagicMock
import httpx
import pytest
from app.config import settings
from app.services.weather import get_rainfall_forecast


@pytest.fixture(name="weather_cache")
def weather_cache_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set WEATHER_CACHE_DIR to an isolated temporary folder."""
    cache_dir = tmp_path / "weather_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "WEATHER_CACHE_DIR", str(cache_dir))
    return cache_dir


def test_weather_override_simulated(weather_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify override_mm returns simulated source without initiating network calls."""

    def fail_if_network_called(*args, **kwargs):
        raise AssertionError("Network should not be contacted when override_mm is provided")

    monkeypatch.setattr(httpx.Client, "get", fail_if_network_called)

    forecast = get_rainfall_forecast(lat=26.18, lon=91.74, override_mm=55.4)
    assert forecast.source == "simulated"
    assert forecast.rainfall_mm_24h == 55.4
    assert forecast.lat == 26.18
    assert forecast.lon == 91.74


def test_weather_open_meteo_success_parsed_and_cached(
    weather_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify Open-Meteo success sums 24h precipitation from current hour and writes cache."""
    now = datetime.now(timezone.utc)
    base_time = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=6)

    times: list[str] = []
    precipitations: list[float] = []

    # Generate 48 hours of data
    for i in range(48):
        t = base_time + timedelta(hours=i)
        times.append(t.strftime("%Y-%m-%dT%H:00"))
        # Set 1.5 mm per hour for the next 24 hours starting from now, 0 elsewhere
        if t >= now.replace(minute=0, second=0, microsecond=0) and len(
            [x for x in times if x >= now.strftime("%Y-%m-%dT%H:00")]
        ) <= 24:
            precipitations.append(1.5)
        else:
            precipitations.append(0.0)

    mock_payload = {
        "latitude": 26.18,
        "longitude": 91.74,
        "hourly": {
            "time": times,
            "precipitation": precipitations,
        },
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_payload
    mock_response.raise_for_status.return_value = None

    def mock_get(*args, **kwargs):
        return mock_response

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    forecast = get_rainfall_forecast(lat=26.18, lon=91.74)
    assert forecast.source == "open-meteo"
    # 24 hours * 1.5 mm = 36.0 mm
    assert forecast.rainfall_mm_24h == 36.0

    # Verify cache file was written
    cache_files = list(weather_cache.glob("*.json"))
    assert len(cache_files) == 1
    cached_content = json.loads(cache_files[0].read_text(encoding="utf-8"))
    assert cached_content["rainfall_mm_24h"] == 36.0


def test_weather_failed_call_returns_cached_data(
    weather_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify network failure falls back to cached forecast data if present."""
    cached_timestamp = "2026-10-31T05:00:00+00:00"
    cache_file = weather_cache / "26.18_91.74.json"
    cache_file.write_text(
        json.dumps(
            {
                "lat": 26.18,
                "lon": 91.74,
                "rainfall_mm_24h": 42.0,
                "fetched_at": cached_timestamp,
            }
        ),
        encoding="utf-8",
    )

    def mock_failed_get(*args, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx.Client, "get", mock_failed_get)

    forecast = get_rainfall_forecast(lat=26.18, lon=91.74)
    assert forecast.source == "cache"
    assert forecast.rainfall_mm_24h == 42.0
    assert forecast.fetched_at == datetime.fromisoformat(cached_timestamp)


def test_weather_failed_call_no_cache_returns_unavailable(
    weather_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify network failure with no cache returns 0.0 with source 'unavailable'."""

    def mock_timeout_get(*args, **kwargs):
        raise httpx.TimeoutException("Connection timed out")

    monkeypatch.setattr(httpx.Client, "get", mock_timeout_get)

    forecast = get_rainfall_forecast(lat=26.18, lon=91.74)
    assert forecast.source == "unavailable"
    assert forecast.rainfall_mm_24h == 0.0
