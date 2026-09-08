"""Tier 2 — turn a URL into readable text. Firecrawl → Jina Reader → direct HTTP.

Firecrawl (``firecrawl-py`` 4.x, v2 API) is first when its key is set: it
renders JavaScript, rotates proxies on a block, honours robots.txt and caches
(``max_age``: a page it fetched in the last 48h costs nothing new). Jina Reader
(``r.jina.ai``) is the keyless middle: clean markdown for most public pages.
The direct ``httpx`` fetch is the floor, and the only tier where *we* are the
crawler, so it is the one that checks robots.txt itself.

``extract`` is Firecrawl's JSON format: one page, one schema, 5 credits. It is
the deterministic cousin of Firecrawl's ``/agent`` endpoint, which is not used
here on purpose — its default ceiling is 2,500 credits per call and it navigates
on its own, which is the wrong shape for a per-account budget.
"""

from __future__ import annotations

import re
import time
from typing import Any

from app.config import settings
from app.research.policy import USER_AGENT, robots_allows

# Firecrawl documents "1 credit per page, ~5 when the enhanced proxy retries".
FIRECRAWL_SCRAPE_CREDITS = 1
FIRECRAWL_JSON_CREDITS = 5

_SHELL_HINTS = (
    "enable javascript",
    "javascript is required",
    "please enable js",
    "you need to enable javascript",
    "loading...",
    "checking your browser",
    "verify you are human",
    "access denied",
    "attention required",
)


def strip_html(html: str) -> str:
    """Reduce an HTML page to readable text."""
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)</?(p|br|div|li|h[1-6]|tr)[^>]*>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def looks_like_shell(text: str) -> bool:
    """A JavaScript shell or a bot wall: too little text, or a tell-tale phrase."""
    t = (text or "").strip()
    if len(t) < 200:
        return True
    low = t[:1500].lower()
    return any(h in low for h in _SHELL_HINTS)


def _pack(
    provider: str,
    status: str,
    started: float,
    *,
    content: str = "",
    title: str = "",
    credits: float = 0.0,
    error: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "status": status,
        "content": content,
        "title": title,
        "credits": credits,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "error": error,
        "meta": meta or {},
    }


def _status_from_code(code: int | None) -> str:
    if code in (401, 403, 429) or code == 999:
        return "blocked"
    return "error"


async def firecrawl(url: str) -> dict[str, Any]:
    from firecrawl import AsyncFirecrawl

    started = time.monotonic()
    try:
        client = AsyncFirecrawl(api_key=settings.FIRECRAWL_API_KEY, timeout=45)
        doc = await client.scrape(
            url,
            formats=["markdown"],
            only_main_content=True,
            max_age=settings.RESEARCH_CACHE_TTL_HOURS * 3600 * 1000,
        )
        md = getattr(doc, "markdown", "") or ""
        metadata = getattr(doc, "metadata", None)
        code = getattr(metadata, "status_code", None) if metadata else None
        title = (getattr(metadata, "title", "") or "") if metadata else ""
        meta = {
            "status_code": code,
            "proxy_used": getattr(metadata, "proxy_used", None) if metadata else None,
            "cache_state": getattr(metadata, "cache_state", None) if metadata else None,
        }
        credits = FIRECRAWL_SCRAPE_CREDITS if meta["cache_state"] != "hit" else 0
        if code and code >= 400:
            return _pack(
                "firecrawl",
                _status_from_code(code),
                started,
                credits=credits,
                error=f"Firecrawl fetched HTTP {code}",
                meta=meta,
            )
        if looks_like_shell(md):
            return _pack(
                "firecrawl",
                "empty",
                started,
                content=md,
                title=title,
                credits=credits,
                error="page returned no readable text",
                meta=meta,
            )
        return _pack(
            "firecrawl",
            "ok",
            started,
            content=md,
            title=title,
            credits=credits,
            meta=meta,
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        status = (
            "blocked"
            if any(k in msg.lower() for k in ("403", "blocked", "captcha"))
            else "error"
        )
        return _pack(
            "firecrawl", status, started, error=f"Firecrawl scrape failed: {msg[:200]}"
        )


async def firecrawl_extract(
    url: str, schema: dict[str, Any], prompt: str
) -> dict[str, Any]:
    """One page → one JSON object matching ``schema`` (Firecrawl JSON format)."""
    from firecrawl import AsyncFirecrawl

    started = time.monotonic()
    try:
        client = AsyncFirecrawl(api_key=settings.FIRECRAWL_API_KEY, timeout=60)
        doc = await client.scrape(
            url,
            formats=[{"type": "json", "schema": schema, "prompt": prompt}],
            only_main_content=True,
            max_age=settings.RESEARCH_CACHE_TTL_HOURS * 3600 * 1000,
        )
        data = getattr(doc, "json", None)
        if not data:
            return _pack(
                "firecrawl",
                "empty",
                started,
                credits=FIRECRAWL_JSON_CREDITS,
                error="extraction returned no fields",
            )
        return _pack(
            "firecrawl",
            "ok",
            started,
            credits=FIRECRAWL_JSON_CREDITS,
            meta={"fields": data},
        )
    except Exception as exc:  # noqa: BLE001
        return _pack(
            "firecrawl",
            "error",
            started,
            error=f"Firecrawl extract failed: {str(exc)[:200]}",
        )


async def jina(url: str) -> dict[str, Any]:
    import httpx

    started = time.monotonic()
    headers = {
        "Accept": "text/plain",
        "User-Agent": USER_AGENT,
        "X-Return-Format": "markdown",
    }
    if settings.JINA_API_KEY:
        headers["Authorization"] = f"Bearer {settings.JINA_API_KEY}"
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(f"https://r.jina.ai/{url}", headers=headers)
        if resp.status_code != 200:
            return _pack(
                "jina",
                _status_from_code(resp.status_code),
                started,
                error=f"Jina Reader HTTP {resp.status_code}: {resp.text[:120]}",
            )
        text = resp.text
        title = ""
        m = re.match(r"Title:\s*(.+)", text)
        if m:
            title = m.group(1).strip()
        if looks_like_shell(text):
            return _pack(
                "jina",
                "empty",
                started,
                content=text,
                title=title,
                error="page returned no readable text",
            )
        return _pack("jina", "ok", started, content=text, title=title)
    except Exception as exc:  # noqa: BLE001
        return _pack("jina", "error", started, error=f"Jina Reader failed: {exc}")


async def basic(url: str) -> dict[str, Any]:
    import httpx

    started = time.monotonic()
    if not await robots_allows(url):
        return _pack(
            "basic",
            "denied",
            started,
            error="robots.txt disallows this path for crawlers",
        )
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=15, headers={"User-Agent": USER_AGENT}
        ) as client:
            resp = await client.get(url)
        if resp.status_code >= 400:
            return _pack(
                "basic",
                _status_from_code(resp.status_code),
                started,
                error=f"HTTP {resp.status_code}",
            )
        text = strip_html(resp.text)
        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", resp.text)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        if looks_like_shell(text):
            return _pack(
                "basic",
                "empty",
                started,
                content=text,
                title=title,
                error="page returned no readable text (JavaScript shell?)",
            )
        return _pack("basic", "ok", started, content=text, title=title)
    except Exception as exc:  # noqa: BLE001
        return _pack("basic", "error", started, error=f"fetch failed: {exc}")


def chain() -> list[tuple[str, Any]]:
    """Configured scrape providers, best first. ``RESEARCH_PROVIDER`` pins a tier."""
    pinned = settings.RESEARCH_PROVIDER.lower()
    if pinned == "basic":
        return [("jina", jina), ("basic", basic)]
    providers: list[tuple[str, Any]] = []
    if settings.FIRECRAWL_API_KEY:
        providers.append(("firecrawl", firecrawl))
    providers += [("jina", jina), ("basic", basic)]
    return providers
