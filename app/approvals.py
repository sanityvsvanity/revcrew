"""Approval gate: Postgres-backed human-in-the-loop for workflow steps."""

from __future__ import annotations

import json
from typing import Any

from app.db import get_pool
from app.integrations.registry import get_chat


async def create_approval(
    run_id: str,
    title: str,
    summary: str,
    channel: str = "#gtm-desk",
    thread_ts: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an approval request: write row + post Block Kit message.

    `data` carries whatever the post-approval step needs (the drafted
    sequence, the lead), so a parked run can resume from any process.
    """
    pool = await get_pool()
    payload = {
        "run_id": run_id,
        "title": title,
        "summary": summary,
        "channel": channel,
        "thread_ts": thread_ts,
        "data": data or {},
    }
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO approvals (run_id, payload, status) VALUES (%s, %s, 'pending') "
            "ON CONFLICT (run_id) DO UPDATE SET status = 'pending', payload = EXCLUDED.payload",
            (run_id, json.dumps(payload)),
        )

    chat = get_chat()
    result = await chat.open_approval(
        channel=channel,
        run_id=run_id,
        title=title,
        summary=summary,
        thread_ts=thread_ts,
    )
    return result


async def resolve_approval(run_id: str, action: str) -> dict[str, Any]:
    """Resolve an approval: update row status, return resolution."""
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "UPDATE approvals SET status = %s, resolved_at = NOW() "
            "WHERE run_id = %s RETURNING payload",
            (action, run_id),
        )
        row = await cur.fetchone()
        if not row:
            return {"run_id": run_id, "status": "not_found"}
        payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return {"run_id": run_id, "status": action, "payload": payload}


async def get_approval_status(run_id: str) -> dict[str, Any] | None:
    """Check the status of an approval."""
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT status, payload FROM approvals WHERE run_id = %s",
            (run_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        payload = row[1] if isinstance(row[1], dict) else json.loads(row[1])
        return {"run_id": run_id, "status": row[0], "payload": payload}
