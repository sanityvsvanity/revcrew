"""Shared push path: promote the approved run to CRM and outreach.

This is the single entry point for pushing an approved run — called by the
Slack Approve handler, the demo runner, and the retry path (S2.6).
Push order per D10: contact → company → deal → note → associate → campaign last.

Retry safety: CRM writes are idempotent through GuardedCRM (same run_id →
same context → same keys), and the campaign/lead stages record their progress
in approvals.push_detail so a retry resumes instead of creating a duplicate
paused campaign.
"""

from __future__ import annotations

from typing import Any

from app.approvals import get_push_detail, record_push_status
from app.guard import set_write_context
from app.integrations.registry import get_crm, get_outreach


async def push_approved_run(
    run_id: str, payload: dict[str, Any], source: str = "demo"
) -> dict[str, Any]:
    """Push an approved run to CRM and outreach.

    Args:
        run_id: The approval run_id.
        payload: The full approval payload (from the approvals table).
        source: Who triggered the push ("demo" or "slack") — recorded in
            the write audit.

    Returns:
        Dict with campaign, contact, company, deal keys.

    Raises:
        Any stage failure, after recording push_status='push_failed' with
        the error and the progress reached so far.
    """
    data = payload.get("data") or {}
    lead = data.get("lead")
    draft = data.get("draft")
    if not lead or not draft:
        raise ValueError("Approval payload missing lead or draft data")

    outreach = get_outreach()
    crm = get_crm()

    set_write_context(f"push:{run_id}", source)

    prior = await get_push_detail(run_id) or {}
    progress: dict[str, Any] = prior.get("progress") or {}

    deal = data.get("deal", {})
    deal_name = deal.get("name", f"{lead['company']} - Outbound")
    deal_amount = deal.get("amount", "")
    deal_stage = deal.get("stage", "prospecting")

    try:
        # CRM first (D10). These are idempotent through the guard, so a
        # retry re-issues them and gets the prior results back.
        contact = await crm.upsert_contact(
            lead["email"],
            {"firstname": lead.get("first_name", ""), "lastname": lead.get("last_name", ""), "jobtitle": lead.get("title", "")},
        )
        company = await crm.upsert_company(
            lead["domain"],
            {"name": lead["company"], "industry": lead.get("industry", "")},
        )
        deal_props: dict[str, Any] = {
            "dealstage": deal_stage,
            # Dedup hint (S4.6): the guard strips this before the adapter.
            "company_domain": lead["domain"],
        }
        if deal_amount:
            deal_props["amount"] = deal_amount
        deal_result = await crm.create_deal(deal_name, deal_props)
        if data.get("brief_snapshot"):
            await crm.log_note("contact", lead["email"], f"Account brief: {data['brief_snapshot']}")
        await crm.associate("contact", contact["id"], "company", company["id"])

        # Campaign last (D10). Not idempotent at the adapter, so resume
        # from recorded progress instead of re-creating.
        campaign = progress.get("campaign")
        if not campaign:
            campaign = await outreach.create_campaign(
                f"Outbound - {lead['company']}", draft["steps"]
            )
            progress["campaign"] = campaign
            await record_push_status(run_id, "pushing", {"progress": progress})

        if not progress.get("lead_added"):
            await outreach.add_lead(
                campaign["id"], lead["email"], {"first_name": lead.get("first_name", "")}
            )
            progress["lead_added"] = True

        await record_push_status(run_id, "pushed", {"progress": progress})
        return {
            "run_id": run_id,
            "campaign": campaign,
            "contact": contact,
            "company": company,
            "deal": deal_result,
        }
    except Exception as exc:
        await record_push_status(
            run_id, "push_failed", {"error": str(exc), "progress": progress}
        )
        raise
