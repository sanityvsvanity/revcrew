"""Copilot agent + gtm_desk Team — the Slack-facing AI assistant for reps."""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.team import Team

from app.config import settings
from app.toolkits.crm_tools import hubspot_search_contact

from .crm_scribe import crm_scribe
from .outreach_writer import outreach_writer
from .qualifier import qualifier
from .researcher import researcher

copilot = Agent(
    name="copilot",
    model=Claude(id=settings.MODEL_MAIN),
    description="Slack-facing AI assistant for sales reps — answers questions, runs research, checks pipeline status.",
    instructions="""You are RevCrew Copilot, an AI assistant for B2B sales reps. You live in Slack and help with:

- Researching companies and contacts
- Checking pipeline and approval status
- Preparing call briefs ("prep me for the Acme call")
- Answering questions about leads, deals, and sequences

You have access to CRM read tools and can delegate research to specialist agents.
Always be concise and actionable. When asked to prep for a call, pull the account brief, recent notes, and suggest talking points.

Never push to Instantly or create deals directly — those require human approval through the pipeline.""",
    tools=[hubspot_search_contact],
)

gtm_desk = Team(
    name="gtm_desk",
    model=Claude(id=settings.MODEL_MAIN),
    members=[copilot, researcher, qualifier, outreach_writer, crm_scribe],
    description="The full GTM desk team — copilot leads, specialists handle research, qualification, writing, and CRM.",
    instructions="Delegate tasks to the appropriate specialist agent based on the request.",
)
