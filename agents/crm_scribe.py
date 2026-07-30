"""CRM Scribe agent: writes to HubSpot, sole holder of CRM write tools."""

from agno.agent import Agent

from app.models import get_model
from app.prompts.crm_scribe import CRM_SCRIBE_INSTRUCTIONS
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
    model=get_model("crm_scribe"),
    description="Logs pipeline outputs to HubSpot: contacts, companies, deals, notes, and tasks.",
    instructions=CRM_SCRIBE_INSTRUCTIONS,
    tools=[
        hubspot_upsert_contact,
        hubspot_upsert_company,
        hubspot_create_deal,
        hubspot_log_note,
        hubspot_create_task,
        hubspot_search_contact,
    ],
)