"""Live Instantly adapter: API v2 campaigns and leads.

Safety rule: activate_campaign refuses to run when ENV=dev unless forced.
Campaigns are created paused and stay paused until a human activates them.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings

API_BASE = "https://api.instantly.ai/api/v2"


class LiveInstantly:
    """Instantly outreach adapter via API v2 key."""

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {settings.INSTANTLY_API_KEY}"}

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.request(
                method, f"{API_BASE}{path}", headers=self._headers(), **kwargs
            )
            resp.raise_for_status()
            if not resp.content:
                return {}
            return resp.json()

    async def create_campaign(
        self, name: str, steps: list[dict[str, Any]]
    ) -> dict[str, Any]:
        sequence_steps = [
            {
                "type": "email",
                "delay": step.get("wait_days", 1),
                "variants": [{"subject": step["subject"], "body": step["body"]}],
            }
            for step in steps
        ]
        return await self._request(
            "POST",
            "/campaigns",
            json={
                "name": name,
                "campaign_schedule": {"schedules": []},
                "sequences": [{"steps": sequence_steps}],
            },
        )

    async def add_lead(
        self, campaign_id: str, email: str, variables: dict[str, str]
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/leads",
            json={
                "campaign": campaign_id,
                "email": email,
                "first_name": variables.get("first_name", ""),
                "custom_variables": variables,
            },
        )

    async def activate_campaign(
        self, campaign_id: str, force: bool = False
    ) -> dict[str, Any]:
        if settings.ENV == "dev" and not force:
            raise RuntimeError(
                "Refusing to activate a campaign with ENV=dev. "
                "Pass force=True only when you mean it."
            )
        return await self._request("POST", f"/campaigns/{campaign_id}/activate")

    async def get_campaign_stats(self, campaign_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", "/campaigns/analytics", params={"id": campaign_id}
        )
