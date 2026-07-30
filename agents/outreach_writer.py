"""Outreach writer agent: drafts email sequences, produces SequenceDraft."""

from agno.agent import Agent

from app.models import get_model
from app.prompts.outreach_writer import OUTREACH_WRITER_INSTRUCTIONS
from app.schemas import SequenceDraft

outreach_writer = Agent(
    name="outreach_writer",
    model=get_model("outreach_writer"),
    description="Drafts personalized outreach email sequences based on account briefs and ICP scores.",
    instructions=OUTREACH_WRITER_INSTRUCTIONS,
    output_schema=SequenceDraft,
)