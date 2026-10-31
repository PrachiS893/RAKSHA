"""Main entry point for the Raksha FastAPI backend."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select
from app.config import settings
from app.db import create_db_and_tables, engine
from app.models import Region
from app.routers.alerts import router as alerts_router
from app.routers.dev import router as dev_router
from app.routers.health import router as health_router
from app.routers.regions import router as regions_router
from app.routers.requests import router as requests_router
from app.routers.subscriptions import router as subscriptions_router
from app.routers.warehouses import router as warehouses_router
from app.seed import seed_database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Handle application startup and shutdown lifecycle events."""
    create_db_and_tables()
    if settings.AUTO_SEED:
        with Session(engine) as session:
            existing_regions = len(session.exec(select(Region)).all())
            if existing_regions == 0:
                seed_database(session)
    yield


app = FastAPI(
    title="Raksha API",
    description=(
        "Predict. Prepare. Respond. Flood-response multi-agent backend. "
        "All flood zones, inventory and requests are SIMULATED demo data."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS middleware
cors_origins: list[str] = list(
    dict.fromkeys([settings.FRONTEND_ORIGIN, "http://127.0.0.1:5173"])
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health_router)
app.include_router(regions_router)
app.include_router(warehouses_router)
app.include_router(requests_router)
app.include_router(alerts_router)
app.include_router(subscriptions_router)

# Dev-only verification endpoints (only mounted in dev mode)
if settings.APP_ENV == "dev":
    app.include_router(dev_router)
