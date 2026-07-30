"""Outreach toolkit: Agno tools wrapping OutreachPort for agent use."""

from __future__ import annotations

from agno.tools import tool

from app.integrations.registry import get_outreach


@tool(name="instantly_create_campaign")
async def instantly_create_campaign(name: str, step1_subject: str, step1_body: str, step2_subject: str = "", step2_body: str = "", step3_subject: str = "", step3_body: str = "") -> str:
    """Create an email outreach campaign in Instantly with up to 3 sequence steps."""
    outreach = get_outreach()
    steps = [{"subject": step1_subject, "body": step1_body, "wait_days": 1}]
    if step2_subject:
        steps.append({"subject": step2_subject, "body": step2_body, "wait_days": 2})
    if step3_subject:
        steps.append({"subject": step3_subject, "body": step3_body, "wait_days": 3})
    result = await outreach.create_campaign(name, steps)
    return f"Campaign created: {result.get('id', 'unknown')} ({len(steps)} steps)"


@tool(name="instantly_add_lead")
async def instantly_add_lead(campaign_id: str, email: str, first_name: str = "", company: str = "") -> str:
    """Add a lead to an existing Instantly campaign."""
    outreach = get_outreach()
    variables: dict[str, str] = {}
    if first_name:
        variables["first_name"] = first_name
    if company:
        variables["company"] = company
    await outreach.add_lead(campaign_id, email, variables)
    return f"Lead added: {email} to campaign {campaign_id}"


@tool(name="instantly_get_stats")
async def instantly_get_stats(campaign_id: str) -> str:
    """Get campaign stats from Instantly (sent, opened, replied, bounced)."""
    outreach = get_outreach()
    stats = await outreach.get_campaign_stats(campaign_id)
    return f"Campaign {campaign_id}: sent={stats.get('sent',0)} opened={stats.get('opened',0)} replied={stats.get('replied',0)} bounced={stats.get('bounced',0)}"