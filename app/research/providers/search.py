"""Tier 1 — web search. Serper (Google SERP) → Firecrawl search → DuckDuckGo.

All three return the same shape: ``results: [{title, url, snippet}]``. Serper
is first because it is the cheapest metered SERP with a stable schema (≈$0.001
per query, prepaid). Firecrawl search is second because a Firecrawl key is the
one most operators already have. DuckDuckGo is the keyless floor: best effort,
rate-limited, fine for evaluation.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.config import settings

MAX_RESULTS = 5


def _pack(
    provider: str,
    status: str,
    results: list[dict[str, str]],
    started: float,
    *,
    credits: float = 0.0,
    error: str = "",
) -> dict[str, Any]:
    return {
        "provider": provider,
        "status": status,
        "results": results,
        "credits": credits,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "error": error,
    }


async def serper(query: str, limit: int = MAX_RESULTS) -> dict[str, Any]:
    import httpx

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": settings.SERPER_API_KEY,
                    "Content-Type": "application/json",
                },
                json={"q": query, "num": limit, "gl": settings.SERPER_GL, "hl": "en"},
            )
        if resp.status_code != 200:
            return _pack(
                "serper",
                "error",
                [],
                started,
                credits=1,
                error=f"Serper HTTP {resp.status_code}: {resp.text[:160]}",
            )
        data = resp.json()
        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "snippet": r.get("snippet", "")[:300],
            }
            for r in data.get("organic", [])[:limit]
            if r.get("link")
        ]
        return _pack(
            "serper", "ok" if results else "empty", results, started, credits=1
        )
    except Exception as exc:  # noqa: BLE001
        return _pack(
            "serper", "error", [], started, credits=0, error=f"Serper failed: {exc}"
        )


async def firecrawl(query: str, limit: int = MAX_RESULTS) -> dict[str, Any]:
    from firecrawl import AsyncFirecrawl

    started = time.monotonic()
    try:
        client = AsyncFirecrawl(api_key=settings.FIRECRAWL_API_KEY, timeout=20)
        data = await client.search(query, limit=limit, sources=["web"])
        web = getattr(data, "web", None) or []
        results = [
            {
                "title": getattr(r, "title", "") or "",
                "url": getattr(r, "url", "") or "",
                "snippet": (getattr(r, "description", "") or "")[:300],
            }
            for r in web
            if getattr(r, "url", "")
        ]
        # Firecrawl bills 2 credits per 10 results (docs.firecrawl.dev/billing).
        return _pack(
            "firecrawl", "ok" if results else "empty", results, started, credits=2
        )
    except Exception as exc:  # noqa: BLE001
        return _pack(
            "firecrawl",
            "error",
            [],
            started,
            credits=0,
            error=f"Firecrawl search failed: {exc}",
        )


def _ddg_sync(query: str, limit: int) -> list[dict[str, str]]:
    from ddgs import DDGS

    with DDGS() as ddgs:
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": (r.get("body", "") or "")[:300],
            }
            for r in ddgs.text(query, max_results=limit)
            if r.get("href")
        ]


async def ddg(query: str, limit: int = MAX_RESULTS) -> dict[str, Any]:
    started = time.monotonic()
    try:
        results = await asyncio.to_thread(_ddg_sync, query, limit)
        return _pack("ddg", "ok" if results else "empty", results, started)
    except Exception as exc:  # noqa: BLE001
        return _pack("ddg", "error", [], started, error=f"DuckDuckGo failed: {exc}")


def chain() -> list[tuple[str, Any]]:
    """The configured search providers, cheapest reliable first."""
    providers: list[tuple[str, Any]] = []
    if settings.SERPER_API_KEY:
        providers.append(("serper", serper))
    if settings.FIRECRAWL_API_KEY:
        providers.append(("firecrawl", firecrawl))
    providers.append(("ddg", ddg))
    return providers
