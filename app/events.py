"""Event outbox: pending events dispatched to handlers with capped retries."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.db import get_pool

MAX_RETRIES = 5


async def enqueue_event(source: str, kind: str, payload: dict) -> int:
    """Insert an event into the outbox for async processing."""
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "INSERT INTO events (source, kind, payload, status) "
            "VALUES (%s, %s, %s, 'pending') RETURNING id",
            (source, kind, json.dumps(payload)),
        )
        row = await cur.fetchone()
        event_id = row[0] if row else 0
    return event_id


async def dispatch_pending_events() -> int:
    """Process all pending events that are due for retry."""
    pool = await get_pool()
    now = datetime.now(timezone.utc)

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, source, kind, payload, retries FROM events "
            "WHERE status = 'pending' AND (next_attempt_at IS NULL OR next_attempt_at <= %s) "
            "ORDER BY created_at LIMIT 50",
            (now,),
        )
        events = await cur.fetchall()

    dispatched = 0
    for event in events:
        event_id, source, kind, payload_raw, retries = event
        payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw

        try:
            await _handle_event(source, kind, payload)
            await _mark_event(event_id, "processed")
            dispatched += 1
        except Exception as exc:
            print(f"[events] Failed to process event {event_id}: {exc}")
            await _retry_event(event_id, retries)

    return dispatched


async def _handle_event(source: str, kind: str, payload: dict):
    """Route an event to the appropriate handler."""
    if kind == "reply_received":
        from app.triage import handle_reply

        await handle_reply(payload)
    elif kind == "lead_received":
        from app.config import settings
        from app.integrations.registry import get_chat

        if settings.DEMO_MODE or not settings.ANTHROPIC_API_KEY:
            chat = get_chat()
            await chat.post_message(
                "#gtm-desk",
                f"New lead in: {payload.get('email', 'unknown')} at "
                f"{payload.get('company', 'unknown')}. Run /demo new-lead to walk the pipeline.",
            )
        else:
            from agents.pipelines import lead_pipeline

            import json as _json

            await lead_pipeline.arun(input=_json.dumps(payload))
    elif kind == "email_opened":
        from app.integrations.registry import get_crm

        crm = get_crm()
        email = payload.get("email", "unknown")
        await crm.log_note("contact", email, f"Email opened: {payload}")
    elif kind == "lead_unsubscribed":
        from app.integrations.registry import get_crm

        crm = get_crm()
        email = payload.get("email", "unknown")
        await crm.log_note("contact", email, f"Lead unsubscribed: {email}")
    else:
        print(f"[events] Unknown event kind: {kind}")


async def _mark_event(event_id: int, status: str):
    """Mark an event as processed or dead-letter."""
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE events SET status = %s WHERE id = %s",
            (status, event_id),
        )


async def _retry_event(event_id: int, current_retries: int):
    """Schedule a retry with exponential backoff, dead-letter after MAX_RETRIES."""
    next_retry = current_retries + 1

    if next_retry > MAX_RETRIES:
        await _mark_event(event_id, "dead_letter")
        return

    delay = 2**next_retry
    next_attempt = datetime.now(timezone.utc) + timedelta(seconds=delay)

    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE events SET retries = %s, next_attempt_at = %s WHERE id = %s",
            (next_retry, next_attempt, event_id),
        )
