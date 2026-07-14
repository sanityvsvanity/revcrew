"""Researcher agent — stub for M0 boot verification."""

from agno.agent import Agent
from agno.models.anthropic import Claude

from app.config import settings

researcher = Agent(
    name="researcher",
    model=Claude(id=settings.MODEL_MAIN),
    description="Researches target accounts and prospects to build detailed briefs.",
    instructions="You are a B2B sales researcher. Given a lead, research the company and produce an account brief.",
)