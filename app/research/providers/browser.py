"""Tier 3 — browser hands: Stagehand v4 on a Browserbase session.

The most capable and most expensive tier, so it is the last resort and it is
bounded on every axis: one session per call, a hard session timeout, no
``keep_alive``, no recording, ``user_metadata`` tagging each session with the
research run so the Browserbase dashboard and our ledger agree on what was
spent. The stack never types credentials, never solves CAPTCHAs on purpose
(``solve_captchas=False``) and never opens a denied domain (policy.py).

Why Stagehand rather than raw Playwright: ``extract`` takes a schema and returns
a validated object, so a careers page or a pricing page becomes fields, not a
40 KB text blob the model has to read. The Python SDK (``stagehand`` 4.x) talks
to Browserbase's hosted service — no Node binary in the image. Omitting
``STAGEHAND_MODEL`` uses Browserbase's Model Gateway, billed to the session.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from app.config import settings

SESSION_TIMEOUT_S = 120


class PageFacts(BaseModel):
    """What the browser tier is asked to pull from a page, whatever the page."""

    title: str = Field(default="", description="Page title")
    summary: str = Field(
        default="", description="2-3 sentence summary of what the page says"
    )
    facts: list[str] = Field(
        default_factory=list,
        description="Concrete facts stated on the page: numbers, names, dates, products",
    )
    people: list[str] = Field(
        default_factory=list, description="People named with their role, if any"
    )
    links: list[str] = Field(
        default_factory=list, description="Absolute URLs of pages worth reading next"
    )


def _model_kwargs() -> dict[str, Any]:
    model = settings.STAGEHAND_MODEL.strip()
    if not model:
        return {}
    key = settings.STAGEHAND_MODEL_API_KEY or (
        settings.ANTHROPIC_API_KEY if model.startswith("anthropic/") else ""
    )
    return {"model": model, "model_api_key": key or None}


async def extract(
    url: str, instruction: str, run_id: str, domain: str
) -> dict[str, Any]:
    """Open ``url`` in a fresh Browserbase session and extract ``PageFacts``."""
    started = time.monotonic()
    browser = None
    stagehand = None
    try:
        from stagehand import Stagehand, browserbase

        browser = await browserbase.launch(
            api_key=settings.BROWSERBASE_API_KEY,
            keep_alive=False,
            timeout=SESSION_TIMEOUT_S,
            browser_settings={
                "solve_captchas": False,
                "record_session": False,
                "block_ads": True,
            },
            user_metadata={"app": "revcrew", "research_run": run_id, "domain": domain},
        )
        stagehand = await Stagehand.create(browser=browser, **_model_kwargs())
        page = await stagehand.context.new_page(url)
        await page.wait_for_load_state("domcontentloaded", timeout=30_000)
        result = await stagehand.extract(instruction, PageFacts, page=page, timeout=60)
        data = getattr(result, "data", None) or result
        facts = (
            data
            if isinstance(data, PageFacts)
            else PageFacts.model_validate(
                data.model_dump() if hasattr(data, "model_dump") else dict(data)
            )
        )
        seconds = time.monotonic() - started
        content_lines = [
            facts.summary,
            *facts.facts,
            *[f"Person: {p}" for p in facts.people],
        ]
        content = "\n".join(line for line in content_lines if line)
        return {
            "provider": "browserbase",
            "status": "ok" if content else "empty",
            "content": content,
            "title": facts.title,
            "credits": 0.0,
            "browser_seconds": round(seconds, 1),
            "latency_ms": int(seconds * 1000),
            "error": "" if content else "browser extraction returned no facts",
            "meta": {
                "session_id": getattr(browser, "session_id", None),
                "links": facts.links[:10],
                "model": settings.STAGEHAND_MODEL or "browserbase-gateway",
            },
        }
    except Exception as exc:  # noqa: BLE001
        seconds = time.monotonic() - started
        msg = str(exc)
        status = (
            "blocked"
            if any(k in msg.lower() for k in ("402", "payment", "quota"))
            else "error"
        )
        return {
            "provider": "browserbase",
            "status": status,
            "content": "",
            "title": "",
            "credits": 0.0,
            "browser_seconds": round(seconds, 1),
            "latency_ms": int(seconds * 1000),
            "error": f"browser tier failed: {msg[:200]}",
            "meta": {"session_id": getattr(browser, "session_id", None)},
        }
    finally:
        for closer in (stagehand, browser):
            if closer is not None:
                try:
                    await closer.close()
                except Exception:  # noqa: BLE001 - cleanup must not mask the result
                    pass
