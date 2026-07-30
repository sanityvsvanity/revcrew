"""Slack webhook endpoints: events, actions, and slash commands."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.config import settings

router = APIRouter(prefix="/slack", tags=["slack"])


def _verify_slack_signature(body: bytes, headers: dict) -> bool:
    """Verify Slack's v0= HMAC-SHA256 signature.

    An empty signing secret fails closed: HMAC with an empty key would make
    forgery trivial. The only exception is a pure-mock dev demo (no bot
    token), where local unsigned curls are allowed with a warning.
    """
    if not settings.SLACK_SIGNING_SECRET:
        if not settings.SLACK_BOT_TOKEN and settings.DEMO_MODE and settings.ENV == "dev":
            print(
                "[slack] Warning: SLACK_SIGNING_SECRET empty — accepting "
                "unsigned request in dev demo mode"
            )
            return True
        return False

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
    """Handle Slack interactivity: approval button clicks and modal submissions."""
    body = await request.body()

    # Verify signature
    if not _verify_slack_signature(body, dict(request.headers)):
        return JSONResponse({"error": "invalid_signature"}, status_code=401)

    # Parse the payload (Slack sends as form-encoded)
    form = await request.form()
    payload_str = form.get("payload", "{}")
    payload = json.loads(payload_str) if isinstance(payload_str, str) else {}

    payload_type = payload.get("type", "")

    if payload_type == "block_actions":
        asyncio.create_task(_handle_block_actions(payload))
    elif payload_type == "view_submission":
        asyncio.create_task(_handle_view_submission(payload))
        # A modal submit ack must be an empty 200 (or a response_action),
        # or Slack shows an error inside the modal.
        return Response(status_code=200)

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


# ---------------------------------------------------------------------------
# Block action handler (button clicks)
# ---------------------------------------------------------------------------


async def _handle_block_actions(payload: dict):
    """Route button clicks: approve, edit, reject, view_emails."""
    actions = payload.get("actions", [])
    trigger_id = payload.get("trigger_id", "")
    user = payload.get("user", {})
    user_id = user.get("id", "")
    user_name = user.get("name", "a rep")

    for action in actions:
        value = action.get("value", "")
        if ":" not in value:
            continue
        run_id, action_type = value.split(":", 1)

        if action_type == "view_emails":
            await _handle_view_emails(run_id, trigger_id)
        elif action_type == "edit":
            await _handle_edit_click(run_id, trigger_id)
        elif action_type == "reject":
            await _handle_reject_click(run_id, trigger_id)
        elif action_type in ("approve", "retry"):
            await _handle_approval_action(run_id, action_type, payload, user_id, user_name)


async def _handle_view_emails(run_id: str, trigger_id: str):
    """Open a read-only modal showing full email bodies (S2.2)."""
    from app.approvals import _build_view_emails_modal, get_approval_status
    from app.integrations.registry import get_chat

    status = await get_approval_status(run_id)
    if not status:
        return

    data = status["payload"].get("data") or {}
    draft = data.get("draft") or {}
    view = _build_view_emails_modal(run_id, draft)

    chat = get_chat()
    await chat.open_modal(trigger_id, view)


async def _handle_edit_click(run_id: str, trigger_id: str):
    """Open the edit modal pre-filled from the approval payload (S2.3).

    The approval stays pending — the modal never locks the row, so closing
    it without submitting leaves the card fully usable.
    """
    from app.approvals import _build_edit_modal, get_approval_status
    from app.integrations.registry import get_chat

    status = await get_approval_status(run_id)
    if not status or status["status"] != "pending":
        return

    view = _build_edit_modal(run_id, status["payload"])

    chat = get_chat()
    await chat.open_modal(trigger_id, view)


async def _handle_reject_click(run_id: str, trigger_id: str):
    """Open the reject modal with reason select (S2.4)."""
    from app.approvals import _build_reject_modal
    from app.integrations.registry import get_chat

    view = _build_reject_modal(run_id)

    chat = get_chat()
    await chat.open_modal(trigger_id, view)


# ---------------------------------------------------------------------------
# View submission handler (modal submits)
# ---------------------------------------------------------------------------


async def _handle_view_submission(payload: dict):
    """Handle modal submissions: edit_submit and reject_submit."""
    callback_id = payload.get("view", {}).get("callback_id", "")
    user = payload.get("user", {})
    user_id = user.get("id", "")
    user_name = user.get("name", "a rep")

    if callback_id.startswith("edit_submit_"):
        run_id = callback_id.removeprefix("edit_submit_")
        await _handle_edit_submit(run_id, payload, user_name)
    elif callback_id.startswith("reject_submit_"):
        run_id = callback_id.removeprefix("reject_submit_")
        await _handle_reject_submit(run_id, payload, user_id, user_name)


async def _handle_edit_submit(run_id: str, payload: dict, user_name: str):
    """Apply edits from the edit modal and refresh the card in place (S2.3)."""
    from app.approvals import _build_approval_blocks, get_approval_status, record_edit
    from app.integrations.registry import get_chat

    # Extract values from the view state
    state = payload.get("view", {}).get("state", {}).get("values", {})
    edits: dict[str, Any] = {}
    for block_data in state.values():
        for action_id, action_data in block_data.items():
            if action_data.get("type") == "plain_text_input":
                edits[action_id] = action_data.get("value", "")

    chat = get_chat()
    updated = await record_edit(run_id, user_name, edits)
    if not updated:
        # Resolved (or expired) while the modal was open — say so instead
        # of dropping the edits silently.
        status = await get_approval_status(run_id)
        if status:
            p = status["payload"]
            await chat.post_message(
                channel=p.get("message_channel") or p.get("channel", "#gtm-desk"),
                text=(
                    f"✏️ @{user_name}'s edits were not applied — this approval "
                    f"is already {status['status']}."
                ),
                thread_ts=p.get("message_ts") or p.get("thread_ts"),
            )
        return

    # Refresh the original card in place so there is exactly one live card
    data = updated.get("data") or {}
    blocks = _build_approval_blocks(
        run_id,
        updated.get("title", "Outreach sequence"),
        data.get("lead") or {},
        data.get("draft") or {},
        data.get("deal") or {},
        data.get("score"),
    )

    message_ts = updated.get("message_ts")
    message_channel = updated.get("message_channel") or updated.get("channel", "#gtm-desk")
    if message_ts:
        await chat.update_message(
            channel=message_channel,
            ts=message_ts,
            text=f"Edited by @{user_name}",
            blocks=blocks,
        )
        await chat.post_message(
            channel=message_channel,
            text=f"✏️ Edited by @{user_name} — card updated, ready to approve.",
            thread_ts=message_ts,
        )
    else:
        # Card message unknown (older approval) — fall back to a fresh card
        thread_ts = updated.get("thread_ts")
        await chat.post_message(
            channel=message_channel,
            text=f"✏️ Edited by @{user_name} — re-review below.",
            thread_ts=thread_ts,
        )
        await chat.post_blocks(message_channel, blocks, thread_ts)


async def _handle_reject_submit(
    run_id: str, payload: dict, user_id: str, user_name: str
):
    """Record the reject reason and resolve the approval (S2.4)."""
    from app.approvals import (
        record_reject_reason,
        resolve_approval,
        update_approval_card,
    )
    from app.integrations.registry import get_chat

    # Extract values from the view state
    state = payload.get("view", {}).get("state", {}).get("values", {})
    reason = None
    detail = None
    for block_data in state.values():
        for action_id, action_data in block_data.items():
            if action_id == "reject_reason":
                selected = action_data.get("selected_option")
                if selected:
                    reason = selected.get("value")
            elif action_id == "reject_detail":
                detail = action_data.get("value", "")

    # Resolve first: only a pending → rejected transition records a reason
    result = await resolve_approval(run_id, "rejected")
    if result.get("status") in ("already_resolved", "not_found"):
        return

    await record_reject_reason(run_id, reason, detail)

    approval_payload = result.get("payload") or {}
    reason_label = {
        "wrong_contact": "Wrong contact",
        "bad_timing": "Bad timing",
        "tone_off": "Tone off",
        "other": "Other",
    }.get(reason or "", reason or "No reason given")
    status_line = f"❌ Rejected by @{user_name}: {reason_label}"

    # Replace the card's buttons, then leave the audit trail in its thread
    await update_approval_card(run_id, approval_payload, status_line)

    chat = get_chat()
    await chat.post_message(
        channel=approval_payload.get("message_channel")
        or approval_payload.get("channel", "#gtm-desk"),
        text=status_line,
        thread_ts=approval_payload.get("message_ts") or approval_payload.get("thread_ts"),
    )


# ---------------------------------------------------------------------------
# Approval action handler (approve)
# ---------------------------------------------------------------------------


async def _handle_approval_action(
    run_id: str, action: str, payload: dict, user_id: str, user_name: str
):
    """Resolve an approval from a Slack button click and push if approved.

    `action` is "approve" or "retry" (re-attempt a failed push of an
    already-approved run). Both trigger writes, so both sit behind the
    approver allowlist.
    """
    from app.approvals import resolve_approval, update_approval_card
    from app.integrations.registry import get_chat

    chat = get_chat()
    channel = payload.get("channel", {}).get("id", "")
    message_ts = payload.get("message", {}).get("ts", "")

    # Approver allowlist check (S2.7)
    approver_ids = settings.approver_ids
    if approver_ids and user_id not in approver_ids:
        # Send ephemeral — we can't do true ephemeral from the API easily,
        # so post a thread message that's clear
        await chat.post_message(
            channel=channel,
            text="⛔ Only designated approvers can resolve this. Ask an approver to review.",
            thread_ts=message_ts,
        )
        return

    if action == "retry":
        await _push_approved(run_id, channel, message_ts)
        return

    result = await resolve_approval(run_id, "approved")
    if result.get("status") in ("already_resolved", "not_found"):
        return

    # Replace the card's buttons so the resolved card can't be clicked again
    await update_approval_card(
        run_id, result.get("payload") or {}, f"✅ Approved by @{user_name}."
    )
    await chat.post_message(
        channel=channel,
        text=f"✅ Approved by @{user_name}.",
        thread_ts=message_ts,
    )

    # Approval unblocks the push: campaign to outreach, records to CRM
    await _push_approved(run_id, channel, message_ts)


async def _push_approved(run_id: str, channel: str, message_ts: str):
    """Push an approved run through the shared push path (S2.1, S2.6).

    push_approved_run records push_status itself ('pushed'/'push_failed'
    with per-stage progress); this wrapper only reports the outcome to the
    channel — with a working Retry button on failure.
    """
    from app.approvals import get_approval_status
    from app.integrations.registry import get_chat
    from app.push import push_approved_run

    status = await get_approval_status(run_id)
    if not status or status["status"] != "approved":
        return

    payload = status["payload"]
    chat = get_chat()

    try:
        result = await push_approved_run(run_id, payload, source="slack")

        data = payload.get("data") or {}
        lead = data.get("lead") or {}
        await chat.post_message(
            channel=channel or "#gtm-desk",
            text=(
                f"✅ Pushed {lead.get('company', 'the lead')}: campaign "
                f"{result['campaign']['id']} created paused, contact, company, "
                f"deal and note logged to CRM."
            ),
            thread_ts=message_ts or None,
        )
    except Exception as exc:
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"⚠️ *Push failed:* {str(exc)[:500]}\n"
                        f"Fix the issue and retry — already-succeeded stages "
                        f"are skipped."
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🔁 Retry push",
                            "emoji": True,
                        },
                        "value": f"{run_id}:retry",
                        "style": "primary",
                    },
                ],
            },
        ]
        await chat.post_blocks(channel or "#gtm-desk", blocks, message_ts or None)


# ---------------------------------------------------------------------------
# Background handlers
# ---------------------------------------------------------------------------


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
    from app.guard import set_write_context

    # Attribute any CRM writes the crew makes (crm_scribe's tools) to the
    # Slack message that triggered them — the guard refuses unattributed
    # writes, and the per-context cap bounds one conversation turn.
    set_write_context(f"chat:{channel}:{thread_ts}", "chat")

    run = await gtm_desk.arun(input=text)
    reply = run.content if isinstance(run.content, str) else str(run.content)
    await chat.post_message(channel=channel, text=reply, thread_ts=thread_ts)


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