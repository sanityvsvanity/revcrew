"""Instantly inbound webhook: replies, opens, unsubscribes into the outbox."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.events import dispatch_pending_events, enqueue_event
from app.webhooks.signature import verify_shared_secret

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

ACCEPTED_KINDS = {"reply_received", "email_opened", "lead_unsubscribed"}


@router.post("/instantly")
async def instantly_webhook(request: Request):
    """Accept an Instantly event, verify the shared secret, park it in the outbox.

    Returns 200 fast; processing happens in the background dispatcher.
    """
    secret_header = request.headers.get("x-revcrew-secret", "")
    if not verify_shared_secret(secret_header, settings.INSTANTLY_WEBHOOK_SECRET):
        return JSONResponse({"error": "invalid_secret"}, status_code=401)

    try:
        payload = json.loads(await request.body())
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    kind = payload.get("event", "reply_received")
    if kind not in ACCEPTED_KINDS:
        return JSONResponse({"ok": True, "ignored": kind})

    event_id = await enqueue_event("instantly", kind, payload)
    asyncio.create_task(dispatch_pending_events())
    return JSONResponse({"ok": True, "event_id": event_id})
