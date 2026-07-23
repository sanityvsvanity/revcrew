"""Demo pipeline: the real infrastructure path driven with canned agent outputs.

Both the CLI demo (demo/run_demo.py) and the Slack /demo command drive this
module. Everything here executes for real: approvals rows, the event outbox,
and every port call. Only the agent outputs are canned, loaded from
demo/data/canned.json and validated against the schemas in app/schemas.py.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.approvals import create_approval, get_approval_status
from app.db import get_pool
from app.events import dispatch_pending_events, enqueue_event
from app.integrations.registry import get_crm, get_outreach
from app.schemas import AccountBrief, LeadScore, SequenceDraft

DATA_DIR = Path(__file__).parent / "data"


def load_lead(lead_index: int = 0) -> tuple[dict, dict]:
    """Return the Nth Tier A lead and its canned fixtures."""
    leads = json.loads((DATA_DIR / "leads.json").read_text())
    canned = json.loads((DATA_DIR / "canned.json").read_text())
    tier_a = [l for l in leads if l["tier"] == "A"]
    lead = tier_a[lead_index % len(tier_a)]
    return lead, canned[lead["id"]]


async def start_run(
    lead_index: int = 0, channel: str = "#gtm-desk"
) -> dict[str, Any]:
    """Research, qualify, draft, then open the approval gate.

    The draft is stored in the approval payload so the run can be completed
    from a Slack button click or a later process. Nothing is pushed anywhere
    until the approval resolves.
    """
    lead, fixtures = load_lead(lead_index)
    brief = AccountBrief.model_validate(fixtures["brief"])
    score = LeadScore.model_validate(fixtures["score"])
    draft = SequenceDraft.model_validate(fixtures["draft"])

    run_id = f"run-{uuid.uuid4().hex[:8]}"
    await create_approval(
        run_id=run_id,
        title=f"Outreach sequence for {lead['company']}",
        summary=(
            f"{len(draft.steps)} steps, Tier {score.tier}, score {score.score}. "
            f"First subject: {draft.steps[0].subject}"
        ),
        channel=channel,
        data={
            "lead": lead,
            "draft": draft.model_dump(),
            "brief_snapshot": brief.snapshot,
        },
    )
    return {
        "run_id": run_id,
        "lead": lead,
        "brief": brief,
        "score": score,
        "draft": draft,
        "call_brief": fixtures["call_brief"],
    }


async def complete_run(run_id: str) -> dict[str, Any] | None:
    """Push an approved run to outreach and CRM through the real ports.

    Returns None when the approval is missing or not approved. Campaigns are
    always created paused.
    """
    status = await get_approval_status(run_id)
    if not status or status["status"] != "approved":
        return None

    data = status["payload"].get("data") or {}
    lead = data.get("lead")
    draft = data.get("draft")
    if not lead or not draft:
        return None

    outreach = get_outreach()
    crm = get_crm()

    campaign = await outreach.create_campaign(f"Outbound - {lead['company']}", draft["steps"])
    await outreach.add_lead(campaign["id"], lead["email"], {"first_name": lead["first_name"]})
    contact = await crm.upsert_contact(
        lead["email"],
        {"first_name": lead["first_name"], "last_name": lead["last_name"], "title": lead["title"]},
    )
    company = await crm.upsert_company(lead["domain"], {"name": lead["company"], "industry": lead["industry"]})
    await crm.create_deal(f"{lead['company']} - Outbound", {"amount": "$18,000", "stage": "prospecting"})
    if data.get("brief_snapshot"):
        await crm.log_note("contact", lead["email"], f"Account brief: {data['brief_snapshot']}")
    await crm.associate("contact", contact["id"], "company", company["id"])

    return {"run_id": run_id, "campaign": campaign, "lead": lead}


async def inject_reply(reply_index: int = 0) -> int:
    """Feed a canned reply through the event outbox and dispatch it."""
    replies = json.loads((DATA_DIR / "replies.json").read_text())
    reply = replies[reply_index % len(replies)]
    await enqueue_event("instantly", "reply_received", reply)
    return await dispatch_pending_events()


async def reset_state() -> None:
    """Clear all mock state."""
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "TRUNCATE mock_crm_objects, mock_campaigns, mock_messages, approvals, events "
            "RESTART IDENTITY"
        )


async def next_lead_index() -> int:
    """Rotate through the Tier A seed leads across /demo new-lead calls."""
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM approvals")
        count = (await cur.fetchone())[0]
    return count % 3
