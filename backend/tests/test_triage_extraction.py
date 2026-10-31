"""Tests for triage extraction with rules fallback and LLM safety checks."""

from collections.abc import Generator
from unittest.mock import patch
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from app.config import settings
from app.constants import Resource
from app.schemas import TriageFeatures
from app.seed import seed_database
from app.services.triage_extraction import (
    RED_FLAG_PHRASES,
    _extract_people_count,
    extract_features,
    extract_with_rules,
)


@pytest.fixture(name="session")
def session_fixture() -> Generator[Session, None, None]:
    """Provide an isolated, seeded in-memory database session."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        seed_database(session)
        yield session


def test_extract_with_rules_medical_emergency() -> None:
    """Verify rules extraction parses medical distress correctly."""
    text = "My father is diabetic and has run out of insulin. He is very weak."
    features = extract_with_rules(text)

    assert features.resource_needed == Resource.MEDICAL_KIT
    assert features.medical_dependency is True
    assert features.no_supply_remaining is True
    assert features.life_threatening is True
    assert features.life_threat_evidence == "insulin"


def test_extract_with_rules_trapped_rescue() -> None:
    """Verify rules extraction parses trapped rescue scenario with rising water."""
    text = "Elderly grandmother is trapped on the roof, water is rising fast, cannot walk."
    features = extract_with_rules(text)

    assert features.resource_needed == Resource.RESCUE_BOAT
    assert features.trapped is True
    assert features.elderly is True
    assert features.disabled_or_immobile is True
    assert features.immediate_danger is True
    assert features.life_threatening is True


def test_extract_people_count_patterns() -> None:
    """Verify regex and word number extraction for people counts."""
    assert _extract_people_count("We are a family of four people") == 4
    assert _extract_people_count("family of 6 trapped inside") == 6
    assert _extract_people_count("5 people need drinking water") == 5
    assert _extract_people_count("food for five") == 5
    assert _extract_people_count("water for 12") == 12


def test_red_flag_union_elevates_life_threatening(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify Red-Flag Union raises life_threatening to True even if LLM missed it."""
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "gsk_fake_test_key_123")

    # LLM incorrectly returns life_threatening=False
    mock_llm_output = TriageFeatures(
        resource_needed=Resource.RESCUE_BOAT,
        life_threatening=False,
        life_threat_evidence=None,
        need_summary="Person trapped on roof.",
    )

    with patch("app.services.triage_extraction.generate_json", return_value=mock_llm_output):
        text = "Help, my uncle is trapped inside the flooded house!"
        features, source, needs_review = extract_features(session, text)

        assert source == "llm"
        # Deterministic red flag check detected 'trapped' and elevated life_threatening
        assert features.life_threatening is True
        assert needs_review is True


def test_evidence_substring_check_triggers_needs_review(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that invented life_threat_evidence not in the citizen message sets needs_review=True."""
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "gsk_fake_test_key_123")

    mock_llm_output = TriageFeatures(
        resource_needed=Resource.DRINKING_WATER,
        life_threatening=True,
        life_threat_evidence="completely fabricated text not in message",
        need_summary="Need water urgently.",
    )

    with patch("app.services.triage_extraction.generate_json", return_value=mock_llm_output):
        text = "We have run out of clean drinking water."
        features, source, needs_review = extract_features(session, text)

        assert features.life_threatening is True
        assert needs_review is True


def test_llm_unavailable_falls_back_to_rules(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that when generate_json returns None, rules extraction is used."""
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "gsk_fake_test_key_123")

    with patch("app.services.triage_extraction.generate_json", return_value=None):
        text = "Need food for family of three."
        features, source, needs_review = extract_features(session, text)

        assert source == "rules"
        assert needs_review is True
        assert features.resource_needed == Resource.FOOD_PACKET
        assert features.people_count == 3
