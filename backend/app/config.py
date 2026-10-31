"""Application configuration settings for Raksha backend."""

from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file located at the backend root
BASE_DIR: Path = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


@dataclass
class Settings:
    """Application settings loaded from environment variables with safe defaults."""

    DATABASE_URL: str = os.getenv("DATABASE_URL") or "sqlite:///./raksha.db"
    FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN") or "http://localhost:5173"
    LLM_API_KEY: str = os.getenv("LLM_API_KEY") or ""
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN") or ""
    ORS_API_KEY: str = os.getenv("ORS_API_KEY") or ""
    APP_ENV: str = os.getenv("APP_ENV") or "dev"
    AUTO_SEED: bool = (os.getenv("AUTO_SEED", "true").lower() in ("true", "1", "yes"))
    LLM_MODEL: str = os.getenv("LLM_MODEL") or "openai/gpt-oss-20b"
    LLM_ENABLED: bool = (os.getenv("LLM_ENABLED", "true").lower() in ("true", "1", "yes"))
    LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS") or "10")
    DEMO_TELEGRAM_CHAT_ID: str = os.getenv("DEMO_TELEGRAM_CHAT_ID") or ""
    TRIAGE_ON_SUBMIT: bool = (os.getenv("TRIAGE_ON_SUBMIT", "true").lower() in ("true", "1", "yes"))
    WEATHER_CACHE_DIR: str = os.getenv("WEATHER_CACHE_DIR") or "data/weather_cache"
    WEATHER_TIMEOUT_SECONDS: int = int(os.getenv("WEATHER_TIMEOUT_SECONDS") or "8")
    ROUTING_ENABLED: bool = (os.getenv("ROUTING_ENABLED", "true").lower() in ("true", "1", "yes"))
    ROUTING_PROFILE: str = os.getenv("ROUTING_PROFILE") or "driving-car"
    ROUTING_TIMEOUT_SECONDS: int = int(os.getenv("ROUTING_TIMEOUT_SECONDS") or "6")
    ROUTE_CACHE_DIR: str = os.getenv("ROUTE_CACHE_DIR") or "data/route_cache"
    OSRM_BASE_URL: str = os.getenv("OSRM_BASE_URL") or "https://router.project-osrm.org"


settings: Settings = Settings()
