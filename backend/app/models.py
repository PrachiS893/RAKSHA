"""Database models for Raksha backend using SQLModel."""

from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import Column, DateTime, JSON
from sqlmodel import Field, SQLModel
from app.constants import AlertStatus, RequestStatus, RiskLevel


class Region(SQLModel, table=True):
    """Geographical region monitored for flood risk and emergency triage."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    polygon: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    center_lat: float
    center_lon: float
    vulnerability: float
    risk_level: str = Field(default=RiskLevel.LOW.value)
    rainfall_mm: float = Field(default=0.0)
    is_simulated_flood: bool = Field(default=True)


class Warehouse(SQLModel, table=True):
    """Relief supply warehouse depot."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    lat: float
    lon: float


class Inventory(SQLModel, table=True):
    """Resource stockpile row allocated to a specific warehouse."""

    id: Optional[int] = Field(default=None, primary_key=True)
    warehouse_id: int = Field(foreign_key="warehouse.id")
    resource: str
    quantity: int
    initial_quantity: int


class Request(SQLModel, table=True):
    """Citizen distress and relief aid request."""

    id: Optional[int] = Field(default=None, primary_key=True)
    text: str
    name: Optional[str] = Field(default=None, nullable=True)
    lat: float
    lon: float
    region_id: Optional[int] = Field(default=None, foreign_key="region.id", nullable=True)
    status: str = Field(default=RequestStatus.RECEIVED.value)
    resource_needed: Optional[str] = Field(default=None, nullable=True)
    people_count: Optional[int] = Field(default=None, nullable=True)
    urgency: Optional[str] = Field(default=None, nullable=True)
    priority_score: Optional[int] = Field(default=None, nullable=True)
    reason: Optional[str] = Field(default=None, nullable=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Assignment(SQLModel, table=True):
    """Resource allocation and routing assignment connecting a warehouse to a request."""

    id: Optional[int] = Field(default=None, primary_key=True)
    request_id: int = Field(foreign_key="request.id")
    warehouse_id: int = Field(foreign_key="warehouse.id")
    resource: str
    quantity: int
    route: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    approved: bool = Field(default=False)


class Alert(SQLModel, table=True):
    """Public warning or safety advisory issued for a region."""

    id: Optional[int] = Field(default=None, primary_key=True)
    region_id: int = Field(foreign_key="region.id")
    level: str
    message: str
    status: str = Field(default=AlertStatus.DRAFT.value)
    approved_by: Optional[str] = Field(default=None, nullable=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Subscription(SQLModel, table=True):
    """Citizen subscription to regional emergency alert notifications."""

    id: Optional[int] = Field(default=None, primary_key=True)
    region_id: int = Field(foreign_key="region.id")
    name: str
    telegram_chat_id: Optional[str] = Field(default=None, nullable=True)


class Delivery(SQLModel, table=True):
    """Multi-channel dispatch delivery attempt log for an alert."""

    id: Optional[int] = Field(default=None, primary_key=True)
    alert_id: int = Field(foreign_key="alert.id")
    channel: str
    status: str
    sent_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class AgentLog(SQLModel, table=True):
    """Audit log entry capturing internal agent decisions and telemetry."""

    id: Optional[int] = Field(default=None, primary_key=True)
    agent: str
    message: str
    payload: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
