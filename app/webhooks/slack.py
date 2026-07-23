"""Slack webhook endpoints: events, actions, and slash commands."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import settings

router = APIRouter(prefix="/slack", tags=["slack"])


def _verify_slack_signature(body: bytes, headers: dict) -> bool:
    """Verify Slack's v0= HMAC-SHA256 signature."""
    signature = headers.get("x-slack-signature", "")
    timestamp = headers.get("x-slack-request-timestamp", "")

    if not signature or not timestamp:
        return False

    # Reject if timestamp is > 5 minutes old
    try:
        ts = int(timestamp)
        if abs(time.time() - ts) > 300:
            return False
    except ValueError:
        return False

    # Compute expected signature
    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = "v0=" + hmac.new(
        settings.SLACK_SIGNING_SECRET.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(signature, expected)


@router.post("/events")
async def slack_events(request: Request):
    """Handle Slack Events API: URL verification, app mentions, DMs."""
    body = await request.body()

    # URL verification challenge
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = json.loads(body)
        if data.get("type") == "url_verification":
            return JSONResponse({"challenge": data.get("challenge")})

    # Skip retries
    if request.headers.get("x-slack-retry-num"):
        return JSONResponse({"ok": True})

    # Verify signature
    if not _verify_slack_signature(body, dict(request.headers)):
        return JSONResponse({"error": "invalid_signature"}, status_code=401)

    # Parse event
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"ok": True})

    event = data.get("event", {})
    event_type = event.get("type", "")

    # Route to gtm_desk in background (ack < 3s)
    if event_type in ("app_mention", "message"):
        asyncio.create_task(_handle_incoming_message(event))

    return JSONResponse({"ok": True})


@router.post("/actions")
async def slack_actions(request: Request):
    """Handle Slack interactivity: approval button clicks."""
    body = await request.body()

    # Verify signature
    if not _verify_slack_signature(body, dict(request.headers)):
        return JSONResponse({"error": "invalid_signature"}, status_code=401)

    # Parse the payload (Slack sends as form-encoded)
    form = await request.form()
    payload_str = form.get("payload", "{}")
    payload = json.loads(payload_str) if isinstance(payload_str, str) else {}

    # Handle block_actions
    if payload.get("type") == "block_actions":
        actions = payload.get("actions", [])
        for action in actions:
            value = action.get("value", "")
            if ":" in value:
                run_id, action_type = value.split(":", 1)
                asyncio.create_task(_handle_approval_action(run_id, action_type, payload))

    return JSONResponse({"ok": True})


@router.post("/commands")
async def slack_commands(request: Request):
    """Handle /demo slash command."""
    body = await request.body()

    if not _verify_slack_signature(body, dict(request.headers)):
        return JSONResponse({"error": "invalid_signature"}, status_code=401)

    form = await request.form()
    command_text = form.get("text", "").strip()
    channel_id = form.get("channel_id", "")
    user_id = form.get("user_id", "")

    asyncio.create_task(_handle_demo_command(command_text, channel_id, user_id))

    return JSONResponse({"text": f"Running `/demo {command_text}`...", "response_type": "ephemeral"})


# Background handlers


async def _handle_incoming_message(event: dict):
    """Route incoming Slack mentions and DMs to the gtm_desk team."""
    from app.integrations.registry import get_chat

    text = event.get("text", "")
    channel = event.get("channel", "")
    thread_ts = event.get("thread_ts") or event.get("ts", "")

    # Strip bot mention prefix
    if text.startswith("<@"):
        parts = text.split(">", 1)
        text = parts[1].strip() if len(parts) > 1 else text

    chat = get_chat()

    if not settings.ANTHROPIC_API_KEY:
        await chat.post_message(
            channel=channel,
            text=(
                "Demo mode without an Anthropic key: the crew cannot answer "
                "free-form questions. Try /demo new-lead, or set "
                "ANTHROPIC_API_KEY to chat with the team."
            ),
            thread_ts=thread_ts,
        )
        return

    from agents.copilot import gtm_desk

    run = await gtm_desk.arun(input=text)
    reply = run.content if isinstance(run.content, str) else str(run.content)
    await chat.post_message(channel=channel, text=reply, thread_ts=thread_ts)


async def _handle_approval_action(run_id: str, action: str, payload: dict):
    """Resolve an approval from a Slack button click and finish the run."""
    from app.approvals import resolve_approval
    from app.integrations.registry import get_chat

    status_map = {"approve": "approved", "edit": "edit_requested", "reject": "rejected"}
    status = status_map.get(action, action)
    await resolve_approval(run_id, status)

    channel = payload.get("channel", {}).get("id", "")
    message_ts = payload.get("message", {}).get("ts", "")
    user = payload.get("user", {}).get("name", "a rep")

    chat = get_chat()
    labels = {"approved": "Approved", "edit_requested": "Edit requested", "rejected": "Rejected"}
    await chat.update_message(
        channel=channel,
        ts=message_ts,
        text=f"{labels.get(status, status)} by {user}.",
    )

    # Approval unblocks the push: campaign to outreach, records to CRM
    if status == "approved":
        from demo.pipeline import complete_run

        result = await complete_run(run_id)
        if result:
            await chat.post_message(
                channel=channel or "#gtm-desk",
                text=(
                    f"Pushed {result['lead']['company']}: campaign "
                    f"{result['campaign']['id']} created paused, contact, company, "
                    f"deal and note logged to CRM."
                ),
                thread_ts=message_ts or None,
            )


async def _handle_demo_command(command: str, channel_id: str, user_id: str):
    """Handle /demo subcommands by driving the real demo pipeline."""
    from app.integrations.registry import get_chat
    from demo.pipeline import inject_reply, next_lead_index, reset_state, start_run

    chat = get_chat()

    if command == "new-lead":
        index = await next_lead_index()
        run = await start_run(lead_index=index, channel=channel_id or "#gtm-desk")
        lead, score = run["lead"], run["score"]
        await chat.post_message(
            channel=channel_id,
            text=(
                f"New lead: {lead['first_name']} {lead['last_name']}, {lead['title']} "
                f"at {lead['company']}. Scored {score.score}/100, Tier {score.tier}. "
                f"Sequence drafted, waiting on your approval above."
            ),
        )
    elif command == "reply":
        dispatched = await inject_reply()
        await chat.post_message(
            channel=channel_id,
            text=f"Injected a canned reply through the event outbox, dispatched {dispatched} event(s).",
        )
    elif command == "reset":
        await reset_state()
        await chat.post_message(channel=channel_id, text="Mock state cleared.")
    else:
        await chat.post_message(
            channel=channel_id,
            text="Usage: /demo new-lead | reply | reset",
        )