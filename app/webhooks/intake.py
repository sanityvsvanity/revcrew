"""Lead intake API: new leads enter through the same outbox as everything else."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

from app.events import dispatch_pending_events, enqueue_event

router = APIRouter(prefix="/api", tags=["intake"])


class LeadIn(BaseModel):
    email: EmailStr
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    company: str
    domain: str = ""
    signals: str = ""


@router.post("/leads")
async def create_lead(lead: LeadIn):
    """Accept a lead, park it in the outbox, return 200 fast."""
    event_id = await enqueue_event("api", "lead_received", lead.model_dump())
    asyncio.create_task(dispatch_pending_events())
    return JSONResponse({"ok": True, "event_id": event_id})
