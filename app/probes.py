"""Live integration probes: health is measured, never remembered.

``/health`` answers two questions and keeps them apart (CoS LESSONS P29, P40):

- **Is the process up?** Always cheap: the app answered, the database
  answered. Railway's healthcheck reads only this.
- **Which integrations work right now?** ``/health?probe=1`` runs one real,
  read-only call per configured integration and reports one of four states
  per integration — not a boolean:

  | state          | meaning                                                  |
  |----------------|----------------------------------------------------------|
  | ``ok``         | configured and a live call succeeded                     |
  | ``degraded``   | configured, reachable, but the call was refused (auth, credit, rate limit) |
  | ``down``       | configured and unreachable or erroring                   |
  | ``unconfigured``| no credentials; the mock or the next tier serves instead |

A probe is never an agent's opinion. It is a deterministic call with a timeout,
run when asked, and the result is not cached between requests. Slack and
HubSpot probes use the cheapest authenticated read each API has.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from app.config import settings

PROBE_TIMEOUT_S = 8.0

OK, DEGRADED, DOWN, UNCONFIGURED = "ok", "degraded", "down", "unconfigured"


def _state_from_http(code: int) -> str:
    if code < 300:
        return OK
    if code in (401, 402, 403, 429):
        return DEGRADED
    return DOWN


async def _get(url: str, headers: dict[str, str] | None = None) -> tuple[str, str]:
    import httpx

    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
        resp = await client.get(url, headers=headers or {})
    return _state_from_http(resp.status_code), f"HTTP {resp.status_code}"


async def _post(
    url: str, json: dict[str, Any], headers: dict[str, str] | None = None
) -> tuple[str, str]:
    import httpx

    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
        resp = await client.post(url, json=json, headers=headers or {})
    return _state_from_http(resp.status_code), f"HTTP {resp.status_code}"


async def probe_database() -> tuple[str, str]:
    from app.db import get_pool

    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT 1")
        await cur.fetchone()
    return OK, "SELECT 1"


async def probe_firecrawl() -> tuple[str, str]:
    if not settings.FIRECRAWL_API_KEY:
        return (
            UNCONFIGURED,
            "FIRECRAWL_API_KEY unset; Jina Reader and direct fetch serve Tier 2",
        )
    return await _get(
        "https://api.firecrawl.dev/v2/team/credit-usage",
        {"Authorization": f"Bearer {settings.FIRECRAWL_API_KEY}"},
    )


async def probe_serper() -> tuple[str, str]:
    if not settings.SERPER_API_KEY:
        return (
            UNCONFIGURED,
            "SERPER_API_KEY unset; Firecrawl search or DuckDuckGo serves Tier 1",
        )
    return await _post(
        "https://google.serper.dev/search",
        {"q": "revcrew probe", "num": 1},
        {"X-API-KEY": settings.SERPER_API_KEY},
    )


async def probe_browserbase() -> tuple[str, str]:
    if not (settings.BROWSERBASE_API_KEY and settings.BROWSERBASE_PROJECT_ID):
        return UNCONFIGURED, "BROWSERBASE_API_KEY / PROJECT_ID unset; browser tier off"
    state, detail = await _get(
        f"https://api.browserbase.com/v1/projects/{settings.BROWSERBASE_PROJECT_ID}",
        {"X-BB-API-Key": settings.BROWSERBASE_API_KEY},
    )
    if state == OK and not settings.RESEARCH_BROWSER_ENABLED:
        return OK, detail + " (configured; RESEARCH_BROWSER_ENABLED=false so unused)"
    return state, detail


async def probe_slack() -> tuple[str, str]:
    if not settings.SLACK_BOT_TOKEN:
        return UNCONFIGURED, "SLACK_BOT_TOKEN unset; chat is mocked"
    import httpx

    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
        resp = await client.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
        )
    data = resp.json() if resp.status_code == 200 else {}
    if data.get("ok"):
        return OK, f"auth.test ok as {data.get('user', '?')}"
    return DEGRADED if resp.status_code == 200 else DOWN, data.get(
        "error"
    ) or f"HTTP {resp.status_code}"


async def probe_hubspot() -> tuple[str, str]:
    if not settings.HUBSPOT_PRIVATE_APP_TOKEN:
        return UNCONFIGURED, "HUBSPOT_PRIVATE_APP_TOKEN unset; CRM is mocked"
    return await _get(
        "https://api.hubapi.com/crm/v3/objects/contacts?limit=1",
        {"Authorization": f"Bearer {settings.HUBSPOT_PRIVATE_APP_TOKEN}"},
    )


async def probe_instantly() -> tuple[str, str]:
    if not settings.INSTANTLY_API_KEY:
        return UNCONFIGURED, "INSTANTLY_API_KEY unset; outreach is mocked"
    return await _get(
        "https://api.instantly.ai/api/v2/campaigns?limit=1",
        {"Authorization": f"Bearer {settings.INSTANTLY_API_KEY}"},
    )


async def probe_model() -> tuple[str, str]:
    from app.models import _resolve_provider

    provider = _resolve_provider()
    if provider == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            return UNCONFIGURED, "ANTHROPIC_API_KEY unset; agents cannot run live"
        return await _get(
            "https://api.anthropic.com/v1/models?limit=1",
            {
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
        )
    host = settings.OLLAMA_HOST or "https://ollama.com"
    headers = (
        {"Authorization": f"Bearer {settings.OLLAMA_API_KEY}"}
        if settings.OLLAMA_API_KEY
        else {}
    )
    return await _get(f"{host.rstrip('/')}/api/tags", headers)


PROBES: dict[str, Callable[[], Awaitable[tuple[str, str]]]] = {
    "database": probe_database,
    "model": probe_model,
    "slack": probe_slack,
    "hubspot": probe_hubspot,
    "instantly": probe_instantly,
    "firecrawl": probe_firecrawl,
    "serper": probe_serper,
    "browserbase": probe_browserbase,
}


async def _run(
    name: str, fn: Callable[[], Awaitable[tuple[str, str]]]
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        state, detail = await asyncio.wait_for(fn(), timeout=PROBE_TIMEOUT_S + 2)
    except asyncio.TimeoutError:
        state, detail = DOWN, f"timed out after {PROBE_TIMEOUT_S}s"
    except Exception as exc:  # noqa: BLE001 - a probe reports, it never raises
        state, detail = DOWN, f"{exc.__class__.__name__}: {str(exc)[:160]}"
    return {
        "name": name,
        "state": state,
        "detail": detail,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }


async def run_probes(names: list[str] | None = None) -> list[dict[str, Any]]:
    selected = [(n, PROBES[n]) for n in (names or list(PROBES)) if n in PROBES]
    return list(await asyncio.gather(*(_run(n, fn) for n, fn in selected)))


def worst(states: list[str]) -> str:
    order = [DOWN, DEGRADED, OK, UNCONFIGURED]
    for s in order:
        if s in states:
            return s
    return UNCONFIGURED
