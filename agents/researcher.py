"""Researcher agent: researches target accounts and produces an AccountBrief.

The researcher keeps no history and no memory. An earlier research agent started at 145K prompt tokens
before its first tool call because it replayed prior runs, and facts from one prospect leaked into the
next. Every account here starts from the lead and the tools.
"""

from agno.agent import Agent

from app.models import get_model, pipeline_agent_kwargs
from app.prompts.researcher import RESEARCHER_INSTRUCTIONS
from app.schemas import AccountBrief
from app.toolkits.research_tools import research_tools

researcher = Agent(
    name="researcher",
    model=get_model("researcher"),
    description="Researches target accounts and prospects to build evidence-based account briefs.",
    instructions=RESEARCHER_INSTRUCTIONS,
    tools=[research_tools],
    output_schema=AccountBrief,
    tool_call_limit=30,
    **pipeline_agent_kwargs(),
)
