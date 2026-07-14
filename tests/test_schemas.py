"""Tests for Pydantic schemas — instantiation and JSON round-trip."""

import json

from app.schemas import (
    AccountBrief,
    LeadScore,
    SequenceDraft,
    SequenceStep,
    TriageCategory,
    TriageResult,
)


class TestAccountBrief:
    def test_instantiation(self):
        brief = AccountBrief(
            company_name="Acme Corp",
            domain="acme.com",
            snapshot="A B2B SaaS company.",
            tech_signals=["Salesforce", "Slack"],
            buying_triggers=["Recent funding"],
            key_people=["Jane Doe - VP Sales"],
            talking_points=["AI-powered workflow"],
            sources=["https://acme.com"],
        )
        assert brief.company_name == "Acme Corp"
        assert brief.domain == "acme.com"

    def test_json_round_trip(self):
        brief = AccountBrief(
            company_name="Acme Corp",
            domain="acme.com",
            snapshot="A B2B SaaS company.",
        )
        data = brief.model_dump_json()
        reloaded = AccountBrief.model_validate_json(data)
        assert reloaded.company_name == "Acme Corp"
        assert reloaded.tech_signals == []

    def test_defaults(self):
        brief = AccountBrief(
            company_name="Test",
            domain="test.com",
            snapshot="Test snapshot.",
        )
        assert brief.tech_signals == []
        assert brief.buying_triggers == []
        assert brief.key_people == []
        assert brief.talking_points == []
        assert brief.sources == []


class TestLeadScore:
    def test_instantiation(self):
        score = LeadScore(
            score=85,
            tier="A",
            reasons=["Strong tech fit", "Recent funding"],
            disqualifiers=[],
        )
        assert score.score == 85
        assert score.tier == "A"

    def test_json_round_trip(self):
        score = LeadScore(score=50, tier="B")
        data = score.model_dump_json()
        reloaded = LeadScore.model_validate_json(data)
        assert reloaded.score == 50
        assert reloaded.tier == "B"

    def test_score_bounds(self):
        LeadScore(score=0, tier="C")
        LeadScore(score=100, tier="A")


class TestSequenceDraft:
    def test_instantiation(self):
        draft = SequenceDraft(
            steps=[
                SequenceStep(
                    subject="Quick question",
                    body="Hi {{first_name}}...",
                    wait_days=2,
                ),
                SequenceStep(
                    subject="Following up",
                    body="Wanted to check in...",
                    wait_days=3,
                ),
            ],
            personalization_notes="Personalized with tech stack mention.",
        )
        assert len(draft.steps) == 2
        assert draft.steps[0].subject == "Quick question"

    def test_json_round_trip(self):
        draft = SequenceDraft(
            steps=[
                SequenceStep(subject="Hello", body="World", wait_days=1),
            ],
        )
        data = draft.model_dump_json()
        reloaded = SequenceDraft.model_validate_json(data)
        assert len(reloaded.steps) == 1


class TestTriageResult:
    def test_instantiation(self):
        result = TriageResult(
            category=TriageCategory.INTERESTED,
            summary="Prospect wants pricing info.",
            suggested_reply="Here's our pricing page...",
            urgency="high",
        )
        assert result.category == TriageCategory.INTERESTED

    def test_json_round_trip(self):
        result = TriageResult(
            category=TriageCategory.OOO,
            summary="Out of office until Monday.",
        )
        data = result.model_dump_json()
        reloaded = TriageResult.model_validate_json(data)
        assert reloaded.category == TriageCategory.OOO
        assert reloaded.urgency == "normal"