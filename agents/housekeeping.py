"""Housekeeping: scheduled jobs for approval expiry, reminders, and daily digest.

S2.5: Hourly sweep for approval reminders and expiry.
S3.1: Daily digest posted to the channel.
S5.4: Retention purge of old audit and approval rows.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

# Module-level scheduler — discovered by runtime.py (S0.7)
scheduler = AsyncIOScheduler()


async def _expire_and_remind():
    """Hourly: expire stale approvals, send reminders."""
    from app.approvals import expire_stale_approvals, send_reminders

    expired = await expire_stale_approvals()
    if expired:
        print(f"[housekeeping] Expired {expired} stale approval(s)")

    reminded = await send_reminders()
    if reminded:
        print(f"[housekeeping] Sent {reminded} approval reminder(s)")


async def _daily_digest():
    """Daily: post the digest to the configured channel (S3.1)."""
    from app.approvals import get_approval_summary
    from app.db import get_pool
    from app.integrations.registry import get_chat

    summary = await get_approval_summary()

    # Count CRM writes today
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM write_audit "
            "WHERE decision = 'allowed' AND created_at >= CURRENT_DATE"
        )
        crm_writes = (await cur.fetchone())[0]

        # Count dead-letter events
        cur = await conn.execute(
            "SELECT COUNT(*) FROM events WHERE status = 'dead_letter'"
        )
        dead_letters = (await cur.fetchone())[0]

    # Build digest text
    lines = ["*📊 Daily Digest*", ""]

    if summary["approved_today"]:
        lines.append(f"✅ *Approved:* {summary['approved_today']} sequence(s) pushed")
    else:
        lines.append("✅ *Approved:* none today")

    if summary["pending"]:
        lines.append(f"⏳ *Pending:* {summary['pending']} approval(s) waiting")
    else:
        lines.append("⏳ *Pending:* none")

    if summary["rejected_today"]:
        reason_parts = []
        for reason, count in summary.get("reject_reasons", {}).items():
            label = {
                "wrong_contact": "Wrong contact",
                "bad_timing": "Bad timing",
                "tone_off": "Tone off",
                "other": "Other",
            }.get(reason, reason)
            reason_parts.append(f"{label} ×{count}")
        lines.append(f"❌ *Rejected:* {summary['rejected_today']} ({', '.join(reason_parts)})")
    else:
        lines.append("❌ *Rejected:* none today")

    if summary["expired_today"]:
        lines.append(f"⌛ *Expired:* {summary['expired_today']} stale approval(s)")

    lines.append(f"📝 *CRM writes:* {crm_writes}")

    # Needs attention section
    attention: list[str] = []
    if dead_letters:
        attention.append(f"{dead_letters} dead-letter event(s)")
    if summary["push_failures"]:
        attention.append(f"{summary['push_failures']} push failure(s)")

    if attention:
        lines.append("")
        lines.append(f"⚠️ *Needs attention:* {', '.join(attention)}")
    elif not any(
        [
            summary["approved_today"],
            summary["pending"],
            summary["rejected_today"],
            summary["expired_today"],
            crm_writes,
        ]
    ):
        lines.append("")
        lines.append("_Quiet day: nothing processed, nothing pending._")

    chat = get_chat()
    channel = settings.SLACK_CHANNEL_ID or "#gtm-desk"
    await chat.post_message(channel=channel, text="\n".join(lines))


async def _purge_old_data():
    """Daily: purge write_audit and resolved approvals older than RETENTION_DAYS (S5.4)."""
    from app.db import get_pool

    pool = await get_pool()
    async with pool.connection() as conn:
        # NB: %s inside a quoted INTERVAL literal is not a placeholder —
        # multiply a unit interval instead.
        await conn.execute(
            "DELETE FROM write_audit WHERE created_at < NOW() - %s * INTERVAL '1 day'",
            (settings.RETENTION_DAYS,),
        )
        await conn.execute(
            "DELETE FROM approvals WHERE status IN ('approved', 'rejected', 'expired') "
            "AND resolved_at < NOW() - %s * INTERVAL '1 day'",
            (settings.RETENTION_DAYS,),
        )
    print(f"[housekeeping] Purged data older than {settings.RETENTION_DAYS} days")


# Register jobs
scheduler.add_job(
    _expire_and_remind,
    trigger=CronTrigger(minute=0),  # Every hour at :00
    id="expire_and_remind",
    replace_existing=True,
)

scheduler.add_job(
    _daily_digest,
    trigger=CronTrigger(hour=settings.DIGEST_HOUR, minute=0, timezone=settings.DIGEST_TZ),
    id="daily_digest",
    replace_existing=True,
)

scheduler.add_job(
    _purge_old_data,
    trigger=CronTrigger(hour=3, minute=0),  # 3 AM daily
    id="purge_old_data",
    replace_existing=True,
)