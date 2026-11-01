"""Main entry point for the Raksha FastAPI backend."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select
from app.config import settings
from app.db import create_db_and_tables, engine
from app.models import Region
from app.routers.agents import router as agents_router
from app.routers.alerts import router as alerts_router
from app.routers.dev import router as dev_router
from app.routers.events import router as events_router
from app.routers.hazards import router as hazards_router
from app.routers.health import router as health_router
from app.routers.regions import router as regions_router
from app.routers.relief import router as relief_router
from app.routers.requests import router as requests_router
from app.routers.resources import router as resources_router
from app.routers.simulation import router as simulation_router
from app.routers.subscriptions import router as subscriptions_router
from app.routers.triage import router as triage_router
from app.routers.warehouses import router as warehouses_router
from app.seed import seed_database

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Handle application startup and shutdown lifecycle events."""
    create_db_and_tables()
    if settings.AUTO_SEED:
        with Session(engine) as session:
            existing_regions = len(session.exec(select(Region)).all())
            if existing_regions == 0:
                seed_database(session)

    scheduler = None
    if settings.RISK_CHECK_INTERVAL_MINUTES > 0:
        from apscheduler.schedulers.background import BackgroundScheduler
        from app.services.scheduler import scheduled_risk_check

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            scheduled_risk_check,
            "interval",
            minutes=settings.RISK_CHECK_INTERVAL_MINUTES,
            id="periodic_risk_check",
        )
        scheduler.start()
        logger.info(
            "Periodic risk check scheduler started (interval: %d min)",
            settings.RISK_CHECK_INTERVAL_MINUTES,
        )

    yield

    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Periodic risk check scheduler stopped")



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
app.include_router(resources_router)
app.include_router(alerts_router)
app.include_router(simulation_router)
app.include_router(subscriptions_router)
app.include_router(triage_router)
app.include_router(relief_router)
app.include_router(hazards_router)
app.include_router(events_router)
app.include_router(agents_router)


# Dev-only verification endpoints (only mounted in dev mode)
if settings.APP_ENV == "dev":
    app.include_router(dev_router)
