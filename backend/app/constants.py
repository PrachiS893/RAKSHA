"""Constants and Enums for the Raksha backend."""

from enum import Enum


class RiskLevel(str, Enum):
    """Flood risk levels for geographical regions."""

    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class AlertLevel(str, Enum):
    """Severity levels for emergency alerts."""

    ADVISORY = "ADVISORY"
    WARNING = "WARNING"
    URGENT = "URGENT"


class AlertStatus(str, Enum):
    """Lifecycle status for regional alerts."""

    DRAFT = "draft"
    APPROVED = "approved"
    SENT = "sent"
    SUPERSEDED = "superseded"


class RequestStatus(str, Enum):
    """Lifecycle status for emergency triage requests."""

    RECEIVED = "received"
    PRIORITIZED = "prioritized"
    ASSIGNED = "assigned"
    ON_THE_WAY = "on_the_way"
    SHORTAGE = "shortage"


class Urgency(str, Enum):
    """Triage urgency classification."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Resource(str, Enum):
    """Relief inventory resource types."""

    DRINKING_WATER = "drinking_water"
    FOOD_PACKET = "food_packet"
    MEDICAL_KIT = "medical_kit"
    RESCUE_BOAT = "rescue_boat"


class Channel(str, Enum):
    """Communication channels for dispatching alerts."""

    IN_APP = "in_app"
    TELEGRAM = "telegram"
    SMS_SIM = "sms_sim"


# Mapping from resource identifier to human-readable quantity unit
RESOURCE_UNITS: dict[str, str] = {
    Resource.DRINKING_WATER.value: "litres",
    Resource.FOOD_PACKET.value: "packets",
    Resource.MEDICAL_KIT.value: "kits",
    Resource.RESCUE_BOAT.value: "boats",
}
