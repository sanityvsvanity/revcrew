"""The evidence ledger: every research fetch is a row, hit or miss.

Two tables (``app/schema.sql``):

- ``research_runs`` — one row per researched account: the budget it ran under,
  what it spent, and the grounding report the gate produced.
- ``evidence`` — one row per provider call: tier, provider, kind, URL or query,
  the content that came back (capped), the outcome and what it cost.

Why a table and not a log line: the grounding gate reads it (a brief may only
cite URLs that appear here for its run), the approval card reads it ("7
sources, 2 unverified links removed"), the digest reads it (research spend per
day), and a reviewer can answer "where did this fact come from" with one query.
Failures are rows too — an empty search or a blocked page is evidence of
absence, and the difference between "nothing found" and "nothing looked for"
is the whole point (CoS LESSONS P26).

Content is capped at ``CONTENT_CAP`` characters per row and reused as a cache:
a page fetched successfully in the last ``RESEARCH_CACHE_TTL_HOURS`` is served
from here before any provider is charged.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.config import settings
from app.db import get_pool
from app.research import budget as budget_mod
from app.research.context import RunContext

CONTENT_CAP = 12_000

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
}


def normalize_url(url: str) -> str:
    """Canonical form used for ledger matching: scheme+host lowercased,
    tracking params dropped, fragment dropped, trailing slash trimmed."""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url.strip()
    if not p.scheme or not p.netloc:
        return url.strip().rstrip("/")
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(p.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMS
        ]
    )
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/") or ""
    return urlunparse((p.scheme.lower(), host, path, "", query, ""))


@dataclass
class Spent:
    calls: int = 0
    credits: float = 0.0
    cost_usd: float = 0.0
    browser_seconds: float = 0.0
    ok_records: int = 0

    def as_dict(self) -> dict[str, float]:
        return {
            "calls": self.calls,
            "credits": round(self.credits, 3),
            "cost_usd": round(self.cost_usd, 4),
            "browser_seconds": round(self.browser_seconds, 1),
            "ok_records": self.ok_records,
        }


async def start_run(
    domain: str, *, trigger: str = "pipeline", budget: budget_mod.Budget | None = None
) -> RunContext:
    budget = budget or budget_mod.Budget.from_settings()
    run_id = f"rr-{uuid.uuid4().hex[:12]}"
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO research_runs (run_id, domain, trigger, budget, status) "
            "VALUES (%s, %s, %s, %s, 'running')",
            (run_id, domain, trigger, json.dumps(budget.as_dict())),
        )
    return RunContext(run_id=run_id, domain=domain, trigger=trigger)


async def finish_run(
    ctx: RunContext, *, status: str = "done", grounding: dict[str, Any] | None = None
) -> None:
    pool = await get_pool()
    spent = Spent(
        ctx.calls, ctx.credits, ctx.cost_usd, ctx.browser_seconds, ctx.ok_records
    )
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE research_runs SET status = %s, spent = %s, grounding = %s, "
            "finished_at = NOW() WHERE run_id = %s",
            (
                status,
                json.dumps(spent.as_dict()),
                json.dumps(grounding or {}),
                ctx.run_id,
            ),
        )


async def record(
    ctx: RunContext,
    *,
    tier: int,
    provider: str,
    kind: str,
    status: str,
    url: str = "",
    query: str = "",
    title: str = "",
    content: str = "",
    error: str = "",
    error_class: str = "",
    credits: float = 0.0,
    browser_seconds: float = 0.0,
    latency_ms: int = 0,
    tos_class: str = "public_web",
    meta: dict[str, Any] | None = None,
) -> int:
    """Append one ledger row and charge the run. Returns the row id."""
    cost = budget_mod.price(provider, credits) if credits else 0.0
    if browser_seconds:
        cost += budget_mod.price("browserbase", browser_seconds)
    if provider == "browserbase" and status == "ok":
        cost += budget_mod.UNIT_USD["stagehand_model"]
    content = (content or "")[:CONTENT_CAP]
    content_hash = (
        hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()[:16]
        if content
        else ""
    )
    norm = normalize_url(url) if url else ""
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "INSERT INTO evidence (run_id, domain, tier, provider, kind, status, url, url_norm, "
            "query, title, content, content_hash, error, error_class, credits, cost_usd, "
            "browser_seconds, latency_ms, tos_class, meta) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "RETURNING id",
            (
                ctx.run_id,
                ctx.domain,
                tier,
                provider,
                kind,
                status,
                url,
                norm,
                query,
                title,
                content,
                content_hash,
                error,
                error_class,
                credits,
                cost,
                browser_seconds,
                latency_ms,
                tos_class,
                json.dumps(meta or {}, default=str),
            ),
        )
        row = await cur.fetchone()
    ctx.calls += 1
    ctx.credits += credits
    ctx.cost_usd += cost
    ctx.browser_seconds += browser_seconds
    if status == "ok":
        ctx.ok_records += 1
        if norm:
            ctx.urls.add(norm)
    return int(row[0]) if row else 0


async def run_urls(run_id: str) -> set[str]:
    """Every URL a successful tool call returned for this run — the grounding whitelist.

    Includes search result URLs (stored in ``meta.results``) as well as pages
    fetched, because a search hit is a real, tool-returned URL the model may cite.
    """
    pool = await get_pool()
    urls: set[str] = set()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT url_norm, meta FROM evidence WHERE run_id = %s AND status = 'ok'",
            (run_id,),
        )
        for url_norm, meta in await cur.fetchall():
            if url_norm:
                urls.add(url_norm)
            meta = meta if isinstance(meta, dict) else json.loads(meta or "{}")
            for r in meta.get("results", []) or []:
                if isinstance(r, dict) and r.get("url"):
                    urls.add(normalize_url(r["url"]))
    return urls


async def cached_page(url: str) -> dict[str, Any] | None:
    """A successful fetch of this URL inside the cache TTL, from any run."""
    ttl = settings.RESEARCH_CACHE_TTL_HOURS
    if ttl <= 0:
        return None
    since = datetime.now(timezone.utc) - timedelta(hours=ttl)
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT provider, title, content, fetched_at FROM evidence "
            "WHERE url_norm = %s AND status = 'ok' AND kind IN ('page', 'browse') "
            "AND content <> '' AND fetched_at >= %s ORDER BY fetched_at DESC LIMIT 1",
            (normalize_url(url), since),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "provider": row[0],
        "title": row[1],
        "content": row[2],
        "fetched_at": row[3],
    }


async def run_summary(run_id: str) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT domain, status, budget, spent, grounding, started_at, finished_at "
            "FROM research_runs WHERE run_id = %s",
            (run_id,),
        )
        row = await cur.fetchone()
        if not row:
            return {}
        cur = await conn.execute(
            "SELECT tier, provider, kind, status, COUNT(*) FROM evidence WHERE run_id = %s "
            "GROUP BY tier, provider, kind, status ORDER BY tier",
            (run_id,),
        )
        breakdown = [
            {"tier": t, "provider": p, "kind": k, "status": s, "n": n}
            for t, p, k, s, n in await cur.fetchall()
        ]
    return {
        "run_id": run_id,
        "domain": row[0],
        "status": row[1],
        "budget": row[2],
        "spent": row[3],
        "grounding": row[4],
        "started_at": row[5],
        "finished_at": row[6],
        "breakdown": breakdown,
    }


async def spend_since(since: datetime) -> dict[str, Any]:
    """Research spend for the digest: runs, calls, credits, dollars, browser seconds."""
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT COUNT(DISTINCT run_id), COUNT(*), COALESCE(SUM(credits),0), "
            "COALESCE(SUM(cost_usd),0), COALESCE(SUM(browser_seconds),0), "
            "COALESCE(SUM(CASE WHEN status <> 'ok' THEN 1 ELSE 0 END),0) "
            "FROM evidence WHERE fetched_at >= %s",
            (since,),
        )
        runs, calls, credits, usd, secs, failures = await cur.fetchone()
    return {
        "runs": runs,
        "calls": calls,
        "credits": float(credits),
        "cost_usd": float(usd),
        "browser_seconds": float(secs),
        "failures": failures,
    }
