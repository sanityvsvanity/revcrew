"""Approval gate — Postgres-backed human-in-the-loop for workflow steps."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.db import get_pool
from app.integrations.registry import get_chat


async def create_approval(
    run_id: str,
    title: str,
    summary: str,
    channel: str = "#gtm-desk",
    thread_ts: str | None = None,
) -> dict[str, Any]:
    """Create an approval request: write row + post Block Kit message."""
    pool = await get_pool()
    payload = {
        "run_id": run_id,
        "title": title,
        "summary": summary,
        "channel": channel,
        "thread_ts": thread_ts,
    }
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO approvals (run_id, payload, status) VALUES ($1, $2, 'pending') "
            "ON CONFLICT (run_id) DO UPDATE SET status='pending', payload=$2",
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
        result = await conn.execute(
            "UPDATE approvals SET status=$1, resolved_at=NOW() WHERE run_id=$2 RETURNING payload",
            (action, run_id),
        )
        row = await result.fetchone()
        if not row:
            return {"run_id": run_id, "status": "not_found"}
        return {"run_id": run_id, "status": action, "payload": json.loads(row[0])}


async def get_approval_status(run_id: str) -> dict[str, Any] | None:
    """Check the status of an approval."""
    pool = await get_pool()
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT status, payload FROM approvals WHERE run_id=$1",
            (run_id,),
        )
        row = await result.fetchone()
        if not row:
            return None
        return {"run_id": run_id, "status": row[0], "payload": json.loads(row[1])}