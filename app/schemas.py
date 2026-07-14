"""Pydantic schemas for RevCrew pipeline outputs."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AccountBrief(BaseModel):
    """Research output: a detailed brief about a target account."""

    company_name: str = Field(description="Company name")
    domain: str = Field(description="Company website domain")
    snapshot: str = Field(description="2-3 sentence company overview")
    tech_signals: list[str] = Field(
        default_factory=list,
        description="Technology stack signals (tools, platforms detected)",
    )
    buying_triggers: list[str] = Field(
        default_factory=list,
        description="Events or signals suggesting purchase intent",
    )
    key_people: list[str] = Field(
        default_factory=list,
        description="Key decision-makers identified",
    )
    talking_points: list[str] = Field(
        default_factory=list,
        description="Personalized talking points for outreach",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Sources used for research",
    )


class LeadScore(BaseModel):
    """Qualification output: ICP fit score and tier."""

    score: int = Field(ge=0, le=100, description="ICP fit score 0-100")
    tier: str = Field(description="Tier: A, B, or C")
    reasons: list[str] = Field(
        default_factory=list,
        description="Positive signals contributing to score",
    )
    disqualifiers: list[str] = Field(
        default_factory=list,
        description="Hard disqualifiers or concerns",
    )


class SequenceStep(BaseModel):
    """A single step in an outreach sequence."""

    subject: str = Field(description="Email subject line")
    body: str = Field(description="Email body text")
    wait_days: int = Field(default=1, ge=0, description="Days to wait before next step")


class SequenceDraft(BaseModel):
    """Outreach writer output: a draft email sequence."""

    steps: list[SequenceStep] = Field(
        default_factory=list,
        min_length=1,
        max_length=5,
        description="Sequence steps (typically 3)",
    )
    personalization_notes: str = Field(
        default="",
        description="Notes on how the sequence was personalized",
    )


class TriageCategory(str, Enum):
    INTERESTED = "interested"
    OBJECTION = "objection"
    OOO = "ooo"
    UNSUBSCRIBE = "unsubscribe"
    OTHER = "other"


class TriageResult(BaseModel):
    """Reply triage output: classification and suggested action."""

    category: TriageCategory = Field(description="Classification of the reply")
    summary: str = Field(description="One-line summary of the reply")
    suggested_reply: str = Field(
        default="",
        description="Draft suggested reply (never auto-sent)",
    )
    urgency: str = Field(
        default="normal",
        description="Urgency: low, normal, or high",
    )