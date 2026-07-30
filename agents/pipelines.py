"""Workflow pipelines: lead_pipeline and reply_triage."""

from agno.workflow import Condition, Step, Workflow

from app.config import settings
from app.schemas import LeadScore, TriageResult

from .crm_scribe import crm_scribe
from .outreach_writer import outreach_writer
from .qualifier import qualifier
from .researcher import researcher


# ── Step executors (defined before Workflows that reference them) ──


def _score_meets_threshold(step_input) -> bool:
    """Check if the lead score meets the ICP threshold."""
    outputs = getattr(step_input, "outputs", {}) or {}
    for key, value in outputs.items():
        if isinstance(value, dict) and "score" in value:
            return value.get("score", 0) >= settings.ICP_SCORE_THRESHOLD
        if isinstance(value, LeadScore):
            return value.score >= settings.ICP_SCORE_THRESHOLD
    return False


async def _approval_gate_step(ctx) -> dict:
    """Create an approval request and return the run_id for the demo runner."""
    import uuid

    from app.approvals import create_approval

    run_id = f"approval-{uuid.uuid4().hex[:8]}"
    outputs = getattr(ctx, "outputs", {}) or {}
    summary = "Outreach sequence ready for review."
    for val in outputs.values():
        if hasattr(val, "steps"):
            steps = val.steps
            if steps:
                summary = f"3-step sequence for {getattr(val, 'personalization_notes', 'review')}"
                summary += f"\nStep 1: {steps[0].subject}"
            break

    await create_approval(
        run_id=run_id,
        title="Outreach Approval Required",
        summary=summary,
    )
    return {"approval_run_id": run_id, "status": "pending"}


async def _push_and_log_step(ctx) -> dict:
    """Push the approved sequence to Instantly and log to HubSpot."""
    from app.integrations.registry import get_crm, get_outreach

    outputs = getattr(ctx, "outputs", {}) or {}
    results = {"campaign": None, "crm": []}

    draft = None
    for val in outputs.values():
        if hasattr(val, "steps"):
            draft = val
            break

    if draft:
        outreach = get_outreach()
        steps_data = [
            {"subject": s.subject, "body": s.body, "wait_days": s.wait_days}
            for s in draft.steps
        ]
        campaign = await outreach.create_campaign(
            name=f"Outreach - {getattr(draft, 'personalization_notes', 'Campaign')}",
            steps=steps_data,
        )
        results["campaign"] = campaign

    crm = get_crm()
    lead_info = {}
    for val in outputs.values():
        if isinstance(val, dict):
            if "company_name" in val:
                lead_info = val
                break

    if lead_info:
        company = await crm.upsert_company(
            domain=lead_info.get("domain", "unknown.com"),
            properties={"name": lead_info.get("company_name", "Unknown")},
        )
        results["crm"].append(("company", company))

    return results


async def _nurture_log_step(ctx) -> dict:
    """Log a low-score lead for nurture."""
    from app.integrations.registry import get_chat

    chat = get_chat()
    await chat.post_message(
        channel="#gtm-desk",
        text="Lead scored below threshold: added to nurture sequence.",
    )
    return {"action": "nurture", "status": "logged"}


async def _classify_reply_step(ctx) -> dict:
    """Classify an inbound reply using a fast model.

    S7.3: if the primary (Ollama) model fails or returns unusable output,
    retry once on Anthropic when a key is present — logged, never silent.
    """
    from agno.agent import Agent

    from app.models import get_fallback_model, get_model
    from app.prompts.triage import TRIAGE_INSTRUCTIONS

    reply_text = ""
    if hasattr(ctx, "input_data"):
        reply_text = str(ctx.input_data)
    elif hasattr(ctx, "outputs"):
        outputs = getattr(ctx, "outputs", {}) or {}
        reply_text = str(outputs)

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
        )
        run = await agent.arun(reply_text)
        return run.content if isinstance(run.content, TriageResult) else None

    primary = get_model("triage")
    try:
        result = await _classify(primary)
        if result is not None:
            return result.model_dump()
    except Exception as exc:
        print(f"[models] triage primary model failed: {exc}")

    fallback = get_fallback_model("triage")
    if fallback is not None and type(fallback) is not type(primary):
        print("[models] model_fallback: retrying triage on Anthropic")
        try:
            result = await _classify(fallback)
            if result is not None:
                return result.model_dump()
        except Exception as exc:
            print(f"[models] triage fallback model failed: {exc}")

    return TriageResult(
        category="other",
        summary="Could not classify reply automatically.",
    ).model_dump()


# ── Workflows ──

lead_pipeline = Workflow(
    name="lead_pipeline",
    description="End-to-end lead processing: research, qualify, draft outreach, approval gate, push to CRM + Instantly.",
    steps=[
        Step(
            name="research",
            agent=researcher,
            description="Research the lead's company and produce an account brief.",
        ),
        Step(
            name="qualify",
            agent=qualifier,
            description="Score the lead against the ICP rubric.",
        ),
        Condition(
            name="score_check",
            evaluator=lambda step_input: _score_meets_threshold(step_input),
            steps=[
                Step(
                    name="draft_outreach",
                    agent=outreach_writer,
                    description="Draft a 3-step email outreach sequence.",
                ),
                Step(
                    name="approval_gate",
                    executor=_approval_gate_step,
                    description="Post approval request and wait for human decision.",
                ),
                Step(
                    name="push_and_log",
                    executor=_push_and_log_step,
                    description="Push approved sequence to Instantly, log to HubSpot.",
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