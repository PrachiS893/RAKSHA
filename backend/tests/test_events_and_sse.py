"""Tests for Server-Sent Events (SSE) live streaming, helpers, and agent logs polling endpoint."""

import json
from fastapi.testclient import TestClient
from sqlmodel import Session
from app.models import AgentLog
from app.routers.events import fetch_logs_after, format_sse, should_emit_stage
from app.services.agent_log import log_agent
from sqlmodel import select



def test_format_sse_structure():
    """format_sse generates properly formatted SSE chunks according to W3C spec."""
    # 1. Event, id, data dictionary
    payload = {"message": "High rainfall detected", "value": 85.5}
    sse_text = format_sse(event="log", data=payload, id=101)

    assert sse_text.startswith("id: 101\n")
    assert "event: log\n" in sse_text
    assert f"data: {json.dumps(payload)}\n" in sse_text
    assert sse_text.endswith("\n\n")

    # 2. Multi-line string data
    multi_line = "Line 1\nLine 2"
    multi_sse = format_sse(event="notice", data=multi_line, id="msg-1")
    assert "data: Line 1\ndata: Line 2\n" in multi_sse
    assert multi_sse.endswith("\n\n")

    # 3. Comment-only keep-alive
    comment_sse = format_sse(comment="keep-alive")
    assert comment_sse == ": keep-alive\n\n"


def test_fetch_logs_after(client_and_session: tuple[TestClient, Session]):
    """fetch_logs_after retrieves only rows newer than after_id in ascending ID order."""
    _, session = client_and_session

    # Insert 5 logs
    ids = []
    for i in range(1, 6):
        log = log_agent(session, agent="Risk", message=f"Risk check iteration {i}")
        ids.append(log.id)

    # Fetch after id 2
    newer = fetch_logs_after(session, after_id=ids[1])
    assert len(newer) >= 3
    assert all(l.id > ids[1] for l in newer)
    # Check ascending order
    retrieved_ids = [l.id for l in newer]
    assert retrieved_ids == sorted(retrieved_ids)

    # Check limit parameter
    limited = fetch_logs_after(session, after_id=ids[0], limit=2)
    assert len(limited) == 2
    assert limited[0].id == ids[1]
    assert limited[1].id == ids[2]


def test_events_stream_once_mode(client_and_session: tuple[TestClient, Session]):
    """GET /events/stream?once=true returns event: log messages with IDs and terminates."""
    client, session = client_and_session

    log1 = log_agent(session, agent="Risk", message="Log event alpha")
    log2 = log_agent(session, agent="Triage", message="Log event beta")

    res = client.get("/events/stream?once=true")
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    assert res.headers.get("cache-control") == "no-cache"

    body = res.text
    # Contains initial stage event and log events
    assert "event: stage" in body
    assert "event: log" in body
    assert f"id: {log1.id}" in body
    assert f"id: {log2.id}" in body
    assert "Log event alpha" in body
    assert "Log event beta" in body


def test_events_stream_after_id_skips_older_rows(client_and_session: tuple[TestClient, Session]):
    """GET /events/stream?after_id=X&once=true skips logs with id <= X."""
    client, session = client_and_session

    log1 = log_agent(session, agent="Risk", message="Older event to skip")
    log2 = log_agent(session, agent="Relief", message="Newer event to include")

    res = client.get(f"/events/stream?after_id={log1.id}&once=true")
    assert res.status_code == 200

    body = res.text
    assert f"id: {log1.id}" not in body
    assert "Older event to skip" not in body
    assert f"id: {log2.id}" in body
    assert "Newer event to include" in body


def test_events_stream_last_event_id_header_overrides_after_id(client_and_session: tuple[TestClient, Session]):
    """Standard Last-Event-ID header overrides after_id query param for client reconnects."""
    client, session = client_and_session

    log1 = log_agent(session, agent="Risk", message="Event one")
    log2 = log_agent(session, agent="Triage", message="Event two")
    log3 = log_agent(session, agent="Relief", message="Event three")

    # query param says after_id=0, but Last-Event-ID header says log2.id
    res = client.get(
        "/events/stream?after_id=0&once=true",
        headers={"Last-Event-ID": str(log2.id)},
    )
    assert res.status_code == 200

    body = res.text
    assert f"id: {log1.id}" not in body
    assert f"id: {log2.id}" not in body
    assert f"id: {log3.id}" in body
    assert "Event three" in body


def test_get_agent_logs_polling_endpoint(client_and_session: tuple[TestClient, Session]):
    """GET /agent-logs returns logs ordered by id ascending, respecting after_id and limit."""
    client, session = client_and_session

    logs = []
    for i in range(5):
        l = log_agent(session, agent="Orchestrator", message=f"Audit message {i}")
        logs.append(l)

    # 1. Fetch all with default limit
    res = client.get("/agent-logs")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 5
    # Verify ascending ordering
    ids = [item["id"] for item in data]
    assert ids == sorted(ids)

    # 2. Fetch with after_id
    res_after = client.get(f"/agent-logs?after_id={logs[2].id}")
    assert res_after.status_code == 200
    after_data = res_after.json()
    assert all(item["id"] > logs[2].id for item in after_data)
    assert after_data[0]["id"] == logs[3].id

    # 3. Fetch with limit
    res_limit = client.get(f"/agent-logs?limit=2")
    assert res_limit.status_code == 200
    limit_data = res_limit.json()
    assert len(limit_data) == 2


def test_reset_preserves_autoincrement_and_cursor(client_and_session: tuple[TestClient, Session]):
    """After POST /simulation/reset, new logs get higher IDs and stream returns them with after_id."""
    client, session = client_and_session

    # Step simulation so we have initial logs
    client.post("/simulation/next")
    logs_before = session.exec(select(AgentLog)).all()
    assert len(logs_before) > 0
    old_max_id = max(l.id for l in logs_before)

    # Reset simulation (deletes agent_logs)
    res_reset = client.post("/simulation/reset")
    assert res_reset.status_code == 200

    # Reset logs an orchestrator message: verify its ID > old_max_id
    logs_after = session.exec(select(AgentLog)).all()
    assert len(logs_after) > 0
    new_min_id = min(l.id for l in logs_after)
    assert new_min_id > old_max_id

    # Verify GET /events/stream?once=true&after_id=<old_max_id> returns the post-reset logs
    res_stream = client.get(f"/events/stream?once=true&after_id={old_max_id}")
    assert res_stream.status_code == 200
    assert "event: log" in res_stream.text
    assert f"id: {new_min_id}" in res_stream.text
    assert "Simulation reset to stage 1: Normal conditions" in res_stream.text


def test_stale_cursor_emits_reset_and_restarts_from_zero(client_and_session: tuple[TestClient, Session]):
    """A stale cursor (after_id > max_id) produces event: reset and then logs from id 0."""
    client, session = client_and_session

    log1 = log_agent(session, agent="Risk", message="Initial log 1")
    log2 = log_agent(session, agent="Triage", message="Initial log 2")
    max_id = max(log1.id, log2.id)

    # Request with stale after_id greater than max_id
    stale_id = max_id + 500
    res = client.get(f"/events/stream?once=true&after_id={stale_id}")
    assert res.status_code == 200

    body = res.text
    # Must emit event: reset
    assert "event: reset" in body
    assert "data: {}" in body

    # And then logs from id 0
    assert f"id: {log1.id}" in body
    assert f"id: {log2.id}" in body
    assert "Initial log 1" in body
    assert "Initial log 2" in body

    # Check /agent-logs with stale cursor also restarts from 0
    res_logs = client.get(f"/agent-logs?after_id={stale_id}")
    assert res_logs.status_code == 200
    data = res_logs.json()
    assert len(data) >= 2
    assert data[0]["id"] == log1.id


def test_should_emit_stage_behavior():
    """should_emit_stage returns True when stats change inside same stage, False when unchanged."""
    s1 = {
        "stage": 2,
        "name": "Heavy rainfall forecast",
        "stats": {
            "pending_alerts": 2,
            "sent_alerts": 0,
            "stock_remaining_pct": 100.0,
        },
    }
    # Stats changed inside the same stage (approved an alert: pending 2 -> 1, sent 0 -> 1)
    s2 = {
        "stage": 2,
        "name": "Heavy rainfall forecast",
        "stats": {
            "pending_alerts": 1,
            "sent_alerts": 1,
            "stock_remaining_pct": 100.0,
        },
    }
    # Nothing changed
    s3 = {
        "stage": 2,
        "name": "Heavy rainfall forecast",
        "stats": {
            "pending_alerts": 1,
            "sent_alerts": 1,
            "stock_remaining_pct": 100.0,
        },
    }

    assert should_emit_stage(None, s1) is True
    assert should_emit_stage(s1, s2) is True
    assert should_emit_stage(s2, s3) is False

    # Also test with json strings
    assert should_emit_stage(json.dumps(s1), json.dumps(s2)) is True
    assert should_emit_stage(json.dumps(s2), json.dumps(s3)) is False

