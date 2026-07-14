"""Live Slack adapter — stub (implemented in M2)."""

from __future__ import annotations

from typing import Any


class LiveSlack:
    """Live Slack chat adapter via Bolt/SDK."""

    async def post_message(
        self, channel: str, text: str, thread_ts: str | None = None
    ) -> dict[str, Any]:
        raise NotImplementedError("Live Slack adapter — M2")

    async def post_blocks(
        self, channel: str, blocks: list[dict[str, Any]], thread_ts: str | None = None
    ) -> dict[str, Any]:
        raise NotImplementedError("Live Slack adapter — M2")

    async def open_approval(
        self,
        channel: str,
        run_id: str,
        title: str,
        summary: str,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError("Live Slack adapter — M2")

    async def update_message(
        self, channel: str, ts: str, text: str, blocks: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        raise NotImplementedError("Live Slack adapter — M2")