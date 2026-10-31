"""Unit tests for alert message drafting, haversine calculation, and validation guards."""

from collections.abc import Generator
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from app.constants import AlertLevel
from app.models import Region
from app.seed import seed_database
from app.services import alert_drafting
from app.services.alert_drafting import (
    ALERT_TEMPLATES,
    AlertDraft,
    build_facts,
    draft_alert_message,
    nearest_warehouse,
    validate_drafted_message,
)


@pytest.fixture(name="session")
def session_fixture() -> Generator[Session, None, None]:
    """Provide an in-memory SQLite database session seeded with warehouses and regions."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        seed_database(session)
        yield session


def test_nearest_warehouse_picks_closest(session: Session) -> None:
    """Verify haversine distance correctly identifies nearest warehouse to region center."""
    # Zone A center: (26.18, 91.74). Warehouse A is at (26.21, 91.74), distance ~3.3 km
    region_a = session.exec(select(Region).where(Region.name == "Zone A - Riverside")).first()
    assert region_a is not None

    closest, distance_km = nearest_warehouse(session, region_a)
    assert closest.name == "Warehouse A - North Depot"
    assert 3.0 <= distance_km <= 4.0


def test_templates_pass_strict_validation() -> None:
    """Verify all built-in alert templates satisfy length, region name, and number constraints."""
    facts = {
        "region": "Zone A - Riverside",
        "alert_level_label": "Warning",
        "rainfall_mm": 70,
        "nearest_warehouse": "Warehouse A - North Depot",
        "distance_km": 3.3,
    }

    for level, template in ALERT_TEMPLATES.items():
        rendered = template.format(
            region=facts["region"],
            mm=facts["rainfall_mm"],
            warehouse=facts["nearest_warehouse"],
            km=facts["distance_km"],
        )
        assert validate_drafted_message(rendered, facts) is True
        assert len(rendered) <= 320


def test_draft_message_uses_valid_llm_output(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that compliant LLM-generated output is selected over template."""
    facts = {
        "region": "Zone A - Riverside",
        "alert_level_label": "Warning",
        "rainfall_mm": 70,
        "nearest_warehouse": "Warehouse A - North Depot",
        "distance_km": 3.3,
    }

    valid_llm_text = (
        "Flood warning for Zone A: 70 mm of heavy rain expected. "
        "Move belongings to higher ground. Nearest relief point: Warehouse A - North Depot, 3.3 km."
    )
    monkeypatch.setattr(
        alert_drafting,
        "generate_json",
        lambda prompt, schema, system=None: AlertDraft(message=valid_llm_text),
    )

    message, used_llm = draft_alert_message(session, facts, AlertLevel.WARNING)
    assert used_llm is True
    assert message == valid_llm_text


def test_draft_message_falls_back_on_wrong_number(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify fallback to template when LLM text introduces unverified numbers."""
    facts = {
        "region": "Zone A - Riverside",
        "alert_level_label": "Warning",
        "rainfall_mm": 70,
        "nearest_warehouse": "Warehouse A - North Depot",
        "distance_km": 3.3,
    }

    # "in 2 hours" introduces unverified number '2'
    hallucinated_number_text = (
        "Flood warning for Zone A: 70 mm of rain arriving in 2 hours. "
        "Relief point Warehouse A - North Depot is 3.3 km away."
    )
    monkeypatch.setattr(
        alert_drafting,
        "generate_json",
        lambda prompt, schema, system=None: AlertDraft(message=hallucinated_number_text),
    )

    message, used_llm = draft_alert_message(session, facts, AlertLevel.WARNING)
    assert used_llm is False
    assert "about 70 mm" in message
    assert "3.3 km away" in message


def test_draft_message_falls_back_on_missing_region_or_excess_length(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify fallback to template when LLM omits region name or exceeds length."""
    facts = {
        "region": "Zone A - Riverside",
        "alert_level_label": "Urgent warning",
        "rainfall_mm": 120,
        "nearest_warehouse": "Warehouse A - North Depot",
        "distance_km": 3.3,
    }

    # Missing region name
    no_region_text = "Urgent warning: 120 mm rain. Evacuate to Warehouse A - North Depot, 3.3 km away."
    monkeypatch.setattr(
        alert_drafting,
        "generate_json",
        lambda prompt, schema, system=None: AlertDraft(message=no_region_text),
    )

    message, used_llm = draft_alert_message(session, facts, AlertLevel.URGENT)
    assert used_llm is False
    assert "Zone A - Riverside" in message

    # Exceeding 320 characters
    long_text = "URGENT flood warning for Zone A - Riverside: " + ("heavy rain " * 35) + " 120 mm."
    monkeypatch.setattr(
        alert_drafting,
        "generate_json",
        lambda prompt, schema, system=None: AlertDraft(message=long_text),
    )

    message2, used_llm2 = draft_alert_message(session, facts, AlertLevel.URGENT)
    assert used_llm2 is False


def test_draft_message_falls_back_when_llm_returns_none(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify fallback when LLM is disabled or returns None."""
    facts = {
        "region": "Zone B - Central Lowlands",
        "alert_level_label": "Advisory",
        "rainfall_mm": 35,
        "nearest_warehouse": "Warehouse B - Central Depot",
        "distance_km": 3.3,
    }

    monkeypatch.setattr(alert_drafting, "generate_json", lambda prompt, schema, system=None: None)

    message, used_llm = draft_alert_message(session, facts, AlertLevel.ADVISORY)
    assert used_llm is False
    assert "Zone B - Central Lowlands" in message
    assert "about 35 mm" in message


def test_draft_message_urgent_rejects_stay_indoors_and_falls_back(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that URGENT alert rejects stay-in-place phrasing ('stay indoors') and falls back."""
    facts = {
        "region": "Zone A - Riverside",
        "alert_level_label": "Urgent warning",
        "rainfall_mm": 90,
        "nearest_warehouse": "Warehouse A - North Depot",
        "distance_km": 3.3,
    }

    bad_text = (
        "URGENT warning for Zone A: 90 mm rain expected. Please stay indoors and move to higher ground. "
        "Depot: Warehouse A - North Depot is 3.3 km."
    )
    monkeypatch.setattr(
        alert_drafting,
        "generate_json",
        lambda prompt, schema, system=None: AlertDraft(message=bad_text),
    )

    message, used_llm = draft_alert_message(session, facts, AlertLevel.URGENT)
    assert used_llm is False
    assert "URGENT flood warning for Zone A - Riverside" in message


def test_draft_message_urgent_requires_higher_ground(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that URGENT alert without 'higher ground' is rejected and falls back."""
    facts = {
        "region": "Zone A - Riverside",
        "alert_level_label": "Urgent warning",
        "rainfall_mm": 90,
        "nearest_warehouse": "Warehouse A - North Depot",
        "distance_km": 3.3,
    }

    no_higher_ground = (
        "URGENT warning for Zone A: 90 mm rain expected. Stay away from flooded roads. "
        "Depot: Warehouse A - North Depot is 3.3 km."
    )
    monkeypatch.setattr(
        alert_drafting,
        "generate_json",
        lambda prompt, schema, system=None: AlertDraft(message=no_higher_ground),
    )

    message, used_llm = draft_alert_message(session, facts, AlertLevel.URGENT)
    assert used_llm is False
    assert "Move to higher ground now" in message


def test_draft_message_advisory_allows_stay_indoors(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that ADVISORY messages are NOT rejected by the stay-in-place rule."""
    facts = {
        "region": "Zone C - Eastern Uplands",
        "alert_level_label": "Advisory",
        "rainfall_mm": 40,
        "nearest_warehouse": "Warehouse C - East Depot",
        "distance_km": 2.5,
    }

    advisory_with_stay_indoors = (
        "Advisory for Zone C: 40 mm rain forecast. Stay indoors if possible and avoid low-lying areas. "
        "Depot: Warehouse C - East Depot is 2.5 km away."
    )
    monkeypatch.setattr(
        alert_drafting,
        "generate_json",
        lambda prompt, schema, system=None: AlertDraft(message=advisory_with_stay_indoors),
    )

    message, used_llm = draft_alert_message(session, facts, AlertLevel.ADVISORY)
    assert used_llm is True
    assert message == advisory_with_stay_indoors


def test_draft_message_warning_rejects_stay_in_place(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that WARNING messages reject stay-in-place phrasing ('shelter in place')."""
    facts = {
        "region": "Zone B - Central Lowlands",
        "alert_level_label": "Warning",
        "rainfall_mm": 70,
        "nearest_warehouse": "Warehouse B - Central Depot",
        "distance_km": 3.3,
    }

    warning_with_shelter = (
        "Flood warning for Zone B: 70 mm rain expected. Move valuables to higher ground and shelter in place. "
        "Depot: Warehouse B - Central Depot is 3.3 km."
    )
    monkeypatch.setattr(
        alert_drafting,
        "generate_json",
        lambda prompt, schema, system=None: AlertDraft(message=warning_with_shelter),
    )

    message, used_llm = draft_alert_message(session, facts, AlertLevel.WARNING)
    assert used_llm is False
    assert "Flood warning for Zone B - Central Lowlands" in message


def test_draft_message_rejects_evacuate_and_promises(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify rejection of unauthorized 'evacuate' commands or promises like 'help is on the way'."""
    facts = {
        "region": "Zone A - Riverside",
        "alert_level_label": "Urgent warning",
        "rainfall_mm": 90,
        "nearest_warehouse": "Warehouse A - North Depot",
        "distance_km": 3.3,
    }

    # Case 1: unauthorized evacuate
    evac_text = (
        "URGENT warning for Zone A: 90 mm rain. Evacuate immediately to higher ground! "
        "Depot: Warehouse A - North Depot is 3.3 km."
    )
    monkeypatch.setattr(
        alert_drafting,
        "generate_json",
        lambda prompt, schema, system=None: AlertDraft(message=evac_text),
    )
    msg1, used1 = draft_alert_message(session, facts, AlertLevel.URGENT)
    assert used1 is False

    # Case 2: unverified promise "help is on the way"
    promise_text = (
        "URGENT warning for Zone A: 90 mm rain. Move to higher ground now. Help is on the way! "
        "Depot: Warehouse A - North Depot is 3.3 km."
    )
    monkeypatch.setattr(
        alert_drafting,
        "generate_json",
        lambda prompt, schema, system=None: AlertDraft(message=promise_text),
    )
    msg2, used2 = draft_alert_message(session, facts, AlertLevel.URGENT)
    assert used2 is False

    # Case 3: unverified promise "rescue is coming"
    rescue_text = (
        "URGENT warning for Zone A: 90 mm rain. Move to higher ground now. Rescue is coming soon. "
        "Depot: Warehouse A - North Depot is 3.3 km."
    )
    monkeypatch.setattr(
        alert_drafting,
        "generate_json",
        lambda prompt, schema, system=None: AlertDraft(message=rescue_text),
    )
    msg3, used3 = draft_alert_message(session, facts, AlertLevel.URGENT)
    assert used3 is False


def test_draft_message_accepts_good_message_from_approved_steps(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that a compliant message built strictly from approved safety steps is accepted."""
    facts = {
        "region": "Zone A - Riverside",
        "alert_level_label": "Urgent warning",
        "rainfall_mm": 90,
        "nearest_warehouse": "Warehouse A - North Depot",
        "distance_km": 3.3,
    }

    good_text = (
        "URGENT flood warning for Zone A: 90 mm rain expected. "
        "Move to higher ground now, stay away from flooded roads and electrical lines, and help elderly neighbours. "
        "Nearest depot: Warehouse A - North Depot, 3.3 km away."
    )
    monkeypatch.setattr(
        alert_drafting,
        "generate_json",
        lambda prompt, schema, system=None: AlertDraft(message=good_text),
    )

    message, used_llm = draft_alert_message(session, facts, AlertLevel.URGENT)
    assert used_llm is True
    assert message == good_text
