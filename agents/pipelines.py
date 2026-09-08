"""Workflow pipelines: lead_pipeline and reply_triage.

lead_pipeline ends at the approval gate. That is the point of the gate: the
workflow's last act is to write the ``approvals`` row and post the card, and
the only path from there to HubSpot or Instantly is a human clicking Approve
(``app/webhooks/slack.py`` → ``app/push.py``). An earlier version ran a
``push_and_log`` step immediately after opening the gate, so the live intake
path pushed a campaign before anyone had clicked anything — a gate that the
scheduled path stepped around is not a gate (CoS LESSONS P43).
``tests/test_pipeline_shape.py`` pins this.

The research step is a custom executor rather than a bare agent step so the
research run (budget, ledger, grounding) wraps the agent call: it opens the
run, sets the context the tools read, awaits the researcher, grounds the
brief against the ledger, records the report and hands the qualifier a brief
that only cites what a tool returned.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agno.workflow import Condition, Step, Workflow
from agno.workflow.types import StepInput, StepOutput

from app.config import settings
from app.schemas import AccountBrief, LeadScore, TriageResult

from .crm_scribe import crm_scribe
from .outreach_writer import outreach_writer
from .qualifier import qualifier
from .researcher import researcher

logger = logging.getLogger(__name__)


# ── Step executors ──


def _lead_from_input(step_input: StepInput) -> dict[str, Any]:
    raw = step_input.input
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
    return {"raw": str(raw)}


def _lead_domain(lead: dict[str, Any]) -> str:
    domain = (
        (lead.get("domain") or "")
        .lower()
        .replace("https://", "")
        .replace("http://", "")
        .strip("/")
    )
    if domain:
        return domain[4:] if domain.startswith("www.") else domain
    email = lead.get("email") or ""
    return email.split("@", 1)[1].lower() if "@" in email else "unknown"


async def _research_step(step_input: StepInput) -> StepOutput:
    """Open a research run, run the researcher inside it, ground the brief."""
    from app.research import context as research_context
    from app.research import evidence
    from app.research.grounding import ground

    lead = _lead_from_input(step_input)
    domain = _lead_domain(lead)
    ctx = await evidence.start_run(domain, trigger="pipeline")
    token = research_context.activate(ctx)
    status = "done"
    try:
        run = await researcher.arun(input=json.dumps(lead))
        content = run.content
        if isinstance(content, AccountBrief):
            brief = content
        elif isinstance(content, dict):
            brief = AccountBrief.model_validate(content)
        else:
            brief = AccountBrief(
                company_name=lead.get("company", ""),
                domain=domain,
                snapshot="",
                gaps=["researcher returned no structured brief"],
            )
            status = "no_brief"
        allowed = await evidence.run_urls(ctx.run_id)
        grounded, report = ground(brief, allowed, evidence_records=ctx.ok_records)
        await evidence.finish_run(ctx, status=status, grounding=report.as_dict())
    except Exception as exc:
        await evidence.finish_run(
            ctx, status="error", grounding={"error": str(exc)[:500]}
        )
        raise
    finally:
        research_context.deactivate(token)

    payload = grounded.model_dump()
    payload["_research"] = {
        "run_id": ctx.run_id,
        "grounding": report.line(),
        "spent": {
            "calls": ctx.calls,
            "credits": round(ctx.credits, 2),
            "cost_usd": round(ctx.cost_usd, 4),
        },
    }
    return StepOutput(content=payload)


def _score_meets_threshold(step_input: StepInput) -> bool:
    """Check if the lead score meets the ICP threshold."""
    outputs = step_input.previous_step_outputs or {}
    for out in outputs.values():
        value = getattr(out, "content", out)
        if isinstance(value, LeadScore):
            return value.score >= settings.ICP_SCORE_THRESHOLD
        if isinstance(value, dict) and "score" in value:
            return int(value.get("score", 0)) >= settings.ICP_SCORE_THRESHOLD
    content = step_input.previous_step_content
    if isinstance(content, LeadScore):
        return content.score >= settings.ICP_SCORE_THRESHOLD
    return False


def _find(step_input: StepInput, predicate) -> Any:
    for out in (step_input.previous_step_outputs or {}).values():
        value = getattr(out, "content", out)
        if predicate(value):
            return value
    return None


async def _approval_gate_step(step_input: StepInput) -> dict:
    """Write the approval row and post the card. The workflow ends here."""
    import uuid

    from app.approvals import create_approval

    lead = _lead_from_input(step_input)
    draft = _find(step_input, lambda v: hasattr(v, "steps"))
    score = _find(step_input, lambda v: isinstance(v, LeadScore))
    brief = _find(step_input, lambda v: isinstance(v, dict) and "snapshot" in v)

    run_id = f"run-{uuid.uuid4().hex[:8]}"
    steps = draft.steps if draft else []
    summary = "Outreach sequence ready for review."
    if steps:
        summary = f"{len(steps)}-step sequence for {lead.get('company', 'the lead')}\nStep 1: {steps[0].subject}"

    data = {
        "lead": lead,
        "draft": draft.model_dump() if draft else {},
        "brief_snapshot": (brief or {}).get("snapshot", ""),
        "brief_sources": (brief or {}).get("sources", []),
        "brief_gaps": (brief or {}).get("gaps", []),
        "research": (brief or {}).get("_research", {}),
        "score": {"tier": score.tier, "score": score.score} if score else {},
        "deal": {
            "name": f"{lead.get('company', 'Lead')} - Outbound",
            "amount": lead.get("deal_amount", settings.DEAL_DEFAULT_AMOUNT or ""),
            "stage": lead.get("deal_stage", settings.DEAL_STAGE_DEFAULT),
        },
    }
    await create_approval(
        run_id=run_id,
        title=f"Outreach sequence for {lead.get('company', 'lead')}",
        summary=summary,
        channel=settings.SLACK_CHANNEL_ID or "#gtm-desk",
        data=data,
    )
    return {
        "approval_run_id": run_id,
        "status": "pending",
        "note": "Nothing is pushed until a human approves this card.",
    }


async def _nurture_log_step(step_input: StepInput) -> dict:
    """Log a low-score lead for nurture."""
    from app.integrations.registry import get_chat

    lead = _lead_from_input(step_input)
    chat = get_chat()
    await chat.post_message(
        channel=settings.SLACK_CHANNEL_ID or "#gtm-desk",
        text=f"Lead scored below threshold ({lead.get('company', 'unknown')}): added to nurture.",
    )
    return {"action": "nurture", "status": "logged"}


async def _classify_reply_step(step_input: StepInput) -> dict:
    """Classify an inbound reply using a fast model.

    If the primary (Ollama) model fails or returns unusable output, retry once
    on Anthropic when a key is present — logged, never silent.
    """
    from agno.agent import Agent

    from app.models import get_fallback_model, get_model, pipeline_agent_kwargs
    from app.prompts.triage import TRIAGE_INSTRUCTIONS

    reply_text = str(step_input.input or "")

    # Prospect text is untrusted — fence it unless the caller already did
    # (handle_reply fences before invoking the workflow).
    if "<crm_data" in reply_text:
        reply_text = reply_text[:2000]
    else:
        from app.toolkits.crm_tools import _fence_crm_data

        reply_text = _fence_crm_data(reply_text[:500])

    async def _classify(model) -> TriageResult | None:
        agent = Agent(
            model=model,
            output_schema=TriageResult,
            instructions=TRIAGE_INSTRUCTIONS,
            **pipeline_agent_kwargs(),
        )
        run = await agent.arun(reply_text)
        return run.content if isinstance(run.content, TriageResult) else None

    primary = get_model("triage")
    try:
        result = await _classify(primary)
        if result is not None:
            return result.model_dump()
    except Exception as exc:
        logger.warning("triage primary model failed: %s", exc)

    fallback = get_fallback_model("triage")
    if fallback is not None and type(fallback) is not type(primary):
        logger.warning("model_fallback: retrying triage on Anthropic")
        try:
            result = await _classify(fallback)
            if result is not None:
                return result.model_dump()
        except Exception as exc:
            logger.warning("triage fallback model failed: %s", exc)

    return TriageResult(
        category="other",
        summary="Could not classify reply automatically.",
    ).model_dump()


# ── Workflows ──

lead_pipeline = Workflow(
    name="lead_pipeline",
    description="Lead processing: research (evidence-graded), qualify, draft outreach, open the approval gate. Push happens only on human approval.",
    steps=[
        Step(
            name="research",
            executor=_research_step,
            description="Research the lead's company inside a budgeted, ledgered run and ground the brief.",
        ),
        Step(
            name="qualify",
            agent=qualifier,
            description="Score the lead against the ICP rubric.",
        ),
        Condition(
            name="score_check",
            evaluator=_score_meets_threshold,
            steps=[
                Step(
                    name="draft_outreach",
                    agent=outreach_writer,
                    description="Draft a 3-step email outreach sequence.",
                ),
                Step(
                    name="approval_gate",
                    executor=_approval_gate_step,
                    description="Post the approval card. The workflow ends here; Approve triggers the push.",
                ),
            ],
            else_steps=[
                Step(
                    name="nurture_log",
                    executor=_nurture_log_step,
                    description="Log low-score lead for nurture.",
                ),
            ],
        ),
    ],
)

reply_triage = Workflow(
    name="reply_triage",
    description="Classify inbound replies and create follow-up tasks.",
    steps=[
        Step(
            name="classify_reply",
            executor=_classify_reply_step,
            description="Classify the reply category and urgency.",
        ),
        Step(
            name="crm_update",
            agent=crm_scribe,
            description="Log the reply and create a follow-up task in HubSpot.",
        ),
    ],
)
