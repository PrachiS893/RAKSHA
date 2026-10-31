"""Health check router for service verification."""

from typing import Any
from fastapi import APIRouter
from app.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check() -> dict[str, Any]:
    """Return health status and environment metadata."""
    return {
        "status": "ok",
        "service": "raksha-backend",
        "version": "0.1.0",
        "env": settings.APP_ENV,
    }
