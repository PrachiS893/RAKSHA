"""Tests for supply allocation algorithms and Relief Coordination Agent.

GOLDEN RULES:
- Allocation is a RECOMMENDATION. Stock is only reduced when a coordinator approves.
- Highest priority requests are served first; each request gets the NEAREST warehouse that has enough stock.
"""

from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, select
from app.agents.relief_agent import run_relief_agent
from app.agents.triage_agent import run_triage_all
from app.constants import RequestStatus, Resource, RiskLevel
from app.demo_data import SAMPLE_REQUESTS
from app.models import Assignment, Inventory, Region, Request, Warehouse
from app.services.allocation import allocate, haversine_km, quantity_needed
from app.services.request_intake import create_request


def test_pure_unit_quantity_needed() -> None:
    # Water: 3 litres per person, people_count None or < 1 counts as 1
    assert quantity_needed(Resource.DRINKING_WATER, 1) == 3
    assert quantity_needed(Resource.DRINKING_WATER, 6) == 18
    assert quantity_needed(Resource.DRINKING_WATER, None) == 3
    assert quantity_needed(Resource.DRINKING_WATER, 0) == 3

    # Food: 3 packets per person
    assert quantity_needed(Resource.FOOD_PACKET, 1) == 3
    assert quantity_needed(Resource.FOOD_PACKET, 5) == 15
    assert quantity_needed(Resource.FOOD_PACKET, None) == 3

    # Medical kit: 1 per request
    assert quantity_needed(Resource.MEDICAL_KIT, 1) == 1
    assert quantity_needed(Resource.MEDICAL_KIT, 5) == 1
    assert quantity_needed(Resource.MEDICAL_KIT, None) == 1

    # Rescue boat: 1 per request
    assert quantity_needed(Resource.RESCUE_BOAT, 1) == 1
    assert quantity_needed(Resource.RESCUE_BOAT, 8) == 1
    assert quantity_needed(Resource.RESCUE_BOAT, None) == 1

    # None resource
    assert quantity_needed(None, 4) == 0


def test_pure_unit_haversine_km() -> None:
    # Same point
    assert haversine_km(26.18, 91.75, 26.18, 91.75) == 0.0

    # Known distance: Guwahati points (~2.5 - 3.5 km)
    d = haversine_km(26.175, 91.758, 26.195, 91.770)
    assert 2.0 < d < 4.0


def test_relief_agent_four_sample_requests(
    client_and_session: tuple[TestClient, Session],
) -> None:
    _, session = client_and_session

    # Set Zone A SEVERE, Zone B HIGH
    regions = session.exec(select(Region)).all()
    for r in regions:
        if "Zone A" in r.name:
            r.risk_level = RiskLevel.SEVERE.value
        elif "Zone B" in r.name:
            r.risk_level = RiskLevel.HIGH.value
        session.add(r)
    session.commit()

    # Create the 4 sample requests
    for req_data in SAMPLE_REQUESTS:
        create_request(
            session=session,
            text=req_data["text"],
            lat=req_data["lat"],
            lon=req_data["lon"],
            name=req_data.get("name"),
            triage=False,
        )

    # Initial inventory snapshot
    initial_inventory = {
        (i.warehouse_id, i.resource): i.quantity
        for i in session.exec(select(Inventory)).all()
    }

    # Run relief agent (runs triage first)
    plan = run_relief_agent(session, triage_first=True)

    # Check plan summary
    assert plan.summary.requests_considered == 4
    assert plan.summary.assigned == 4
    assert plan.summary.partial == 0
    assert plan.summary.unmet == 0
    assert plan.summary.awaiting_approval == 4
    assert plan.summary.approved == 0
    assert len(plan.unmet) == 0
    assert len(plan.assignments) == 4

    # Verify inventory was NOT changed by planning
    current_inventory = {
        (i.warehouse_id, i.resource): i.quantity
        for i in session.exec(select(Inventory)).all()
    }
    assert current_inventory == initial_inventory

    # Check specific assignments
    # 1. Elderly trapped -> rescue_boat x1 from Warehouse A (Fancy Bazaar)
    # 2. Amit (insulin) -> medical_kit x1 from Warehouse C (Noonmati, 2.2 km)
    # 3. Rina (water 6 people) -> drinking_water x18 from Warehouse B (Khanapara, 4.8 km)
    # 4. Pooja (food 5 people) -> food_packet x15 from Warehouse B (Khanapara, 3.8 km)
    asgn_by_res = {a.resource: a for a in plan.assignments}

    boat_asgn = asgn_by_res[Resource.RESCUE_BOAT.value]
    assert boat_asgn.quantity == 1
    assert "Warehouse A" in boat_asgn.warehouse
    assert boat_asgn.approved is False
    assert boat_asgn.partial is False

    med_asgn = asgn_by_res[Resource.MEDICAL_KIT.value]
    assert med_asgn.quantity == 1
    assert "Warehouse C" in med_asgn.warehouse

    water_asgn = asgn_by_res[Resource.DRINKING_WATER.value]
    assert water_asgn.quantity == 18
    assert "Warehouse B" in water_asgn.warehouse

    food_asgn = asgn_by_res[Resource.FOOD_PACKET.value]
    assert food_asgn.quantity == 15
    assert "Warehouse B" in food_asgn.warehouse

    # Idempotency test: re-running the agent produces the same count of assignments without duplicating
    plan2 = run_relief_agent(session, triage_first=False)
    assert len(plan2.assignments) == 4
    db_assignments = session.exec(select(Assignment)).all()
    assert len(db_assignments) == 4


def test_allocation_scarcity_and_unmet_shortage() -> None:
    # Warehouse stock: only 1 rescue boat in Warehouse 1, 0 in others
    stock = {1: {"rescue_boat": 1}, 2: {"rescue_boat": 0}}
    coords = {1: (26.19, 91.77), 2: (26.13, 91.80)}
    names = {1: "Warehouse 1", 2: "Warehouse 2"}

    # Two requests for rescue boat: req1 has higher priority than req2
    class DummyReq:
        def __init__(self, id: int, ref: str, score: int, lat: float, lon: float):
            self.id = id
            self.ref = ref
            self.resource_needed = "rescue_boat"
            self.people_count = 1
            self.priority_score = score
            self.urgency = "CRITICAL"
            self.lat = lat
            self.lon = lon
            self.created_at = 100

    r1 = DummyReq(1, "R1", 95, 26.18, 91.76)
    r2 = DummyReq(2, "R2", 70, 26.18, 91.76)

    assignments, unmet = allocate([r2, r1], stock, coords, names)

    # R1 gets the single rescue boat because of higher priority score (95 vs 70)
    assert len(assignments) == 1
    assert assignments[0]["request_id"] == 1
    assert assignments[0]["quantity"] == 1

    # R2 is unmet due to no stock available
    assert len(unmet) == 1
    assert unmet[0]["request_id"] == 2
    assert unmet[0]["reason"] == "No stock available"


def test_allocation_partial_and_missing_resource() -> None:
    # Warehouse stock: warehouse 1 has 3 packets, warehouse 2 has 1 packet
    stock = {1: {"food_packet": 3}, 2: {"food_packet": 1}}
    coords = {1: (26.19, 91.77), 2: (26.13, 91.80)}
    names = {1: "Warehouse 1", 2: "Warehouse 2"}

    class DummyReq:
        def __init__(self, id: int, res: str | None, count: int, score: int):
            self.id = id
            self.ref = f"R{id}"
            self.resource_needed = res
            self.people_count = count
            self.priority_score = score
            self.urgency = "HIGH"
            self.lat = 26.18
            self.lon = 91.76
            self.created_at = 100

    # Request 1: needs food for 2 people (6 packets), but largest warehouse only has 3
    # Request 2: no resource identified
    r1 = DummyReq(1, "food_packet", 2, 80)
    r2 = DummyReq(2, None, 1, 60)

    assignments, unmet = allocate([r1, r2], stock, coords, names)

    # r1 gets partial assignment of 3 packets
    assert len(assignments) == 1
    assert assignments[0]["request_id"] == 1
    assert assignments[0]["partial"] is True
    assert assignments[0]["quantity"] == 3
    assert assignments[0]["unmet_quantity"] == 3
    assert "Partial: only 3 of 6 available" in assignments[0]["reason"]

    # r2 is unmet because no resource identified
    assert len(unmet) == 1
    assert unmet[0]["request_id"] == 2
    assert unmet[0]["reason"] == "Needs coordinator decision: no clear resource identified"
