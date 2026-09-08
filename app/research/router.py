"""The waterfall: cheapest source first, escalation only after an empty or blocked result.

``search`` and ``fetch`` are what the toolkit calls. Each walks its provider chain, records every
attempt in the ledger (misses included), charges the budget, and stops at the first usable result.
``fetch`` escalates to the browser tier only when a cheaper tier returned a JavaScript shell or was
blocked and policy allows it. The browser is never the first call.

Every public function takes the ``RunContext`` explicitly. The toolkit resolves it from the
contextvar; tests pass one in.
"""

from __future__ import annotations

from typing import Any

from app.research import budget as budget_mod
from app.research import evidence, policy
from app.research.context import RunContext
from app.research.providers import browser as browser_provider
from app.research.providers import scrape as scrape_providers
from app.research.providers import search as search_providers
from app.research.providers import signals as signal_providers
from app.toolkits._contract import envelope


# A refusal is a ledger row too, so that "we did not look" can be told apart
# from "we looked and found nothing".
async def _refuse(
    ctx: RunContext,
    *,
    tier: int,
    provider: str,
    kind: str,
    reason: str,
    url: str = "",
    query: str = "",
) -> dict[str, Any]:
    await evidence.record(
        ctx,
        tier=tier,
        provider=provider,
        kind=kind,
        status="refused",
        url=url,
        query=query,
        error=reason,
        error_class="terminal",
    )
    return envelope(reason, "terminal", tier=tier)


def _over_budget(
    ctx: RunContext, budget: budget_mod.Budget, **costs: float
) -> str | None:
    return budget_mod.check(ctx, budget, **costs)


async def search(
    ctx: RunContext,
    query: str,
    *,
    limit: int = search_providers.MAX_RESULTS,
    budget: budget_mod.Budget | None = None,
) -> dict[str, Any]:
    budget = budget or budget_mod.Budget.from_settings()
    reason = _over_budget(ctx, budget, credits=2)
    if reason:
        return await _refuse(
            ctx, tier=1, provider="budget", kind="search", reason=reason, query=query
        )

    attempts: list[dict[str, Any]] = []
    for name, fn in search_providers.chain():
        result = await fn(query, limit)
        results = [
            r
            for r in result.get("results", [])
            if not policy.is_denied(r.get("url", ""))
        ]
        denied = len(result.get("results", [])) - len(results)
        await evidence.record(
            ctx,
            tier=1,
            provider=name,
            kind="search",
            status=result["status"],
            query=query,
            content="\n".join(
                f"{r['title']} — {r['url']}\n{r['snippet']}" for r in results
            ),
            error=result.get("error", ""),
            credits=result.get("credits", 0.0),
            latency_ms=result.get("latency_ms", 0),
            tos_class="public_api",
            meta={"results": results, "denied_results_dropped": denied},
        )
        attempts.append({"provider": name, "status": result["status"]})
        if result["status"] == "ok" and results:
            return {
                "ok": True,
                "provider": name,
                "query": query,
                "results": results,
                "denied_results_dropped": denied,
                "attempts": attempts,
            }
        if result["status"] in ("ok", "empty"):
            # A verified-empty search is an answer; do not burn the next provider on it.
            return {
                "ok": True,
                "provider": name,
                "query": query,
                "results": [],
                "verified_empty": True,
                "denied_results_dropped": denied,
                "attempts": attempts,
            }
    return envelope(
        "every search provider failed for this query; record it as a research gap",
        "transient",
        attempts=attempts,
        query=query,
    )


async def fetch(
    ctx: RunContext,
    url: str,
    *,
    budget: budget_mod.Budget | None = None,
    max_chars: int = 6000,
) -> dict[str, Any]:
    budget = budget or budget_mod.Budget.from_settings()
    if policy.is_denied(url):
        return await _refuse(
            ctx,
            tier=2,
            provider="policy",
            kind="page",
            reason=policy.deny_reason(url),
            url=url,
        )
    reason = _over_budget(
        ctx, budget, credits=scrape_providers.FIRECRAWL_SCRAPE_CREDITS
    )
    if reason:
        return await _refuse(
            ctx, tier=2, provider="budget", kind="page", reason=reason, url=url
        )

    cached = await evidence.cached_page(url)
    if cached:
        await evidence.record(
            ctx,
            tier=2,
            provider="cache",
            kind="page",
            status="ok",
            url=url,
            title=cached["title"],
            content=cached["content"],
            tos_class="cache",
            meta={
                "cached_from": cached["provider"],
                "fetched_at": cached["fetched_at"].isoformat(),
            },
        )
        return {
            "ok": True,
            "provider": f"cache:{cached['provider']}",
            "url": url,
            "title": cached["title"],
            "text": cached["content"][:max_chars],
            "cached": True,
        }

    attempts: list[dict[str, Any]] = []
    escalate = False
    for name, fn in scrape_providers.chain():
        result = await fn(url)
        await evidence.record(
            ctx,
            tier=2,
            provider=name,
            kind="page",
            status=result["status"],
            url=url,
            title=result.get("title", ""),
            content=result.get("content", ""),
            error=result.get("error", ""),
            credits=result.get("credits", 0.0),
            latency_ms=result.get("latency_ms", 0),
            meta=result.get("meta"),
        )
        attempts.append({"provider": name, "status": result["status"]})
        if result["status"] == "ok":
            return {
                "ok": True,
                "provider": name,
                "url": url,
                "title": result.get("title", ""),
                "text": result["content"][:max_chars],
                "attempts": attempts,
            }
        if result["status"] in ("empty", "blocked"):
            escalate = True
        if result["status"] == "denied":
            break  # robots said no; the browser must not be used to route around it

    if escalate:
        allowed, why = policy.browser_allowed(url)
        if allowed:
            reason = _over_budget(
                ctx, budget, browser_seconds=browser_provider.SESSION_TIMEOUT_S / 2
            )
            if reason:
                await evidence.record(
                    ctx,
                    tier=3,
                    provider="budget",
                    kind="browse",
                    status="refused",
                    url=url,
                    error=reason,
                    error_class="terminal",
                )
            else:
                result = await browser_provider.extract(
                    url,
                    "Summarise this page and list the concrete facts, people and next links on it.",
                    ctx.run_id,
                    ctx.domain,
                )
                await evidence.record(
                    ctx,
                    tier=3,
                    provider="browserbase",
                    kind="browse",
                    status=result["status"],
                    url=url,
                    title=result.get("title", ""),
                    content=result.get("content", ""),
                    error=result.get("error", ""),
                    browser_seconds=result.get("browser_seconds", 0.0),
                    latency_ms=result.get("latency_ms", 0),
                    meta=result.get("meta"),
                )
                attempts.append({"provider": "browserbase", "status": result["status"]})
                if result["status"] == "ok":
                    return {
                        "ok": True,
                        "provider": "browserbase",
                        "url": url,
                        "title": result.get("title", ""),
                        "text": result["content"][:max_chars],
                        "attempts": attempts,
                        "next_links": result.get("meta", {}).get("links", []),
                    }
        else:
            attempts.append(
                {"provider": "browserbase", "status": "skipped", "reason": why}
            )

    tried = [a for a in attempts if a.get("status") != "skipped"]
    last = tried[-1] if tried else {}
    cls = "terminal" if last.get("status") in ("denied", "blocked") else "transient"
    return envelope(
        f"could not read {url}: "
        + "; ".join(f"{a['provider']}={a['status']}" for a in attempts)
        + ". Record it as a research gap.",
        cls,
        attempts=attempts,
        url=url,
    )


async def extract(
    ctx: RunContext,
    url: str,
    schema: dict[str, Any],
    prompt: str,
    *,
    budget: budget_mod.Budget | None = None,
) -> dict[str, Any]:
    """Structured extraction from one page (Firecrawl JSON format). Firecrawl-only."""
    budget = budget or budget_mod.Budget.from_settings()
    if policy.is_denied(url):
        return await _refuse(
            ctx,
            tier=2,
            provider="policy",
            kind="extract",
            reason=policy.deny_reason(url),
            url=url,
        )
    from app.config import settings

    if not settings.FIRECRAWL_API_KEY:
        return envelope(
            "structured extraction needs FIRECRAWL_API_KEY; use fetch_page and read the text",
            "terminal",
        )
    reason = _over_budget(ctx, budget, credits=scrape_providers.FIRECRAWL_JSON_CREDITS)
    if reason:
        return await _refuse(
            ctx, tier=2, provider="budget", kind="extract", reason=reason, url=url
        )
    result = await scrape_providers.firecrawl_extract(url, schema, prompt)
    fields = (result.get("meta") or {}).get("fields") or {}
    await evidence.record(
        ctx,
        tier=2,
        provider="firecrawl",
        kind="extract",
        status=result["status"],
        url=url,
        content=str(fields)[:4000],
        error=result.get("error", ""),
        credits=result.get("credits", 0.0),
        latency_ms=result.get("latency_ms", 0),
        meta={"fields": fields},
    )
    if result["status"] == "ok":
        return {"ok": True, "provider": "firecrawl", "url": url, "fields": fields}
    return envelope(result.get("error") or "extraction returned nothing", url=url)


async def hiring_signals(
    ctx: RunContext, domain: str, company: str, careers_text: str = ""
) -> dict[str, Any]:
    """Tier 0: open roles from Greenhouse / Lever / Ashby public boards."""
    candidates = signal_providers.detect_ats(careers_text)
    if not candidates:
        for token in signal_providers.guess_tokens(domain, company):
            for ats in ("greenhouse", "lever", "ashby"):
                candidates.append((ats, token))
    checked: list[dict[str, Any]] = []
    for ats, token in candidates[:9]:
        result = await signal_providers.fetch_board(ats, token)
        jobs = result.get("jobs", [])
        await evidence.record(
            ctx,
            tier=0,
            provider=ats,
            kind="signal",
            status=result["status"],
            url=result["url"],
            query=f"{ats}:{token}",
            content="\n".join(
                f"{j['title']} — {j['location']} — {j['url']}" for j in jobs[:50]
            ),
            error=result.get("error", ""),
            latency_ms=result.get("latency_ms", 0),
            tos_class="public_api",
            meta={
                "results": [
                    {"url": j["url"], "title": j["title"]} for j in jobs if j.get("url")
                ][:50],
                "summary": signal_providers.summarize_jobs(jobs) if jobs else {},
            },
        )
        checked.append({"ats": ats, "token": token, "status": result["status"]})
        if result["status"] == "ok":
            return {
                "ok": True,
                "provider": ats,
                "board": token,
                "board_url": result["url"],
                "summary": signal_providers.summarize_jobs(jobs),
                "roles": jobs[:25],
                "checked": checked,
            }
    return {
        "ok": True,
        "verified_empty": True,
        "roles": [],
        "checked": checked,
        "note": "no public Greenhouse/Lever/Ashby board found for this company",
    }


async def news_signals(
    ctx: RunContext, company: str, region: str = "AU"
) -> dict[str, Any]:
    result = await signal_providers.google_news(company, region)
    items = [
        i for i in result.get("items", []) if not policy.is_denied(i.get("url", ""))
    ]
    await evidence.record(
        ctx,
        tier=0,
        provider="google_news",
        kind="signal",
        status=result["status"],
        url=result["url"],
        query=company,
        content="\n".join(
            f"{i['published']} {i['source']}: {i['title']} — {i['url']}" for i in items
        ),
        error=result.get("error", ""),
        latency_ms=result.get("latency_ms", 0),
        tos_class="public_api",
        meta={"results": [{"url": i["url"], "title": i["title"]} for i in items]},
    )
    if result["status"] == "error":
        return envelope(result.get("error", "news lookup failed"), "transient")
    return {
        "ok": True,
        "provider": "google_news",
        "items": items,
        "verified_empty": not items,
    }
