"""CRM toolkit — Agno tools wrapping CRMPort for agent use."""

from __future__ import annotations

from typing import Any

from agno.tools import tool

from app.integrations.registry import get_crm


@tool(name="hubspot_upsert_contact")
async def hubspot_upsert_contact(email: str, firstname: str = "", lastname: str = "", company: str = "", title: str = "") -> str:
    """Create or update a contact in HubSpot. Provide email and any known properties."""
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
    crm = get_crm()
    await crm.log_note(object_type, object_id, body)
    return f"Note logged on {object_type}/{object_id}"


@tool(name="hubspot_create_task")
async def hubspot_create_task(title: str, due_date: str = "", assigned_to: str = "") -> str:
    """Create a task in HubSpot."""
    crm = get_crm()
    props: dict[str, Any] = {}
    if due_date:
        props["hs_timestamp"] = due_date
    if assigned_to:
        props["hs_task_subject"] = assigned_to
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