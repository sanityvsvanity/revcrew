"""Approval gate: Postgres-backed human-in-the-loop for workflow steps.

S2.2: Progressive-disclosure card (lead line, score, subjects, deal, manifest, View emails).
S2.3: Edit modal pre-filled from payload, round-trip with edits tracking.
S2.4: Reject captures reason + optional detail.
S2.5: Expiry and reminder support (driven by housekeeping scheduler).
S2.6: Push-status tracking for partial-failure visibility.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.db import get_pool
from app.integrations.registry import get_chat


# ---------------------------------------------------------------------------
# Card builder (S2.2)
# ---------------------------------------------------------------------------

def _build_approval_blocks(
    run_id: str,
    title: str,
    lead: dict[str, Any],
    draft: dict[str, Any],
    deal: dict[str, Any],
    score: dict[str, Any] | None = None,
    status_line: str | None = None,
) -> list[dict[str, Any]]:
    """Build the progressive-disclosure approval card.

    Card shows: lead line, score/tier, three subject lines, deal line,
    writes manifest, and Approve/Edit/Reject/View emails buttons.
    With `status_line` set the card is resolved: the buttons are replaced
    by the status text so a stale card can't be clicked.
    """
    first_name = lead.get("first_name", "")
    last_name = lead.get("last_name", "")
    company = lead.get("company", "")
    title_str = lead.get("title", "")

    lead_line = f"*{first_name} {last_name}*"
    if title_str:
        lead_line += f", {title_str}"
    lead_line += f" at *{company}*"

    score_line = ""
    if score:
        tier = score.get("tier", "?")
        score_val = score.get("score", 0)
        score_line = f"Score: {score_val}/100, Tier {tier}"

    steps = draft.get("steps", [])
    subject_lines = "\n".join(
        f"• *{i+1}.* {s.get('subject', '(no subject)')}"
        for i, s in enumerate(steps[:3])
    )

    deal_name = deal.get("name", f"{company} - Outbound")
    deal_amount = deal.get("amount", "")
    deal_stage = deal.get("stage", "prospecting")
    deal_line = f"Deal: *{deal_name}*"
    if deal_amount:
        deal_line += f" — ${deal_amount}"
    deal_line += f" ({deal_stage})"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": title, "emoji": True},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": lead_line},
        },
    ]

    if score_line:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": score_line}}
        )

    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Subjects:*\n{subject_lines}"},
        }
    )

    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": deal_line},
        }
    )

    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "_Will create: contact, company, deal, 1 note · "
                    "campaign starts paused_"
                ),
            },
        }
    )

    blocks.append({"type": "divider"})

    if status_line:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": status_line}}
        )
        return blocks

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve", "emoji": True},
                    "value": f"{run_id}:approve",
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✏️ Edit", "emoji": True},
                    "value": f"{run_id}:edit",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Reject", "emoji": True},
                    "value": f"{run_id}:reject",
                    "style": "danger",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "📧 View emails",
                        "emoji": True,
                    },
                    "value": f"{run_id}:view_emails",
                },
            ],
        }
    )

    return blocks


def _build_view_emails_modal(
    run_id: str, draft: dict[str, Any]
) -> dict[str, Any]:
    """Build a read-only modal showing all three full email bodies."""
    steps = draft.get("steps", [])
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📧 Email sequence", "emoji": True},
        },
    ]

    for i, step in enumerate(steps[:3]):
        subject = step.get("subject", "(no subject)")
        body = step.get("body", "(no body)")
        # The whole section text (heading + body) must fit Slack's
        # 3,000-char section limit, or views.open rejects the modal.
        heading = f"*Email {i+1}: {subject}*\n\n"
        body = body[: 3000 - len(heading)]
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": heading + body,
                },
            }
        )

    return {
        "type": "modal",
        "callback_id": f"view_emails_{run_id}",
        "title": {"type": "plain_text", "text": "Email sequence", "emoji": True},
        "close": {"type": "plain_text", "text": "Close", "emoji": True},
        "blocks": blocks,
    }


def _build_edit_modal(
    run_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Build an edit modal pre-filled from the approval payload."""
    data = payload.get("data") or {}
    draft = data.get("draft") or {}
    deal = data.get("deal") or {}
    steps = draft.get("steps", [])

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "✏️ Edit outreach", "emoji": True},
        },
    ]

    for i, step in enumerate(steps[:3]):
        subject = step.get("subject", "")
        body = step.get("body", "")
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Email {i+1}*",
                },
            }
        )
        blocks.append(
            {
                "type": "input",
                "block_id": f"subject_{i}",
                "label": {"type": "plain_text", "text": "Subject", "emoji": True},
                "element": {
                    "type": "plain_text_input",
                    "action_id": f"subject_{i}",
                    "initial_value": subject,
                    "max_length": 200,
                },
            }
        )
        blocks.append(
            {
                "type": "input",
                "block_id": f"body_{i}",
                "label": {"type": "plain_text", "text": "Body", "emoji": True},
                "element": {
                    "type": "plain_text_input",
                    "action_id": f"body_{i}",
                    "initial_value": body[:3000],
                    "multiline": True,
                    "max_length": 3000,
                },
            }
        )

    # Deal fields
    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Deal*"},
        }
    )
    blocks.append(
        {
            "type": "input",
            "block_id": "deal_name",
            "label": {"type": "plain_text", "text": "Deal name", "emoji": True},
            "element": {
                "type": "plain_text_input",
                "action_id": "deal_name",
                "initial_value": deal.get("name", ""),
                "max_length": 200,
            },
        }
    )
    blocks.append(
        {
            "type": "input",
            "block_id": "deal_amount",
            "label": {"type": "plain_text", "text": "Amount", "emoji": True},
            "element": {
                "type": "plain_text_input",
                "action_id": "deal_amount",
                "initial_value": str(deal.get("amount", "")),
                "max_length": 20,
            },
        }
    )

    return {
        "type": "modal",
        "callback_id": f"edit_submit_{run_id}",
        "title": {"type": "plain_text", "text": "Edit outreach", "emoji": True},
        "submit": {"type": "plain_text", "text": "Save", "emoji": True},
        "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
        "blocks": blocks,
        "private_metadata": run_id,
    }


def _build_reject_modal(run_id: str) -> dict[str, Any]:
    """Build a reject modal with reason select + optional text."""
    return {
        "type": "modal",
        "callback_id": f"reject_submit_{run_id}",
        "title": {"type": "plain_text", "text": "Reject outreach", "emoji": True},
        "submit": {"type": "plain_text", "text": "Reject", "emoji": True},
        "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
        "blocks": [
            {
                "type": "input",
                "block_id": "reject_reason",
                "label": {
                    "type": "plain_text",
                    "text": "Reason (optional)",
                    "emoji": True,
                },
                "element": {
                    "type": "static_select",
                    "action_id": "reject_reason",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select a reason",
                        "emoji": True,
                    },
                    "options": [
                        {
                            "text": {
                                "type": "plain_text",
                                "text": "Wrong contact",
                                "emoji": True,
                            },
                            "value": "wrong_contact",
                        },
                        {
                            "text": {
                                "type": "plain_text",
                                "text": "Bad timing",
                                "emoji": True,
                            },
                            "value": "bad_timing",
                        },
                        {
                            "text": {
                                "type": "plain_text",
                                "text": "Tone off",
                                "emoji": True,
                            },
                            "value": "tone_off",
                        },
                        {
                            "text": {
                                "type": "plain_text",
                                "text": "Other",
                                "emoji": True,
                            },
                            "value": "other",
                        },
                    ],
                },
            },
            {
                "type": "input",
                "block_id": "reject_detail",
                "label": {
                    "type": "plain_text",
                    "text": "Details (optional)",
                    "emoji": True,
                },
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "reject_detail",
                    "multiline": True,
                    "max_length": 500,
                },
            },
        ],
        "private_metadata": run_id,
    }


# ---------------------------------------------------------------------------
# Core approval operations
# ---------------------------------------------------------------------------


async def create_approval(
    run_id: str,
    title: str,
    summary: str,
    channel: str = "#gtm-desk",
    thread_ts: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an approval request: write row + post Block Kit card.

    `data` carries the full payload: lead, draft, deal, score, brief_snapshot.
    The card is built from data fields per S2.2.
    """
    pool = await get_pool()
    payload = {
        "run_id": run_id,
        "title": title,
        "summary": summary,
        "channel": channel,
        "thread_ts": thread_ts,
        "data": data or {},
    }
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO approvals (run_id, payload, status) VALUES (%s, %s, 'pending') "
            "ON CONFLICT (run_id) DO UPDATE SET status = 'pending', payload = EXCLUDED.payload",
            (run_id, json.dumps(payload)),
        )

    chat = get_chat()
    result = await chat.open_approval(
        channel=channel,
        run_id=run_id,
        title=title,
        summary=summary,
        thread_ts=thread_ts,
        data=data or {},
    )

    # Remember where the card landed so it can be updated in place on
    # approve/reject/edit/expiry instead of leaving live buttons behind.
    message_ts = result.get("ts", "")
    message_channel = result.get("channel", channel)
    if message_ts:
        payload["message_ts"] = message_ts
        payload["message_channel"] = message_channel
        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE approvals SET payload = %s WHERE run_id = %s",
                (json.dumps(payload), run_id),
            )
    return result


async def resolve_approval(run_id: str, action: str) -> dict[str, Any]:
    """Resolve an approval: update row status, return resolution.

    Only transitions from 'pending' are allowed — a double-click on Approve
    returns 'already_resolved' and does nothing (S0.5).
    """
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "UPDATE approvals SET status = %s, resolved_at = NOW() "
            "WHERE run_id = %s AND status = 'pending' RETURNING payload",
            (action, run_id),
        )
        row = await cur.fetchone()
        if not row:
            cur2 = await conn.execute(
                "SELECT status FROM approvals WHERE run_id = %s", (run_id,)
            )
            existing = await cur2.fetchone()
            if existing:
                return {"run_id": run_id, "status": "already_resolved"}
            return {"run_id": run_id, "status": "not_found"}
        payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return {"run_id": run_id, "status": action, "payload": payload}


async def get_approval_status(run_id: str) -> dict[str, Any] | None:
    """Check the status of an approval."""
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT status, payload FROM approvals WHERE run_id = %s",
            (run_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        payload = row[1] if isinstance(row[1], dict) else json.loads(row[1])
        return {"run_id": run_id, "status": row[0], "payload": payload}


# ---------------------------------------------------------------------------
# Edit round-trip (S2.3)
# ---------------------------------------------------------------------------


async def record_edit(
    run_id: str,
    user: str,
    edits: dict[str, Any],
) -> dict[str, Any] | None:
    """Apply edits to a still-pending approval's payload.

    The approval stays pending throughout — opening the edit modal never
    locks the row, so an abandoned modal can't strand the approval.
    Returns the updated payload, or None if the approval no longer exists
    or was resolved while the modal was open (the edits are dropped).
    """
    pool = await get_pool()
    edit_entry = {
        "user": user,
        "when": datetime.now(timezone.utc).isoformat(),
        "fields": edits,
    }
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT payload FROM approvals WHERE run_id = %s AND status = 'pending'",
            (run_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        data = payload.get("data") or {}

        # Apply edits to draft steps
        draft = data.get("draft") or {}
        steps = draft.get("steps", [])
        for i, step in enumerate(steps[:3]):
            subj_key = f"subject_{i}"
            body_key = f"body_{i}"
            if subj_key in edits:
                step["subject"] = edits[subj_key]
            if body_key in edits:
                step["body"] = edits[body_key]

        # Apply edits to deal
        deal = data.get("deal") or {}
        if "deal_name" in edits:
            deal["name"] = edits["deal_name"]
        if "deal_amount" in edits:
            deal["amount"] = edits["deal_amount"]

        # Track edits
        existing_edits: list = payload.get("edits") or []
        existing_edits.append(edit_entry)

        payload["edits"] = existing_edits
        payload["data"] = data

        cur = await conn.execute(
            "UPDATE approvals SET payload = %s, edits = %s "
            "WHERE run_id = %s AND status = 'pending' RETURNING run_id",
            (json.dumps(payload), json.dumps(existing_edits), run_id),
        )
        if not await cur.fetchone():
            return None
        return payload


# ---------------------------------------------------------------------------
# Reject with reason (S2.4)
# ---------------------------------------------------------------------------


async def record_reject_reason(
    run_id: str, reason: str | None, detail: str | None
) -> None:
    """Store the reject reason and optional detail on the approval row."""
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE approvals SET reject_reason = %s, reject_detail = %s "
            "WHERE run_id = %s",
            (reason, detail, run_id),
        )


# ---------------------------------------------------------------------------
# Push status tracking (S2.6)
# ---------------------------------------------------------------------------


async def record_push_status(
    run_id: str, status: str, detail: dict[str, Any] | None = None
) -> None:
    """Record push outcome: 'pushed' or 'push_failed' with per-stage detail."""
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE approvals SET push_status = %s, push_detail = %s "
            "WHERE run_id = %s",
            (status, json.dumps(detail) if detail else None, run_id),
        )


async def get_push_detail(run_id: str) -> dict[str, Any] | None:
    """Return the stored push detail (error + per-stage progress), if any."""
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT push_detail FROM approvals WHERE run_id = %s", (run_id,)
        )
        row = await cur.fetchone()
        if row and row[0]:
            return row[0] if isinstance(row[0], dict) else json.loads(row[0])
    return None


# ---------------------------------------------------------------------------
# Expiry and reminders (S2.5)
# ---------------------------------------------------------------------------


async def expire_stale_approvals() -> int:
    """Expire approvals past TTL. Returns count of expired."""
    pool = await get_pool()
    async with pool.connection() as conn:
        # NB: %s inside a quoted INTERVAL literal is not a placeholder —
        # multiply a unit interval instead.
        cur = await conn.execute(
            "UPDATE approvals SET status = 'expired', resolved_at = NOW() "
            "WHERE status = 'pending' "
            "AND created_at < NOW() - %s * INTERVAL '1 hour' "
            "RETURNING run_id, payload",
            (settings.APPROVAL_TTL_HOURS,),
        )
        rows = await cur.fetchall()

    # Kill the buttons on each expired card so it can't be clicked later.
    for run_id, payload_raw in rows:
        payload = payload_raw if isinstance(payload_raw, dict) else json.loads(payload_raw)
        await update_approval_card(
            run_id,
            payload,
            f"⌛ Expired after {settings.APPROVAL_TTL_HOURS}h without a decision.",
        )
    return len(rows)


async def update_approval_card(
    run_id: str, payload: dict[str, Any], status_line: str
) -> None:
    """Replace the card's buttons with a status line, if we know where it is.

    Best-effort: approvals created before message tracking (or whose post
    failed) are left alone — the pending-only state machine still protects
    them from double resolution.
    """
    message_ts = payload.get("message_ts")
    message_channel = payload.get("message_channel") or payload.get("channel")
    if not message_ts or not message_channel:
        return

    data = payload.get("data") or {}
    blocks = _build_approval_blocks(
        run_id,
        payload.get("title", "Approval"),
        data.get("lead") or {},
        data.get("draft") or {},
        data.get("deal") or {},
        data.get("score"),
        status_line=status_line,
    )
    try:
        chat = get_chat()
        await chat.update_message(
            channel=message_channel,
            ts=message_ts,
            text=status_line,
            blocks=blocks,
        )
    except Exception as exc:
        print(f"[approvals] Could not update card for {run_id}: {exc}")


async def send_reminders() -> int:
    """Send one reminder per pending approval past the reminder threshold.
    Returns count of reminders sent.
    """
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT run_id, payload FROM approvals "
            "WHERE status = 'pending' AND reminder_sent = FALSE "
            "AND created_at < NOW() - %s * INTERVAL '1 hour'",
            (settings.APPROVAL_REMINDER_HOURS,),
        )
        rows = await cur.fetchall()

    chat = get_chat()
    sent = 0
    for row in rows:
        run_id = row[0]
        payload = row[1] if isinstance(row[1], dict) else json.loads(row[1])
        channel = payload.get("message_channel") or payload.get("channel", "#gtm-desk")
        # Thread the reminder under the card itself when we know its ts.
        thread_ts = payload.get("message_ts") or payload.get("thread_ts")
        title = payload.get("title", "Pending approval")

        await chat.post_message(
            channel=channel,
            text=f"⏰ Reminder: *{title}* is still pending approval.",
            thread_ts=thread_ts,
        )

        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE approvals SET reminder_sent = TRUE WHERE run_id = %s",
                (run_id,),
            )
        sent += 1

    return sent


# ---------------------------------------------------------------------------
# Digest queries (S3.1)
# ---------------------------------------------------------------------------


async def get_approval_summary() -> dict[str, Any]:
    """Return counts for the daily digest."""
    pool = await get_pool()
    async with pool.connection() as conn:
        # Pending count
        cur = await conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE status = 'pending'"
        )
        pending = (await cur.fetchone())[0]

        # Approved today
        cur = await conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE status = 'approved' "
            "AND resolved_at >= CURRENT_DATE"
        )
        approved_today = (await cur.fetchone())[0]

        # Rejected today with reasons
        cur = await conn.execute(
            "SELECT reject_reason, COUNT(*) FROM approvals "
            "WHERE status = 'rejected' AND resolved_at >= CURRENT_DATE "
            "AND reject_reason IS NOT NULL "
            "GROUP BY reject_reason"
        )
        reject_reasons = {row[0]: row[1] for row in await cur.fetchall()}

        # Expired today
        cur = await conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE status = 'expired' "
            "AND resolved_at >= CURRENT_DATE"
        )
        expired_today = (await cur.fetchone())[0]

        # Push failures
        cur = await conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE push_status = 'push_failed'"
        )
        push_failures = (await cur.fetchone())[0]

    return {
        "pending": pending,
        "approved_today": approved_today,
        "rejected_today": sum(reject_reasons.values()),
        "reject_reasons": reject_reasons,
        "expired_today": expired_today,
        "push_failures": push_failures,
    }