"""Live Server-Sent Events stream and polling endpoints for agent audit logs and simulation state."""

import asyncio
import json
import logging
import time
from typing import Any, Optional
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session, func, select
from app.db import engine, get_session
from app.models import AgentLog
from app.schemas import AgentLogRead, format_iso_utc
from app.services.simulator import get_simulation_state_response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Live"])


def format_sse(
    event: str | None = None,
    data: Any = None,
    id: int | str | None = None,
    comment: str | None = None,
) -> str:
    """Format an SSE message block adhering to the HTML5 Server-Sent Events spec."""
    lines: list[str] = []
    if comment is not None:
        lines.append(f": {comment}")
    if id is not None:
        lines.append(f"id: {id}")
    if event is not None:
        lines.append(f"event: {event}")
    if data is not None:
        if isinstance(data, (dict, list)):
            data_str = json.dumps(data)
        else:
            data_str = str(data)
        for subline in data_str.splitlines():
            lines.append(f"data: {subline}")
    return "\n".join(lines) + "\n\n"


def should_emit_stage(
    previous_json: dict[str, Any] | str | None,
    current_json: dict[str, Any] | str | None,
) -> bool:
    """Determine whether simulation state has changed and an event: stage should be emitted.

    Returns True if previous_json is None, or if current_json differs from previous_json.
    Accepts parsed dictionaries or raw JSON strings.
    """
    if previous_json is None:
        return True
    if current_json is None:
        return False

    prev_obj = (
        json.loads(previous_json)
        if isinstance(previous_json, str)
        else previous_json
    )
    curr_obj = (
        json.loads(current_json)
        if isinstance(current_json, str)
        else current_json
    )
    return prev_obj != curr_obj


def fetch_logs_after(
    session: Session,
    after_id: int = 0,
    limit: int | None = None,
) -> list[AgentLog]:
    """Fetch AgentLog records with ID strictly greater than after_id, ordered by ID ascending."""
    stmt = select(AgentLog).where(AgentLog.id > after_id).order_by(AgentLog.id.asc())
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.exec(stmt).all())


def _serialize_log(log: AgentLog) -> dict[str, Any]:
    """Serialize an AgentLog instance into SSE log event data dictionary."""
    return {
        "id": log.id,
        "agent": log.agent,
        "message": log.message,
        "payload": log.payload,
        "created_at": format_iso_utc(log.created_at),
    }


def _get_stream_snapshot(
    after_id: int | None,
) -> tuple[int, list[dict[str, Any]], dict[str, Any], bool]:
    """Query current snapshot in a short-lived session (designed for threadpool execution).

    If after_id is greater than the highest existing log ID, assumes database was recreated.
    """
    with Session(engine) as session:
        max_id = session.exec(select(func.max(AgentLog.id))).first() or 0
        was_reset = False
        if after_id is not None and after_id > max_id:
            was_reset = True
            starting_id = 0
        elif after_id is None:
            starting_id = max_id
        else:
            starting_id = after_id

        logs = fetch_logs_after(session, after_id=starting_id)
        serialized_logs = [_serialize_log(l) for l in logs]
        state_data = get_simulation_state_response(session).model_dump(mode="json")
        return starting_id, serialized_logs, state_data, was_reset


def _poll_stream_snapshot(
    last_log_id: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], bool, int]:
    """Poll for new logs and current state in a short-lived session (designed for threadpool execution)."""
    with Session(engine) as session:
        max_id = session.exec(select(func.max(AgentLog.id))).first() or 0
        was_reset = False
        effective_id = last_log_id
        if last_log_id > max_id:
            was_reset = True
            effective_id = 0
        new_logs = fetch_logs_after(session, after_id=effective_id)
        serialized_logs = [_serialize_log(l) for l in new_logs]
        state_data = get_simulation_state_response(session).model_dump(mode="json")
        return serialized_logs, state_data, was_reset, effective_id


@router.get(
    "/events/stream",
    summary="Live Server-Sent Events stream of agent activity and simulation state transitions",
)
async def events_stream(
    request: Request,
    after_id: Optional[int] = Query(
        default=None,
        ge=0,
        description="Resume logs stream after this ID (defaults to latest in live stream, 0 in once mode)",
    ),
    once: bool = Query(
        default=False,
        description="Send existing backlog and close immediately (useful for tests and curl debugging)",
    ),
    last_event_id: Optional[str] = Header(
        default=None,
        alias="Last-Event-ID",
        description="Standard SSE resume header overriding after_id",
    ),
) -> StreamingResponse:
    """Stream real-time agent execution logs and simulation stage updates via SSE."""
    # Last-Event-ID header takes precedence over after_id query parameter
    effective_after_id: int | None
    if last_event_id is not None and last_event_id.strip() != "":
        try:
            effective_after_id = int(last_event_id.strip())
        except ValueError:
            effective_after_id = after_id if after_id is not None else (0 if once else None)
    elif after_id is not None:
        effective_after_id = after_id
    elif once:
        effective_after_id = 0
    else:
        effective_after_id = None

    async def event_generator():
        # Retrieve initial snapshot in threadpool
        last_log_id, initial_logs, state_data, was_reset = await asyncio.to_thread(
            _get_stream_snapshot, effective_after_id
        )

        # 1. If cursor was stale (after_id > max_id), notify client of reset
        if was_reset:
            yield format_sse(event="reset", data={})

        # 2. Emit current simulation stage once at connection start
        yield format_sse(event="stage", data=state_data)
        last_state_data = state_data

        # 3. Emit initial / backlog logs
        for log_dict in initial_logs:
            yield format_sse(event="log", data=log_dict, id=log_dict["id"])
            if log_dict["id"] > last_log_id:
                last_log_id = log_dict["id"]

        # If once mode requested, terminate stream immediately
        if once:
            return

        last_keep_alive = time.time()

        # 4. Continuous polling loop with non-blocking sleeps and short-lived sessions
        while True:
            if await request.is_disconnected():
                break

            await asyncio.sleep(0.7)

            if await request.is_disconnected():
                break

            new_logs, state_data, was_reset_loop, reset_id = await asyncio.to_thread(
                _poll_stream_snapshot, last_log_id
            )

            if was_reset_loop:
                last_log_id = reset_id
                yield format_sse(event="reset", data={})

            # Emit stage change event whenever serialized state differs from last sent
            if should_emit_stage(last_state_data, state_data):
                last_state_data = state_data
                yield format_sse(event="stage", data=state_data)

            # Emit log events for newly persisted agent activities
            for log_dict in new_logs:
                yield format_sse(event="log", data=log_dict, id=log_dict["id"])
                if log_dict["id"] > last_log_id:
                    last_log_id = log_dict["id"]

            # Emit keep-alive comment every 15 seconds
            now = time.time()
            if now - last_keep_alive >= 15.0:
                last_keep_alive = now
                yield format_sse(comment="keep-alive")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/agent-logs",
    response_model=list[AgentLogRead],
    summary="Retrieve agent audit logs ordered ascending by ID for polling clients",
)
def get_agent_logs(
    after_id: int = Query(
        default=0,
        ge=0,
        description="Return logs with ID strictly greater than this value",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of logs to return (default 50, max 200)",
    ),
    session: Session = Depends(get_session),
) -> list[AgentLogRead]:
    """Retrieve agent logs in ascending ID order for polling clients."""
    max_id = session.exec(select(func.max(AgentLog.id))).first() or 0
    if after_id > max_id:
        after_id = 0
    logs = fetch_logs_after(session, after_id=after_id, limit=limit)
    return [
        AgentLogRead(
            id=log.id,
            agent=log.agent,
            message=log.message,
            payload=log.payload,
            created_at=format_iso_utc(log.created_at),
        )
        for log in logs
    ]
