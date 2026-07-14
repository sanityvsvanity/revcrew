"""CRM Scribe agent — writes to HubSpot, sole holder of CRM write tools."""

from agno.agent import Agent
from agno.models.anthropic import Claude

from app.config import settings
from app.toolkits.crm_tools import (
    hubspot_create_deal,
    hubspot_create_task,
    hubspot_log_note,
    hubspot_search_contact,
    hubspot_upsert_company,
    hubspot_upsert_contact,
)

crm_scribe = Agent(
    name="crm_scribe",
    model=Claude(id=settings.MODEL_FAST),
    description="Logs pipeline outputs to HubSpot — contacts, companies, deals, notes, and tasks.",
    instructions="""You are a CRM data entry specialist. Given pipeline outputs (account brief, lead score, sequence draft, triage results), log everything to HubSpot.

Your responsibilities:
- Upsert contacts and companies (deduplicate by email/domain)
- Create deals for qualified leads
- Log notes with research summaries and outreach context
- Create tasks for follow-ups and reply handling
- Associate contacts with companies and deals

Use the available HubSpot tools. Always search before creating to avoid duplicates.
Be thorough — every pipeline action should leave a CRM trail.""",
    tools=[
        hubspot_upsert_contact,
        hubspot_upsert_company,
        hubspot_create_deal,
        hubspot_log_note,
        hubspot_create_task,
        hubspot_search_contact,
    ],
)