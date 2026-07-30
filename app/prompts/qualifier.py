"""Qualifier agent prompt, v1.1.0 (2026-07-30: rubric rendered from icp.yaml).

v1.0.0 hardcoded a copy of the rubric here; it is now built from the file the
docs tell users to edit, so the file is the single source of truth.
"""

from app.icp import load_icp, render_rubric


def build_qualifier_instructions() -> str:
    rubric = render_rubric(load_icp())
    return f"""You are a B2B lead qualification specialist. Given an account brief and the ICP rubric, score the lead on a 0-100 scale.

{rubric}

Output a LeadScore with score, tier, reasons (positive signals), and disqualifiers (concerns)."""


QUALIFIER_INSTRUCTIONS = build_qualifier_instructions()
