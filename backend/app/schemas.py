from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator
from app.constants import RiskLevel


def format_iso_utc(dt: datetime) -> str:
    """Format a datetime as a standard UTC ISO 8601 string with 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


class Coordinates(BaseModel):
    """Geographical coordinate pair."""

    lat: float
    lon: float


# Region Schemas
class RegionRead(BaseModel):
    """Response schema for region metadata and polygon boundary."""

    id: int
    name: str
    polygon: dict[str, Any]
    center: Coordinates
    vulnerability: float
    risk_level: str
    rainfall_mm: float
    is_flooded: bool = False
    is_simulated_flood: bool


# Warehouse Schemas
class InventoryItemRead(BaseModel):
    """Response schema for a single inventory stockpile item."""

    resource: str
    unit: str
    quantity: int
    initial_quantity: int


class WarehouseRead(BaseModel):
    """Response schema for warehouse details with nested inventory."""

    id: int
    name: str
    lat: float
    lon: float
    inventory: list[InventoryItemRead]
    simulated: bool = True


# Request Schemas
class RequestCreate(BaseModel):
    """Payload schema for submitting an emergency request."""

    text: str
    lat: float
    lon: float
    name: Optional[str] = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        """Validate text length after trimming."""
        trimmed = v.strip()
        if len(trimmed) < 3 or len(trimmed) > 1000:
            raise ValueError("text must be between 3 and 1000 characters after trimming")
        return trimmed

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        """Validate latitude bounds."""
        if v < -90.0 or v > 90.0:
            raise ValueError("lat must be between -90 and 90")
        return v

    @field_validator("lon")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        """Validate longitude bounds."""
        if v < -180.0 or v > 180.0:
            raise ValueError("lon must be between -180 and 180")
        return v


class RequestRead(BaseModel):
    """Response schema for an emergency request."""

    id: int
    text: str
    name: Optional[str] = None
    lat: float
    lon: float
    region_id: Optional[int] = None
    region_name: Optional[str] = None
    status: str
    resource_needed: Optional[str] = None
    people_count: Optional[int] = None
    urgency: Optional[str] = None
    priority_score: Optional[int] = None
    reason: Optional[str] = None
    created_at: str


# Alert Schemas
class DeliveryRead(BaseModel):
    """Response schema for an alert delivery attempt."""

    channel: str
    status: str
    recipient: Optional[str] = None
    detail: Optional[str] = None
    sent_at: Optional[str] = None


class AlertRead(BaseModel):
    """Response schema for a flood alert message."""

    id: int
    region_id: int
    region_name: str
    level: str
    level_label: str
    message: str
    status: str
    requires_approval: bool
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    created_at: str
    deliveries: list[DeliveryRead] = []


class AlertApproveRequest(BaseModel):
    """Payload schema for approving a draft alert."""

    approved_by: str = "coordinator"
    message: Optional[str] = None


# Subscription Schemas
class SubscriptionCreate(BaseModel):
    """Payload schema for creating an alert subscription."""

    region_id: int
    name: str
    telegram_chat_id: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate non-empty name."""
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("name cannot be empty")
        return trimmed


class SubscriptionRead(BaseModel):
    """Response schema for an alert subscription."""

    id: int
    region_id: int
    region_name: str
    name: str
    telegram_chat_id: Optional[str] = None


# Risk Agent Schemas
class RiskExplanation(BaseModel):
    """Structured LLM explanation output schema."""

    reason: str
    action: str

    @field_validator("reason")
    @classmethod
    def validate_reason_length(cls, v: str) -> str:
        """Validate that reason is at most 30 words."""
        if len(v.strip().split()) > 30:
            raise ValueError("reason must be 30 words or fewer")
        return v.strip()

    @field_validator("action")
    @classmethod
    def validate_action_length(cls, v: str) -> str:
        """Validate that action is at most 20 words."""
        if len(v.strip().split()) > 20:
            raise ValueError("action must be 20 words or fewer")
        return v.strip()


class RiskReport(BaseModel):
    """Comprehensive risk assessment report produced by the Risk Agent."""

    region_id: int
    region: str
    risk_level: RiskLevel
    rainfall_mm: float
    rainfall_source: str
    reason: str
    action: str
    generated_at: datetime
    simulated: bool = True


# Simulation Schemas
class SimulationHighestRisk(BaseModel):
    """Highest risk summary details across all monitored regions."""

    region_id: int
    region: str
    risk_level: str


class SimulationRegionStat(BaseModel):
    """Region summary metrics within simulation state."""

    id: int
    name: str
    risk_level: str
    rainfall_mm: float
    is_flooded: bool


class SimulationStats(BaseModel):
    """Aggregated operational metrics for the active simulation stage."""

    highest_risk: Optional[SimulationHighestRisk] = None
    regions: list[SimulationRegionStat]
    open_requests: int
    pending_alerts: int
    sent_alerts: int
    stock_remaining_pct: float


class SimulationStateRead(BaseModel):
    """Current state and execution status of the flood scenario simulation."""

    stage: int
    total_stages: int = 5
    name: str
    description: str
    can_advance: bool
    label: str = "Illustrative simulation, not a live emergency feed."
    stats: SimulationStats
    events: list[str] = Field(default_factory=list)
