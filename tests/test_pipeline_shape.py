"""The pipeline's shape is a safety property, and the research step is tested
end to end with a scripted model against a real Postgres."""

import json


from agents import pipelines
from tests.conftest import requires_db, run_db_test


def _step_names(steps):
    out = []
    for s in steps:
        out.append(s.name)
        for attr in ("steps", "else_steps"):
            out.extend(_step_names(getattr(s, attr, None) or []))
    return out


class TestShape:
    def test_workflow_ends_at_the_gate(self):
        """No step after approval_gate may touch CRM or outreach. Approve does."""
        names = _step_names(pipelines.lead_pipeline.steps)
        assert "approval_gate" in names
        assert "push_and_log" not in names, (
            "the push must only run from a human Approve"
        )
        cond = next(s for s in pipelines.lead_pipeline.steps if s.name == "score_check")
        assert [s.name for s in cond.steps] == ["draft_outreach", "approval_gate"]
        assert [s.name for s in cond.else_steps] == ["nurture_log"]

    def test_research_step_is_the_ledgered_executor(self):
        step = pipelines.lead_pipeline.steps[0]
        assert step.name == "research" and step.executor is pipelines._research_step

    def test_pipeline_agents_carry_no_history(self):
        from agents.crm_scribe import crm_scribe
        from agents.outreach_writer import outreach_writer
        from agents.qualifier import qualifier
        from agents.researcher import researcher

        for agent in (researcher, qualifier, outreach_writer, crm_scribe):
            assert agent.add_history_to_context is False, agent.name
            assert (
                agent.add_datetime_to_context is True and "%A" in agent.datetime_format
            ), agent.name

    def test_researcher_holds_the_whole_stack(self):
        from agents.researcher import researcher

        names = set(researcher.tools[0].async_functions)
        assert names == {
            "web_search",
            "fetch_page",
            "extract_page_fields",
            "hiring_signals",
            "news_signals",
            "crm_history",
            "lookup_company_enrichment",
        }


class TestScoreCheck:
    def test_reads_lead_score_from_previous_outputs(self):
        from agno.workflow.types import StepInput, StepOutput

        from app.config import settings
        from app.schemas import LeadScore

        hi = StepInput(
            input="x",
            previous_step_outputs={
                "qualify": StepOutput(
                    content=LeadScore(score=settings.ICP_SCORE_THRESHOLD, tier="B")
                )
            },
        )
        lo = StepInput(
            input="x",
            previous_step_outputs={
                "qualify": StepOutput(
                    content={"score": settings.ICP_SCORE_THRESHOLD - 1, "tier": "C"}
                )
            },
        )
        assert pipelines._score_meets_threshold(hi) is True
        assert pipelines._score_meets_threshold(lo) is False
        assert pipelines._score_meets_threshold(StepInput(input="x")) is False


class TestOllamaCloudGuard:
    def test_cloud_flips_structured_output_flags(self, monkeypatch):
        from app.config import settings
        from app.models import _build_ollama_model

        monkeypatch.setattr(settings, "OLLAMA_HOST", "")
        monkeypatch.setattr(settings, "OLLAMA_API_KEY", "k")
        m = _build_ollama_model("qualifier")
        assert (
            m.supports_native_structured_outputs is False
            and m.supports_json_schema_outputs is False
        )

    def test_local_daemon_keeps_native(self, monkeypatch):
        from app.config import settings
        from app.models import _build_ollama_model

        monkeypatch.setattr(settings, "OLLAMA_HOST", "http://localhost:11434")
        monkeypatch.setattr(settings, "OLLAMA_API_KEY", "")
        assert (
            _build_ollama_model("qualifier").supports_native_structured_outputs is True
        )


FABRICATED = "https://www.linkedin.com/in/jo-bloggs-ceo"
REAL = "https://acme.example/about"


@requires_db
def test_research_step_grounds_what_the_model_invents(monkeypatch):
    """The model fetches one real page, then cites it AND a URL no tool returned.
    The step must keep the first, strip the second, and record both facts."""

    async def scenario():
        from app.research import evidence
        from app.research.providers import scrape as scrape_providers
        from tests._scripted_model import ScriptedModel

        pool = await evidence.get_pool()
        async with pool.connection() as conn:
            await conn.execute("TRUNCATE evidence, research_runs")

        async def fake_jina(url):
            return {
                "provider": "jina",
                "status": "ok",
                "content": "About Acme. We forge anvils for 400 customers. " * 8,
                "title": "About Acme",
                "credits": 0.0,
                "latency_ms": 3,
                "error": "",
                "meta": {},
            }

        monkeypatch.setattr(scrape_providers, "chain", lambda: [("jina", fake_jina)])

        brief = {
            "company_name": "Acme",
            "domain": "acme.example",
            "snapshot": f"Acme forges anvils for 400 customers ({REAL}). CEO profile: {FABRICATED}.",
            "tech_signals": [],
            "buying_triggers": ["400 customers claimed on /about"],
            "key_people": ["Jo Bloggs, CEO"],
            "talking_points": ["anvil volume"],
            "sources": [REAL, FABRICATED],
            "gaps": [],
        }
        model = ScriptedModel(
            [("call", "fetch_page", {"url": REAL}), ("say", json.dumps(brief))]
        )
        monkeypatch.setattr(pipelines.researcher, "model", model)

        from agno.workflow.types import StepInput

        lead = {"email": "jo@acme.example", "company": "Acme", "domain": "acme.example"}
        out = await pipelines._research_step(StepInput(input=json.dumps(lead)))
        content = out.content
        assert content["sources"] == [REAL]
        assert FABRICATED not in content["snapshot"] and REAL in content["snapshot"]
        assert content["key_people"] == ["Jo Bloggs, CEO"], (
            "evidence exists, so unlinked claims stay"
        )
        assert any(
            "1 cited URL(s) not returned by any tool" in g for g in content["gaps"]
        )
        assert (
            content["_research"]["grounding"]
            == "1 source verified · 2 unverified links removed"
        )
        assert content["_research"]["spent"]["calls"] == 1

        summary = await evidence.run_summary(content["_research"]["run_id"])
        assert summary["status"] == "done" and summary["domain"] == "acme.example"
        assert summary["grounding"]["sources_removed"] == [FABRICATED]
        assert summary["breakdown"] == [
            {"tier": 2, "provider": "jina", "kind": "page", "status": "ok", "n": 1}
        ]
        assert model.calls == 2

    run_db_test(scenario)
