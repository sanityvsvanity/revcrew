"""Reply triage: classify an inbound reply and route the follow-up.

Demo mode uses a deterministic keyword classifier so the whole path runs with
zero credentials. With DEMO_MODE=false and an Anthropic key set, classification
runs through the reply_triage workflow instead.
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.integrations.registry import get_chat, get_crm
from app.schemas import TriageCategory, TriageResult

_RULES: list[tuple[TriageCategory, list[str]]] = [
    (TriageCategory.UNSUBSCRIBE, ["unsubscribe", "remove me", "take me off", "stop emailing"]),
    (TriageCategory.OOO, ["out of office", "annual leave", "on leave", "returning", "back in the office"]),
    (TriageCategory.OBJECTION, ["budget", "not in a position", "too expensive", "not right now", "check back", "next quarter"]),
    (TriageCategory.INTERESTED, ["pricing", "interested", "set up a call", "book a demo", "send over", "sounds good", "love to"]),
]

_SUGGESTED_REPLIES: dict[TriageCategory, str] = {
    TriageCategory.INTERESTED: (
        "Thanks {first_name}, glad it landed. I can walk you through pricing on a "
        "15 minute call. Does Tuesday or Wednesday afternoon work?"
    ),
    TriageCategory.OBJECTION: (
        "Understood, timing matters. I will check back closer to next quarter. "
        "If anything changes in the meantime, happy to talk sooner."
    ),
    TriageCategory.OOO: "",
    TriageCategory.UNSUBSCRIBE: "",
    TriageCategory.OTHER: "Thanks for the reply. Could you tell me a bit more about what you are looking for?",
}

_URGENCY: dict[TriageCategory, str] = {
    TriageCategory.INTERESTED: "high",
    TriageCategory.OBJECTION: "normal",
    TriageCategory.OOO: "low",
    TriageCategory.UNSUBSCRIBE: "normal",
    TriageCategory.OTHER: "normal",
}


def classify_reply(subject: str, body: str, first_name: str = "there") -> TriageResult:
    """Deterministic keyword classification. Used in demo mode and as fallback."""
    text = f"{subject}\n{body}".lower()
    category = TriageCategory.OTHER
    for cat, keywords in _RULES:
        if any(k in text for k in keywords):
            category = cat
            break

    summaries = {
        TriageCategory.INTERESTED: "Prospect is interested and asked for pricing and a call",
        TriageCategory.OBJECTION: "Prospect raised a timing or budget objection",
        TriageCategory.OOO: "Auto-reply: prospect is out of office",
        TriageCategory.UNSUBSCRIBE: "Prospect asked to be removed from the sequence",
        TriageCategory.OTHER: "Reply did not match a known category",
    }

    return TriageResult(
        category=category,
        summary=summaries[category],
        suggested_reply=_SUGGESTED_REPLIES[category].format(first_name=first_name),
        urgency=_URGENCY[category],
    )


async def handle_reply(payload: dict[str, Any]) -> TriageResult:
    """Triage an inbound reply, log to CRM, and alert the rep in chat.

    The suggested reply is a draft only. Nothing is ever sent automatically.
    """
    email = payload.get("from", "unknown")
    subject = payload.get("subject", "")
    body = payload.get("body", "")
    first_name = email.split(".")[0].split("@")[0].title() if email else "there"

    if settings.DEMO_MODE or not settings.ANTHROPIC_API_KEY:
        result = classify_reply(subject, body, first_name)
    else:
        from agents.pipelines import reply_triage

        run = await reply_triage.arun(input=f"Subject: {subject}\n\n{body}")
        result = TriageResult.model_validate_json(run.content) if isinstance(run.content, str) else run.content

    crm = get_crm()
    chat = get_chat()

    await crm.log_note("contact", email, f"Reply received ({result.category.value}): {result.summary}")

    if result.category in (TriageCategory.INTERESTED, TriageCategory.OBJECTION):
        await crm.create_task(
            f"Follow up with {first_name}: {result.summary}",
            {"email": email, "urgency": result.urgency},
        )

    if result.category == TriageCategory.UNSUBSCRIBE:
        await crm.log_note("contact", email, "Marked do-not-contact after unsubscribe request")

    alert_lines = [
        f"Reply from {email}: {result.category.value.upper()} (urgency: {result.urgency})",
        f"Summary: {result.summary}",
    ]
    if result.suggested_reply:
        alert_lines.append(f"Suggested reply (draft, not sent): {result.suggested_reply}")
    await chat.post_message("#gtm-desk", "\n".join(alert_lines))

    return result
