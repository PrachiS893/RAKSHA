"""Global pytest configuration and test environment isolation."""

import os
import tempfile
from pathlib import Path
import httpx
import pytest

# 1. At the very top of tests/conftest.py, BEFORE anything imports the app,
# set these environment variables to safe test values so python-dotenv does not
# override them from .env.
_test_weather_cache = Path(tempfile.gettempdir()) / "raksha_pytest_weather_cache"
_test_weather_cache.mkdir(parents=True, exist_ok=True)
_test_route_cache = Path(tempfile.gettempdir()) / "raksha_pytest_route_cache"
_test_route_cache.mkdir(parents=True, exist_ok=True)

os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["DEMO_TELEGRAM_CHAT_ID"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["ORS_API_KEY"] = ""
os.environ["LLM_ENABLED"] = "false"
os.environ["APP_ENV"] = "dev"
os.environ["AUTO_SEED"] = "false"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["WEATHER_CACHE_DIR"] = str(_test_weather_cache)
os.environ["ROUTE_CACHE_DIR"] = str(_test_route_cache)
os.environ["ROUTING_ENABLED"] = "true"


@pytest.fixture(autouse=True)
def block_real_network_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """Autouse fixture that blocks all real outbound network requests via httpx.

    Any unmocked httpx request raises RuntimeError('real network call in a test: <url>').
    FastAPI TestClient uses _TestClientTransport and is unaffected.
    Tests mocking httpx.Client or transport bypass this handler.
    """

    def _blocked_handle_request(self, request: httpx.Request, *args, **kwargs):
        raise RuntimeError(f"real network call in a test: {request.url}")

    async def _blocked_handle_async_request(
        self, request: httpx.Request, *args, **kwargs
    ):
        raise RuntimeError(f"real network call in a test: {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked_handle_request)
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", _blocked_handle_async_request
    )


@pytest.fixture(name="client_and_session")
def client_and_session_fixture(
    monkeypatch: pytest.MonkeyPatch,
):
    """Provide TestClient and direct Session on an isolated in-memory SQLite database."""
    from collections.abc import Generator
    from fastapi.testclient import TestClient
    from sqlmodel import Session, SQLModel, create_engine
    from sqlmodel.pool import StaticPool
    from app.agents import risk_agent
    from app.db import get_session
    from app.main import app
    from app.seed import seed_database
    from app.services import alert_drafting, triage_extraction

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)

    with Session(test_engine) as session:
        seed_database(session)

    def get_test_session() -> Generator[Session, None, None]:
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session

    # Prevent external LLM or weather calls during tests
    monkeypatch.setattr(alert_drafting, "generate_json", lambda prompt, schema, system=None: None)
    monkeypatch.setattr(risk_agent, "generate_json", lambda prompt, schema, system=None: None)
    monkeypatch.setattr(triage_extraction, "generate_json", lambda prompt, schema, system=None: None)

    # Clear route cache files between tests for isolation
    route_cache_dir = Path(os.environ.get("ROUTE_CACHE_DIR", str(_test_route_cache)))
    if route_cache_dir.exists():
        for f in route_cache_dir.glob("*.json"):
            try:
                f.unlink()
            except Exception:
                pass

    with TestClient(app) as test_client:
        with Session(test_engine) as db_session:
            yield test_client, db_session

    app.dependency_overrides.clear()
