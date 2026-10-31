"""Tests for the health check router."""

from fastapi.testclient import TestClient
from app.config import settings
from app.main import app


def test_health_check() -> None:
    """Verify that GET /health returns HTTP 200 and expected payload."""
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "raksha-backend"
        assert data["version"] == "0.1.0"
        assert data["env"] == settings.APP_ENV
