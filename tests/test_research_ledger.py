"""The evidence ledger and the router, against a real Postgres.

Providers are replaced with fakes that return the exact shapes the real
adapters return, so what is exercised is the waterfall, the ledger rows, the
budget, the cache and the policy — everything that is ours.
"""

import pytest

from app.config import settings
from app.research import budget as budget_mod
from app.research import evidence, router
from app.research.providers import scrape as scrape_providers
from app.research.providers import search as search_providers
from tests.conftest import requires_db, run_db_test


def _search_result(provider, status, results=None, credits=0.0, error=""):
    return {
        "provider": provider,
        "status": status,
        "results": results or [],
        "credits": credits,
        "latency_ms": 1,
        "error": error,
    }


def _scrape_result(provider, status, content="", credits=0.0, error="", meta=None):
    return {
        "provider": provider,
        "status": status,
        "content": content,
        "title": "T",
        "credits": credits,
        "latency_ms": 1,
        "error": error,
        "meta": meta or {},
    }


async def _rows(run_id):
    pool = await evidence.get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT tier, provider, kind, status, url, credits::float, cost_usd::float, error FROM evidence "
            "WHERE run_id = %s ORDER BY id",
            (run_id,),
        )
        return await cur.fetchall()


async def _truncate():
    pool = await evidence.get_pool()
    async with pool.connection() as conn:
        await conn.execute("TRUNCATE evidence, research_runs")


@requires_db
def test_search_waterfall_records_every_attempt(monkeypatch):
    async def scenario():
        await _truncate()
        monkeypatch.setattr(
            search_providers,
            "chain",
            lambda: [
                (
                    "serper",
                    lambda q, n: _fake(
                        _search_result(
                            "serper", "error", credits=1, error="Serper HTTP 500"
                        )
                    ),
                ),
                (
                    "ddg",
                    lambda q, n: _fake(
                        _search_result(
                            "ddg",
                            "ok",
                            [
                                {
                                    "title": "Acme",
                                    "url": "https://acme.example/",
                                    "snippet": "anvils",
                                },
                                {
                                    "title": "Acme on LinkedIn",
                                    "url": "https://www.linkedin.com/company/acme",
                                    "snippet": "x",
                                },
                            ],
                        )
                    ),
                ),
            ],
        )
        ctx = await evidence.start_run("acme.example")
        out = await router.search(ctx, "acme overview")
        assert out["ok"] and out["provider"] == "ddg"
        assert [r["url"] for r in out["results"]] == ["https://acme.example/"], (
            "denied domains never reach the model"
        )
        assert out["denied_results_dropped"] == 1
        rows = await _rows(ctx.run_id)
        assert [(r[1], r[3]) for r in rows] == [("serper", "error"), ("ddg", "ok")]
        assert rows[0][5] == 1.0 and rows[0][6] == pytest.approx(0.001)
        assert await evidence.run_urls(ctx.run_id) == {"https://acme.example"}
        assert ctx.calls == 2 and ctx.ok_records == 1

    run_db_test(scenario)


@requires_db
def test_verified_empty_search_stops_the_chain(monkeypatch):
    async def scenario():
        await _truncate()
        called = []
        monkeypatch.setattr(
            search_providers,
            "chain",
            lambda: [
                (
                    "serper",
                    lambda q, n: _fake(
                        _search_result("serper", "empty", credits=1), called, "serper"
                    ),
                ),
                ("ddg", lambda q, n: _fake(_search_result("ddg", "ok"), called, "ddg")),
            ],
        )
        ctx = await evidence.start_run("acme.example")
        out = await router.search(ctx, "acme series z funding")
        assert out["ok"] and out["verified_empty"] is True and out["results"] == []
        assert called == ["serper"]

    run_db_test(scenario)


@requires_db
def test_fetch_falls_through_and_escalation_is_policy_gated(monkeypatch):
    async def scenario():
        await _truncate()
        monkeypatch.setattr(
            scrape_providers,
            "chain",
            lambda: [
                (
                    "firecrawl",
                    lambda u: _fake(
                        _scrape_result(
                            "firecrawl",
                            "empty",
                            "Loading...",
                            credits=1,
                            error="page returned no readable text",
                        )
                    ),
                ),
                (
                    "jina",
                    lambda u: _fake(
                        _scrape_result("jina", "blocked", error="Jina Reader HTTP 403")
                    ),
                ),
            ],
        )
        monkeypatch.setattr(settings, "RESEARCH_BROWSER_ENABLED", False)
        ctx = await evidence.start_run("acme.example")
        out = await router.fetch(ctx, "https://app.acme.example/pricing")
        assert out["ok"] is False and out["error_class"] == "terminal"
        assert out["attempts"][-1] == {
            "provider": "browserbase",
            "status": "skipped",
            "reason": "browser tier is disabled (RESEARCH_BROWSER_ENABLED=false)",
        }
        rows = await _rows(ctx.run_id)
        assert [(r[1], r[3]) for r in rows] == [
            ("firecrawl", "empty"),
            ("jina", "blocked"),
        ]

    run_db_test(scenario)


@requires_db
def test_fetch_escalates_to_browser_when_allowed(monkeypatch):
    async def scenario():
        await _truncate()
        from app.research.providers import browser as browser_provider

        monkeypatch.setattr(
            scrape_providers,
            "chain",
            lambda: [
                (
                    "jina",
                    lambda u: _fake(
                        _scrape_result("jina", "empty", "Please enable JavaScript")
                    ),
                ),
            ],
        )
        monkeypatch.setattr(settings, "RESEARCH_BROWSER_ENABLED", True)
        monkeypatch.setattr(settings, "BROWSERBASE_API_KEY", "bb")
        monkeypatch.setattr(settings, "BROWSERBASE_PROJECT_ID", "pid")

        async def fake_extract(url, instruction, run_id, domain):
            return {
                "provider": "browserbase",
                "status": "ok",
                "content": "Plans from $99/mo. " * 20,
                "title": "Pricing",
                "credits": 0.0,
                "browser_seconds": 12.5,
                "latency_ms": 12500,
                "error": "",
                "meta": {
                    "session_id": "s1",
                    "links": ["https://acme.example/enterprise"],
                },
            }

        monkeypatch.setattr(browser_provider, "extract", fake_extract)
        ctx = await evidence.start_run("acme.example")
        out = await router.fetch(ctx, "https://acme.example/pricing")
        assert out["ok"] and out["provider"] == "browserbase" and out["next_links"]
        rows = await _rows(ctx.run_id)
        assert [(r[0], r[1], r[3]) for r in rows] == [
            (2, "jina", "empty"),
            (3, "browserbase", "ok"),
        ]
        assert ctx.browser_seconds == 12.5
        # browser seconds + one model call are priced
        assert ctx.cost_usd == pytest.approx(
            12.5 * budget_mod.UNIT_USD["browserbase"] + 0.01, rel=1e-3
        )

    run_db_test(scenario)


@requires_db
def test_denied_domain_is_refused_and_recorded():
    async def scenario():
        await _truncate()
        ctx = await evidence.start_run("acme.example")
        out = await router.fetch(ctx, "https://www.linkedin.com/company/acme")
        assert (
            out["ok"] is False
            and out["do_not_retry"] is True
            and "deny list" in out["error"]
        )
        rows = await _rows(ctx.run_id)
        assert [(r[1], r[2], r[3]) for r in rows] == [("policy", "page", "refused")]

    run_db_test(scenario)


@requires_db
def test_budget_refuses_before_calling_a_provider(monkeypatch):
    async def scenario():
        await _truncate()
        called = []
        monkeypatch.setattr(
            search_providers,
            "chain",
            lambda: [
                ("ddg", lambda q, n: _fake(_search_result("ddg", "ok"), called, "ddg"))
            ],
        )
        ctx = await evidence.start_run("acme.example")
        tight = budget_mod.Budget(
            max_calls=1, max_credits=99, max_browser_seconds=0, max_usd=1
        )
        first = await router.search(ctx, "q1", budget=tight)
        second = await router.search(ctx, "q2", budget=tight)
        assert first["ok"] is True
        assert second["ok"] is False and "1 tool calls per account" in second["error"]
        assert called == ["ddg"]
        rows = await _rows(ctx.run_id)
        assert rows[-1][1] == "budget" and rows[-1][3] == "refused"

    run_db_test(scenario)


@requires_db
def test_cache_serves_a_recent_page_without_charging(monkeypatch):
    async def scenario():
        await _truncate()
        calls = []
        monkeypatch.setattr(
            scrape_providers,
            "chain",
            lambda: [
                (
                    "jina",
                    lambda u: _fake(
                        _scrape_result("jina", "ok", "About Acme. " * 40), calls, "jina"
                    ),
                )
            ],
        )
        a = await evidence.start_run("acme.example")
        await router.fetch(a, "https://acme.example/about")
        b = await evidence.start_run("acme.example", trigger="adhoc")
        out = await router.fetch(b, "https://www.acme.example/about/?utm_source=slack")
        assert out["cached"] is True and out["provider"] == "cache:jina"
        assert calls == ["jina"], "the second fetch must not hit a provider"
        rows = await _rows(b.run_id)
        assert rows[0][1] == "cache" and rows[0][3] == "ok"
        assert await evidence.run_urls(b.run_id), (
            "a cached page still grounds the second run"
        )

        monkeypatch.setattr(settings, "RESEARCH_CACHE_TTL_HOURS", 0)
        assert await evidence.cached_page("https://acme.example/about") is None

    run_db_test(scenario)


@requires_db
def test_finish_run_persists_spend_and_grounding():
    async def scenario():
        await _truncate()
        ctx = await evidence.start_run("acme.example")
        await evidence.record(
            ctx,
            tier=1,
            provider="serper",
            kind="search",
            status="ok",
            query="q",
            credits=1,
            meta={"results": [{"url": "https://a.example/x", "title": "A"}]},
        )
        await evidence.finish_run(
            ctx, status="done", grounding={"sources_kept": 1, "clean": True}
        )
        summary = await evidence.run_summary(ctx.run_id)
        assert summary["status"] == "done" and summary["spent"]["calls"] == 1
        assert summary["grounding"]["clean"] is True
        assert summary["breakdown"] == [
            {"tier": 1, "provider": "serper", "kind": "search", "status": "ok", "n": 1}
        ]
        from datetime import datetime, timedelta, timezone

        spend = await evidence.spend_since(
            datetime.now(timezone.utc) - timedelta(minutes=5)
        )
        assert (
            spend["runs"] == 1
            and spend["calls"] == 1
            and spend["cost_usd"] == pytest.approx(0.001)
        )

    run_db_test(scenario)


async def _fake(value, sink=None, name=None):
    if sink is not None:
        sink.append(name)
    return value
