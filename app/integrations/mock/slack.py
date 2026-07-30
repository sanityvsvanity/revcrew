"""Mock Slack adapter: writes to mock_messages table, renders Block Kit to console."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.db import get_pool


class MockSlack:
    """Mock chat. Messages stored in Postgres, Block Kit rendered to console."""

    async def post_message(
        self, channel: str, text: str, thread_ts: str | None = None
    ) -> dict[str, Any]:
        ts = f"mock-{uuid.uuid4().hex[:6]}"
        payload = {"channel": channel, "ts": ts, "text": text, "thread_ts": thread_ts}
        pool = await get_pool()
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO mock_messages (channel, ts, text, payload) VALUES (%s, %s, %s, %s)",
                (channel, ts, text, json.dumps(payload)),
            )
        thread_info = f" (thread: {thread_ts})" if thread_ts else ""
        print(f"\n[MOCK slack] #{channel.removeprefix('#')}{thread_info}")
        print(f"  {text[:200]}")
        return payload

    async def post_blocks(
        self, channel: str, blocks: list[dict[str, Any]], thread_ts: str | None = None
    ) -> dict[str, Any]:
        ts = f"mock-{uuid.uuid4().hex[:6]}"
        text = self._render_blocks(blocks)
        payload = {"channel": channel, "ts": ts, "blocks": blocks, "thread_ts": thread_ts}
        pool = await get_pool()
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO mock_messages (channel, ts, text, payload) VALUES (%s, %s, %s, %s)",
                (channel, ts, text, json.dumps(payload)),
            )
        thread_info = f" (thread: {thread_ts})" if thread_ts else ""
        print(f"\n[MOCK slack] #{channel.removeprefix('#')}{thread_info} [BLOCKS]")
        print(f"  {text}")
        return payload

    async def open_approval(
        self,
        channel: str,
        run_id: str,
        title: str,
        summary: str,
        thread_ts: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the progressive-disclosure card (S2.2) and post it."""
        from app.approvals import _build_approval_blocks

        if data:
            lead = data.get("lead") or {}
            draft = data.get("draft") or {}
            deal = data.get("deal") or {}
            score = data.get("score")
            blocks = _build_approval_blocks(run_id, title, lead, draft, deal, score)
        else:
            # Fallback for callers that don't pass data (backward compat)
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*\n{summary}"}},
                {"type": "actions", "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Approve"}, "value": f"{run_id}:approve", "style": "primary"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Edit"}, "value": f"{run_id}:edit"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Reject"}, "value": f"{run_id}:reject", "style": "danger"},
                ]},
            ]

        return await self.post_blocks(channel, blocks, thread_ts)

    async def open_modal(
        self, trigger_id: str, view: dict[str, Any]
    ) -> dict[str, Any]:
        """Mock modal open — renders the modal to console."""
        title = view.get("title", {}).get("text", "Modal")
        print(f"\n[MOCK slack] modal opened (trigger: {trigger_id}): {title}")
        for block in view.get("blocks", []):
            t = block.get("type", "unknown")
            if t == "input":
                label = block.get("label", {}).get("text", "?")
                print(f"  [input] {label}")
            elif t == "section":
                text_obj = block.get("text", {})
                print(f"  [section] {text_obj.get('text', '')[:100]}")
            elif t == "header":
                text_obj = block.get("text", {})
                print(f"  [header] {text_obj.get('text', '')}")
            elif t == "divider":
                print("  ---")
        return {"ok": True}

    async def update_message(
        self, channel: str, ts: str, text: str, blocks: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        print(f"[MOCK slack] updated message {ts} in #{channel.removeprefix('#')}: {text[:100]}")
        return {"channel": channel, "ts": ts, "text": text}

    def _render_blocks(self, blocks: list[dict[str, Any]]) -> str:
        """Render Block Kit to a readable console summary."""
        parts: list[str] = []
        for block in blocks:
            t = block.get("type", "unknown")
            if t == "section":
                text_obj = block.get("text", {})
                parts.append(text_obj.get("text", ""))
            elif t == "actions":
                elements = block.get("elements", [])
                labels = [e.get("text", {}).get("text", "?") for e in elements]
                parts.append(f"[Buttons: {', '.join(labels)}]")
            elif t == "header":
                text_obj = block.get("text", {})
                parts.append(f"# {text_obj.get('text', '')}")
            elif t == "divider":
                parts.append("---")
        return "\n".join(parts)