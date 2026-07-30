"""Integration port protocols: abstract interfaces for CRM, outreach, and chat."""

from __future__ import annotations

from typing import Any, Protocol


class CRMPort(Protocol):
    """CRM operations: HubSpot (or mock)."""

    async def upsert_contact(
        self, email: str, properties: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def upsert_company(
        self, domain: str, properties: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def create_deal(
        self, name: str, properties: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def log_note(
        self, object_type: str, object_id: str, body: str
    ) -> dict[str, Any]: ...

    async def create_task(
        self, title: str, properties: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def associate(
        self, from_type: str, from_id: str, to_type: str, to_id: str
    ) -> None: ...

    async def search_contact(self, email: str) -> dict[str, Any] | None: ...

    async def get_timeline(
        self, object_type: str, object_id: str
    ) -> list[dict[str, Any]]: ...


class OutreachPort(Protocol):
    """Email outreach operations: Instantly (or mock)."""

    async def create_campaign(
        self, name: str, steps: list[dict[str, Any]]
    ) -> dict[str, Any]: ...

    async def add_lead(
        self, campaign_id: str, email: str, variables: dict[str, str]
    ) -> dict[str, Any]: ...

    async def activate_campaign(self, campaign_id: str) -> dict[str, Any]: ...

    async def get_campaign_stats(self, campaign_id: str) -> dict[str, Any]: ...


class ChatPort(Protocol):
    """Chat/messaging operations: Slack (or mock)."""

    async def post_message(
        self, channel: str, text: str, thread_ts: str | None = None
    ) -> dict[str, Any]: ...

    async def post_blocks(
        self, channel: str, blocks: list[dict[str, Any]], thread_ts: str | None = None
    ) -> dict[str, Any]: ...

    async def open_approval(
        self,
        channel: str,
        run_id: str,
        title: str,
        summary: str,
        thread_ts: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def open_modal(
        self, trigger_id: str, view: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def update_message(
        self, channel: str, ts: str, text: str, blocks: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]: ...
