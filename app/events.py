"""Event outbox — pending events → handler dispatch with retry."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from app.db import get_pool


async def enqueue_event(source: str, kind: str, payload: dict) -> int:
    """Insert an event into the outbox for async processing."""
    pool = await get_pool()
    async with pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO events (source, kind, payload, status) VALUES ($1, $2, $3, 'pending') RETURNING id",
            (source, kind, json.dumps(payload)),
        )
        row = await result.fetchone()
        event_id = row[0] if row else 0
    return event_id


async def dispatch_pending_events() -> int:
    """Process all pending events that are due for retry."""
    pool = await get_pool()
    now = datetime.now(timezone.utc)

    async with pool.connection() as conn:
        rows = await conn.execute(
            "SELECT id, source, kind, payload, retries FROM events "
            "WHERE status='pending' AND (next_attempt_at IS NULL OR next_attempt_at <= $1) "
            "ORDER BY created_at LIMIT 50",
            (now,),
        )
        events = await rows.fetchall()

    dispatched = 0
    for event in events:
        event_id, source, kind, payload_str, retries = event
        payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str

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
        # Trigger reply_triage workflow
        from agents.pipelines import reply_triage

        await reply_triage.arun(input=payload)
    elif kind == "email_opened":
        # Log to CRM
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
            "UPDATE events SET status=$1 WHERE id=$2",
            (status, event_id),
        )


async def _retry_event(event_id: int, current_retries: int):
    """Schedule a retry with exponential backoff (max 5 retries)."""
    max_retries = 5
    next_retry = current_retries + 1

    if next_retry > max_retries:
        await _mark_event(event_id, "dead_letter")
        return

    delay = 2 ** next_retry  # 2, 4, 8, 16, 32 seconds
    next_attempt = datetime.now(timezone.utc) + timedelta(seconds=delay)

    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE events SET retries=$1, next_attempt_at=$2 WHERE id=$3",
            (next_retry, next_attempt, event_id),
        )