"""Live HubSpot adapter — stub (implemented in M3)."""

from __future__ import annotations

from typing import Any


class LiveHubSpot:
    """Live HubSpot CRM adapter via API v3."""

    async def upsert_contact(
        self, email: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError("Live HubSpot adapter — M3")

    async def upsert_company(
        self, domain: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError("Live HubSpot adapter — M3")

    async def create_deal(
        self, name: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError("Live HubSpot adapter — M3")

    async def log_note(
        self, object_type: str, object_id: str, body: str
    ) -> dict[str, Any]:
        raise NotImplementedError("Live HubSpot adapter — M3")

    async def create_task(
        self, title: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError("Live HubSpot adapter — M3")

    async def associate(
        self, from_type: str, from_id: str, to_type: str, to_id: str
    ) -> None:
        raise NotImplementedError("Live HubSpot adapter — M3")

    async def search_contact(self, email: str) -> dict[str, Any] | None:
        raise NotImplementedError("Live HubSpot adapter — M3")

    async def get_timeline(
        self, object_type: str, object_id: str
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("Live HubSpot adapter — M3")