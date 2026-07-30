"""CRM toolkit: Agno tools wrapping CRMPort for agent use.

S3.3: Activity summary tool for "what did you do this week?"
S4.8: Read-back fencing on CRM free-text fields.
S4.9: Tool-layer validation for fast model self-correction.
"""

from __future__ import annotations

from typing import Any

from agno.tools import tool

from app.integrations.registry import get_crm


# ---------------------------------------------------------------------------
# Read-back fencing helper (S4.8)
# ---------------------------------------------------------------------------

def _fence_crm_data(text: str, source: str = "prospect_correspondence") -> str:
    """Wrap free-text CRM data in a data fence so the copilot treats it as untrusted."""
    return f'<crm_data source="{source}">\n{text}\n</crm_data>'


# ---------------------------------------------------------------------------
# Validation helpers (S4.9)
# ---------------------------------------------------------------------------

def _validate_email(email: str) -> str | None:
    """Return an error message if the email looks invalid, else None."""
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return f"Invalid email: '{email}'. Provide a valid email address."
    return None


def _validate_note_body(body: str) -> str | None:
    """Return an error message if the note body is too long, else None."""
    if len(body) > 4000:
        return f"Note body is {len(body)} chars (max 4000). Shorten it."
    return None


# ---------------------------------------------------------------------------
# CRM write tools
# ---------------------------------------------------------------------------


@tool(name="hubspot_upsert_contact")
async def hubspot_upsert_contact(
    email: str, firstname: str = "", lastname: str = "", company: str = "", title: str = ""
) -> str:
    """Create or update a contact in HubSpot. Provide email and any known properties."""
    err = _validate_email(email)
    if err:
        return err
    crm = get_crm()
    props: dict[str, Any] = {}
    if firstname:
        props["firstname"] = firstname
    if lastname:
        props["lastname"] = lastname
    if company:
        props["company"] = company
    if title:
        props["jobtitle"] = title
    result = await crm.upsert_contact(email, props)
    return f"Contact upserted: {result.get('id', 'unknown')}"


@tool(name="hubspot_upsert_company")
async def hubspot_upsert_company(domain: str, name: str = "", industry: str = "", size: str = "") -> str:
    """Create or update a company in HubSpot. Provide domain and any known properties."""
    crm = get_crm()
    props: dict[str, Any] = {}
    if name:
        props["name"] = name
    if industry:
        props["industry"] = industry
    if size:
        props["numberofemployees"] = size
    result = await crm.upsert_company(domain, props)
    return f"Company upserted: {result.get('id', 'unknown')}"


@tool(name="hubspot_create_deal")
async def hubspot_create_deal(name: str, amount: str = "", stage: str = "qualified") -> str:
    """Create a deal in HubSpot."""
    crm = get_crm()
    props: dict[str, Any] = {"dealstage": stage}
    if amount:
        props["amount"] = amount
    result = await crm.create_deal(name, props)
    return f"Deal created: {result.get('id', 'unknown')}"


@tool(name="hubspot_log_note")
async def hubspot_log_note(object_type: str, object_id: str, body: str) -> str:
    """Log a note on a HubSpot object (contact, company, or deal)."""
    err = _validate_note_body(body)
    if err:
        return err
    crm = get_crm()
    await crm.log_note(object_type, object_id, body)
    return f"Note logged on {object_type}/{object_id}"


@tool(name="hubspot_create_task")
async def hubspot_create_task(title: str, due_date: str = "", assigned_to: str = "") -> str:
    """Create a task in HubSpot. Use assigned_to for the HubSpot owner ID."""
    crm = get_crm()
    props: dict[str, Any] = {}
    if due_date:
        props["hs_timestamp"] = due_date
    if assigned_to:
        props["hubspot_owner_id"] = assigned_to
    result = await crm.create_task(title, props)
    return f"Task created: {result.get('id', 'unknown')}"


@tool(name="hubspot_search_contact")
async def hubspot_search_contact(email: str) -> str:
    """Search for a contact in HubSpot by email. Returns contact info or 'not found'."""
    crm = get_crm()
    result = await crm.search_contact(email)
    if result:
        return f"Found: {result.get('email', email)} (id={result.get('id', 'unknown')})"
    return f"No contact found for {email}"


# ---------------------------------------------------------------------------
# Activity summary tool (S3.3)
# ---------------------------------------------------------------------------


@tool(name="revcrew_activity_summary")
async def revcrew_activity_summary(days: int = 7) -> str:
    """Get RevCrew activity summary: approvals, CRM writes, and events for the last N days.

    Use this to answer "what did you do this week?" or similar questions.
    Returns aggregate counts and recent activity rows (no raw payloads).
    """
    from app.db import get_pool

    pool = await get_pool()
    async with pool.connection() as conn:
        # NB: %s inside a quoted INTERVAL literal is not a placeholder —
        # multiply a unit interval instead.
        # Approval counts
        cur = await conn.execute(
            "SELECT status, COUNT(*) FROM approvals "
            "WHERE created_at >= NOW() - %s * INTERVAL '1 day' "
            "GROUP BY status",
            (days,),
        )
        approval_counts = {row[0]: row[1] for row in await cur.fetchall()}

        # CRM write counts
        cur = await conn.execute(
            "SELECT decision, object_type, COUNT(*) FROM write_audit "
            "WHERE created_at >= NOW() - %s * INTERVAL '1 day' "
            "GROUP BY decision, object_type",
            (days,),
        )
        write_rows = await cur.fetchall()

        # Recent writes (last 10, summary only)
        cur = await conn.execute(
            "SELECT context_id, operation, object_type, decision, payload_summary, created_at "
            "FROM write_audit "
            "WHERE created_at >= NOW() - %s * INTERVAL '1 day' "
            "ORDER BY created_at DESC LIMIT 10",
            (days,),
        )
        recent_writes = [
            {
                "context": row[0],
                "operation": row[1],
                "object": row[2],
                "decision": row[3],
                "summary": row[4],
                "at": row[5].isoformat() if row[5] else "",
            }
            for row in await cur.fetchall()
        ]

    # Build summary
    lines = [f"*RevCrew activity — last {days} day(s)*", ""]

    lines.append("*Approvals:*")
    for status, count in sorted(approval_counts.items()):
        lines.append(f"  {status}: {count}")
    if not approval_counts:
        lines.append("  none")

    lines.append("")
    lines.append("*CRM writes:*")
    for decision, obj_type, count in write_rows:
        lines.append(f"  {decision} {obj_type}: {count}")
    if not write_rows:
        lines.append("  none")

    if recent_writes:
        lines.append("")
        lines.append("*Recent activity:*")
        for w in recent_writes:
            lines.append(
                f"  {w['decision']} {w['operation']} {w['object']} "
                f"({w['context']}) at {w['at'][:19]}"
            )

    return "\n".join(lines)