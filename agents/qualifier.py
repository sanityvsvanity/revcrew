"""Qualifier agent: scores leads against ICP rubric, produces LeadScore."""

from agno.agent import Agent
from agno.models.anthropic import Claude

from app.config import settings
from app.schemas import LeadScore

qualifier = Agent(
    name="qualifier",
    model=Claude(id=settings.MODEL_FAST),
    description="Scores leads against the ICP rubric to determine fit tier.",
    instructions="""You are a B2B lead qualification specialist. Given an account brief and the ICP rubric, score the lead on a 0-100 scale.

The ICP rubric criteria and weights:
- Industry fit (25%): B2B SaaS, 11-200 employees ideal. Exclude agencies, marketplaces, non-profits.
- Size fit (20%): Company size alignment.
- Tech signals (20%): Technology stack sophistication.
- Buying triggers (20%): Recent events suggesting purchase intent.
- Seniority of contact (15%): VP+ scores higher.

Tier cutoffs:
- A: score >= 80 (strong fit, fast-track to outreach)
- B: score >= {threshold} (moderate fit)
- C: below threshold (nurture only)

Hard disqualifiers:
- Agency or marketing services firm
- Fewer than 5 employees
- Direct competitor
- Personal email domain (gmail, yahoo, etc.)

Output a LeadScore with score, tier, reasons (positive signals), and disqualifiers (concerns).""".format(threshold=settings.ICP_SCORE_THRESHOLD),
    output_schema=LeadScore,
)