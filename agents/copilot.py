"""Copilot agent + gtm_desk Team: the Slack-facing AI assistant for reps.

S3.3: Activity read tool over write_audit + approvals for "what did you do this week?"
S4.8: Read-back fencing on CRM free-text fields.
"""

from agno.agent import Agent
from agno.team import Team

from app.models import get_model
from app.prompts.copilot import COPILOT_INSTRUCTIONS
from app.toolkits.crm_tools import (
    hubspot_search_contact,
    revcrew_activity_summary,
)

from .crm_scribe import crm_scribe
from .outreach_writer import outreach_writer
from .qualifier import qualifier
from .researcher import researcher

copilot = Agent(
    name="copilot",
    model=get_model("copilot"),
    description="Slack-facing AI assistant for sales reps: answers questions, runs research, checks pipeline status.",
    instructions=COPILOT_INSTRUCTIONS,
    tools=[hubspot_search_contact, revcrew_activity_summary],
)

gtm_desk = Team(
    name="gtm_desk",
    model=get_model("copilot"),
    members=[copilot, researcher, qualifier, outreach_writer, crm_scribe],
    description="The full GTM desk team: copilot leads, specialists handle research, qualification, writing, and CRM.",
    instructions="Delegate tasks to the appropriate specialist agent based on the request.",
)