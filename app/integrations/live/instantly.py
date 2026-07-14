"""Live Instantly adapter — stub (implemented in M3)."""

from __future__ import annotations

from typing import Any


class LiveInstantly:
    """Live Instantly email outreach adapter via API v2."""

    async def create_campaign(
        self, name: str, steps: list[dict[str, Any]]
    ) -> dict[str, Any]:
        raise NotImplementedError("Live Instantly adapter — M3")

    async def add_lead(
        self, campaign_id: str, email: str, variables: dict[str, str]
    ) -> dict[str, Any]:
        raise NotImplementedError("Live Instantly adapter — M3")

    async def activate_campaign(self, campaign_id: str) -> dict[str, Any]:
        raise NotImplementedError("Live Instantly adapter — M3")

    async def get_campaign_stats(self, campaign_id: str) -> dict[str, Any]:
        raise NotImplementedError("Live Instantly adapter — M3")