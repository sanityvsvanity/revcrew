"""Live HubSpot adapter: CRM v3 objects, Associations v4, Search API.

Dedupe before create: contacts are searched by email, companies by domain.
429s are retried with respect for Retry-After.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

API_BASE = "https://api.hubapi.com"
MAX_RETRIES = 3


def _iso_now() -> str:
    """Return the current UTC time as an ISO 8601 string (HubSpot-compatible)."""
    return datetime.now(timezone.utc).isoformat()


class LiveHubSpot:
    """HubSpot CRM adapter via private app token."""

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {settings.HUBSPOT_PRIVATE_APP_TOKEN}"}

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            for attempt in range(MAX_RETRIES + 1):
                resp = await client.request(
                    method, f"{API_BASE}{path}", headers=self._headers(), **kwargs
                )
                if resp.status_code == 429 and attempt < MAX_RETRIES:
                    wait = float(resp.headers.get("Retry-After", 2**attempt))
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                if resp.status_code == 204 or not resp.content:
                    return {}
                return resp.json()
        return {}

    async def _search_one(
        self, object_type: str, property_name: str, value: str
    ) -> dict[str, Any] | None:
        data = await self._request(
            "POST",
            f"/crm/v3/objects/{object_type}/search",
            json={
                "filterGroups": [
                    {"filters": [{"propertyName": property_name, "operator": "EQ", "value": value}]}
                ],
                "limit": 1,
            },
        )
        results = data.get("results", [])
        return results[0] if results else None

    async def upsert_contact(
        self, email: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        props = {"email": email, **{k.lower(): v for k, v in properties.items()}}
        existing = await self._search_one("contacts", "email", email)
        if existing:
            return await self._request(
                "PATCH", f"/crm/v3/objects/contacts/{existing['id']}", json={"properties": props}
            )
        return await self._request("POST", "/crm/v3/objects/contacts", json={"properties": props})

    async def upsert_company(
        self, domain: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        props = {"domain": domain, **{k.lower(): v for k, v in properties.items()}}
        existing = await self._search_one("companies", "domain", domain)
        if existing:
            return await self._request(
                "PATCH", f"/crm/v3/objects/companies/{existing['id']}", json={"properties": props}
            )
        return await self._request("POST", "/crm/v3/objects/companies", json={"properties": props})

    async def create_deal(
        self, name: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        props = {"dealname": name, **properties}
        return await self._request("POST", "/crm/v3/objects/deals", json={"properties": props})

    async def log_note(
        self, object_type: str, object_id: str, body: str
    ) -> dict[str, Any]:
        note = await self._request(
            "POST",
            "/crm/v3/objects/notes",
            json={"properties": {"hs_note_body": f"RevCrew: {body}", "hs_timestamp": _iso_now()}},
        )
        if note.get("id") and object_id:
            try:
                await self.associate("notes", note["id"], object_type, object_id)
            except httpx.HTTPStatusError:
                pass
        return note

    async def create_task(
        self, title: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        task_props: dict[str, Any] = {
            "hs_task_subject": title,
            "hs_task_body": str(properties),
            "hs_timestamp": _iso_now(),
            "hs_task_priority": "HIGH" if properties.get("urgency") == "high" else "MEDIUM",
        }
        # Optional HubSpot owner assignment (S0.4)
        owner_id = properties.get("hubspot_owner_id") or settings.HUBSPOT_DEFAULT_OWNER_ID
        if owner_id:
            task_props["hubspot_owner_id"] = owner_id
        return await self._request(
            "POST",
            "/crm/v3/objects/tasks",
            json={"properties": task_props},
        )

    async def associate(
        self, from_type: str, from_id: str, to_type: str, to_id: str
    ) -> None:
        await self._request(
            "PUT",
            f"/crm/v4/objects/{from_type}/{from_id}/associations/default/{to_type}/{to_id}",
        )

    async def search_contact(self, email: str) -> dict[str, Any] | None:
        return await self._search_one("contacts", "email", email)

    async def get_timeline(
        self, object_type: str, object_id: str
    ) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            f"/crm/v4/objects/{object_type}/{object_id}/associations/notes",
        )
        return data.get("results", [])
