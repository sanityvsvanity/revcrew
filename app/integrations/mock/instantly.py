"""Mock Instantly adapter — writes to mock_campaigns table, logs to console."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.db import get_pool


class MockInstantly:
    """Mock email outreach — campaigns stored in Postgres."""

    async def create_campaign(
        self, name: str, steps: list[dict[str, Any]]
    ) -> dict[str, Any]:
        campaign_id = f"mock-campaign-{uuid.uuid4().hex[:8]}"
        payload = {"id": campaign_id, "name": name, "steps": steps, "status": "paused"}
        pool = await get_pool()
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO mock_campaigns (campaign_id, name, payload) VALUES ($1, $2, $3)",
                (campaign_id, name, json.dumps(payload)),
            )
        print(f"[MOCK instantly] created campaign '{name}' ({len(steps)} steps, id={campaign_id})")
        return payload

    async def add_lead(
        self, campaign_id: str, email: str, variables: dict[str, str]
    ) -> dict[str, Any]:
        lead_id = f"mock-lead-{uuid.uuid4().hex[:8]}"
        payload = {"id": lead_id, "campaign_id": campaign_id, "email": email, "variables": variables}
        print(f"[MOCK instantly] added lead '{email}' to campaign {campaign_id}")
        return payload

    async def activate_campaign(self, campaign_id: str) -> dict[str, Any]:
        print(f"[MOCK instantly] campaign {campaign_id} activated (mock — no emails sent)")
        return {"id": campaign_id, "status": "active"}

    async def get_campaign_stats(self, campaign_id: str) -> dict[str, Any]:
        return {
            "id": campaign_id,
            "sent": 0,
            "opened": 0,
            "replied": 0,
            "bounced": 0,
        }