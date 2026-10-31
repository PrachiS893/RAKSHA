"""Tests for Relief Coordination Agent endpoints.

Includes:
- POST /relief/plan
- GET /relief/plan
- POST /assignments/{id}/approve
- POST /plan/approve
- POST /assignments/{id}/dispatch
"""

from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.constants import RequestStatus, Resource, RiskLevel
from app.demo_data import SAMPLE_REQUESTS
from app.models import Assignment, Inventory, Region, Request
from app.services.request_intake import create_request


def _setup_flood_requests(client: TestClient, session: Session) -> None:
    # Set Zone A SEVERE, Zone B HIGH
    regions = session.exec(select(Region)).all()
    for r in regions:
        if "Zone A" in r.name:
            r.risk_level = RiskLevel.SEVERE.value
        elif "Zone B" in r.name:
            r.risk_level = RiskLevel.HIGH.value
        session.add(r)
    session.commit()

    for req_data in SAMPLE_REQUESTS:
        create_request(
            session=session,
            text=req_data["text"],
            lat=req_data["lat"],
            lon=req_data["lon"],
            name=req_data.get("name"),
            triage=False,
        )


def test_plan_generate_and_get_endpoints(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    _setup_flood_requests(client, session)

    # POST /relief/plan
    res = client.post("/relief/plan?triage_first=true")
    assert res.status_code == 200
    plan_post = res.json()

    assert plan_post["summary"]["requests_considered"] == 4
    assert plan_post["summary"]["assigned"] == 4
    assert plan_post["summary"]["awaiting_approval"] == 4
    assert len(plan_post["assignments"]) == 4

    # GET /relief/plan matches POST /relief/plan
    res_get = client.get("/relief/plan")
    assert res_get.status_code == 200
    plan_get = res_get.json()

    assert plan_get["summary"] == plan_post["summary"]
    assert len(plan_get["assignments"]) == len(plan_post["assignments"])
    assert [a["id"] for a in plan_get["assignments"]] == [a["id"] for a in plan_post["assignments"]]


def test_approve_single_assignment_and_conflict(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    _setup_flood_requests(client, session)
    client.post("/relief/plan")

    assignments = session.exec(select(Assignment)).all()
    target_a = assignments[0]

    # Pre-check warehouse stock
    inv_before = session.exec(
        select(Inventory).where(
            Inventory.warehouse_id == target_a.warehouse_id,
            Inventory.resource == target_a.resource,
        )
    ).one()
    initial_stock = inv_before.quantity

    # 1. Approve with empty body -> defaults to "coordinator"
    res = client.post(f"/assignments/{target_a.id}/approve")
    assert res.status_code == 200
    data = res.json()
    assert data["approved"] is True
    assert data["approved_by"] == "coordinator"
    assert data["approved_at"] is not None
    assert data["request_status"] == RequestStatus.ASSIGNED.value

    # Warehouse stock reduced by exactly the assigned quantity
    session.expire_all()
    inv_after = session.exec(
        select(Inventory).where(
            Inventory.warehouse_id == target_a.warehouse_id,
            Inventory.resource == target_a.resource,
        )
    ).one()
    assert inv_after.quantity == initial_stock - target_a.quantity

    # Request status updated in database
    req = session.get(Request, target_a.request_id)
    assert req.status == RequestStatus.ASSIGNED.value

    # 2. Approving again returns 409
    res_dup = client.post(f"/assignments/{target_a.id}/approve")
    assert res_dup.status_code == 409
    assert "already approved" in res_dup.json()["detail"].lower()


def test_plan_approve_all_and_stock_reduction(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    _setup_flood_requests(client, session)
    client.post("/relief/plan")

    # Initial warehouse status
    wh_res = client.get("/warehouses").json()
    initial_total = sum(i["quantity"] for w in wh_res for i in w["inventory"])
    initial_max = sum(i["initial_quantity"] for w in wh_res for i in w["inventory"])
    assert initial_total == initial_max
    sim_before = client.get("/simulation").json()
    assert sim_before["stats"]["stock_remaining_pct"] == 100.0

    # Approve entire plan with coordinator name
    res = client.post("/plan/approve", json={"approved_by": "Dr. Sharma"})
    assert res.status_code == 200
    plan_appr = res.json()
    assert plan_appr["approved"] == 4
    for a in plan_appr["assignments"]:
        assert a["approved"] is True
        assert a["approved_by"] == "Dr. Sharma"

    # Warehouse status reflects reduced stock (< 100%)
    wh_after = client.get("/warehouses").json()
    after_total = sum(i["quantity"] for w in wh_after for i in w["inventory"])
    assert after_total < initial_total
    sim_after = client.get("/simulation").json()
    assert sim_after["stats"]["stock_remaining_pct"] < 100.0

    # All 4 requests are assigned
    req_res = client.get("/requests").json()
    for r in req_res:
        assert r["status"] == RequestStatus.ASSIGNED.value


def test_plan_approve_all_or_nothing_atomic_failure(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    _setup_flood_requests(client, session)
    client.post("/relief/plan")

    assignments = session.exec(select(Assignment)).all()
    last_a = assignments[-1]

    # Artificially deplete stock for the last assignment's warehouse and resource
    inv = session.exec(
        select(Inventory).where(
            Inventory.warehouse_id == last_a.warehouse_id,
            Inventory.resource == last_a.resource,
        )
    ).one()
    inv.quantity = 0
    session.add(inv)
    session.commit()

    # Pre-check all unapproved
    assert all(not a.approved for a in session.exec(select(Assignment)).all())

    # POST /plan/approve must fail with 409 and change NOTHING
    res = client.post("/plan/approve")
    assert res.status_code == 409
    assert "Insufficient stock" in res.json()["detail"]

    # Verify no assignment was approved
    session.expire_all()
    assignments_after = session.exec(select(Assignment)).all()
    assert all(not a.approved for a in assignments_after)


def test_dispatch_endpoint_lifecycle(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    _setup_flood_requests(client, session)
    client.post("/relief/plan")

    assignment = session.exec(select(Assignment)).first()
    assert assignment is not None

    # 1. Dispatch before approval returns 409
    res_before = client.post(f"/assignments/{assignment.id}/dispatch")
    assert res_before.status_code == 409
    assert "must be approved before dispatch" in res_before.json()["detail"]

    # 2. Approve assignment
    client.post(f"/assignments/{assignment.id}/approve")

    # 3. Dispatch after approval sets "on_the_way"
    res_after = client.post(f"/assignments/{assignment.id}/dispatch")
    assert res_after.status_code == 200
    data = res_after.json()
    assert data["request_status"] == RequestStatus.ON_THE_WAY.value

    session.expire_all()
    req = session.get(Request, assignment.request_id)
    assert req.status == RequestStatus.ON_THE_WAY.value


def test_unknown_assignment_returns_404(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, _ = client_and_session

    res_approve = client.post("/assignments/9999/approve")
    assert res_approve.status_code == 404

    res_dispatch = client.post("/assignments/9999/dispatch")
    assert res_dispatch.status_code == 404
