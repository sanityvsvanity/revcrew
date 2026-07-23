"""Researcher agent: researches target accounts and produces AccountBrief."""

from agno.agent import Agent
from agno.models.anthropic import Claude

from app.config import settings
from app.schemas import AccountBrief
from app.toolkits.research_tools import lookup_company_enrichment, web_search_company

researcher = Agent(
    name="researcher",
    model=Claude(id=settings.MODEL_MAIN),
    description="Researches target accounts and prospects to build detailed account briefs.",
    instructions="""You are a B2B sales researcher. Given a lead (name, title, company, domain), research the company and produce a detailed account brief.

Use the available tools to gather information:
- `web_search_company` for web research
- `lookup_company_enrichment` for pre-loaded enrichment data

Your output must be a structured AccountBrief with:
- company_name, domain, snapshot (2-3 sentence overview)
- tech_signals (technology stack indicators)
- buying_triggers (events suggesting purchase intent)
- key_people (decision-makers identified)
- talking_points (personalized outreach angles)
- sources (where you found the information)

Be thorough but concise. Focus on actionable intelligence for outreach.""",
    tools=[web_search_company, lookup_company_enrichment],
    output_schema=AccountBrief,
)