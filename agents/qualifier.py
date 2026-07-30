"""Qualifier agent: scores leads against ICP rubric, produces LeadScore."""

from agno.agent import Agent

from app.models import get_model
from app.prompts.qualifier import QUALIFIER_INSTRUCTIONS
from app.schemas import LeadScore

qualifier = Agent(
    name="qualifier",
    model=get_model("qualifier"),
    description="Scores leads against the ICP rubric to determine fit tier.",
    instructions=QUALIFIER_INSTRUCTIONS,
    output_schema=LeadScore,
)