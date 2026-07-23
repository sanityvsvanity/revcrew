"""Live Slack adapter: Web API via httpx."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings

API_BASE = "https://slack.com/api"


class SlackAPIError(RuntimeError):
    pass


class LiveSlack:
    """Slack chat adapter. Uses chat.postMessage and chat.update."""

    def _resolve_channel(self, channel: str) -> str:
        # Callers pass a human name like "#gtm-desk"; the API wants a channel ID.
        if channel.startswith("#") and settings.SLACK_CHANNEL_ID:
            return settings.SLACK_CHANNEL_ID
        return channel

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{API_BASE}/{method}",
                json=payload,
                headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
            )
        data = resp.json()
        if not data.get("ok"):
            raise SlackAPIError(f"{method} failed: {data.get('error', 'unknown')}")
        return data

    async def post_message(
        self, channel: str, text: str, thread_ts: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"channel": self._resolve_channel(channel), "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        return await self._call("chat.postMessage", payload)

    async def post_blocks(
        self, channel: str, blocks: list[dict[str, Any]], thread_ts: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "channel": self._resolve_channel(channel),
            "blocks": blocks,
            "text": "RevCrew update",
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts
        return await self._call("chat.postMessage", payload)

    async def open_approval(
        self,
        channel: str,
        run_id: str,
        title: str,
        summary: str,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*\n{summary}"}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Approve"}, "action_id": "approve", "value": f"{run_id}:approve", "style": "primary"},
                {"type": "button", "text": {"type": "plain_text", "text": "Edit"}, "action_id": "edit", "value": f"{run_id}:edit"},
                {"type": "button", "text": {"type": "plain_text", "text": "Reject"}, "action_id": "reject", "value": f"{run_id}:reject", "style": "danger"},
            ]},
        ]
        return await self.post_blocks(channel, blocks, thread_ts)

    async def update_message(
        self, channel: str, ts: str, text: str, blocks: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "channel": self._resolve_channel(channel),
            "ts": ts,
            "text": text,
        }
        if blocks is not None:
            payload["blocks"] = blocks
        return await self._call("chat.update", payload)
