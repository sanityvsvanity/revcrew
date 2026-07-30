"""Researcher agent: researches target accounts and produces AccountBrief."""

from agno.agent import Agent

from app.models import get_model
from app.prompts.researcher import RESEARCHER_INSTRUCTIONS
from app.schemas import AccountBrief
from app.toolkits.research_tools import (
    crm_history,
    fetch_page,
    lookup_company_enrichment,
    web_search,
)

researcher = Agent(
    name="researcher",
    model=get_model("researcher"),
    description="Researches target accounts and prospects to build detailed account briefs.",
    instructions=RESEARCHER_INSTRUCTIONS,
    tools=[web_search, fetch_page, crm_history, lookup_company_enrichment],
    output_schema=AccountBrief,
)