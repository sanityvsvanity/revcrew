# ADR 0002 — Firecrawl first, a browser last, and our own adapters over agno's toolkits

Date: 2026-09-08 · Status: accepted

## Context

Account research needs four capabilities: search, page-to-text, page-to-fields, and a real browser for
pages that render nothing without JavaScript or sit behind a bot wall. Vendors were checked against
their own docs and pricing pages on 2026-09-08 (details: `docs/research-stack.md`).

## Decision

- **Order of escalation is cost order:** free Tier 0 signals and the CRM → a metered SERP → a scrape API
  → a headless browser. Escalation is triggered by evidence (an `empty`/`blocked` result), never by
  preference, and the browser is opt-in.
- **Firecrawl is the scrape API.** It renders JavaScript, rotates proxies on a block, honours robots,
  caches (`max_age`), and its JSON format gives schema-validated fields for 5 credits. Its `/agent`
  endpoint is excluded (2,500-credit default ceiling, autonomous navigation).
- **Browserbase + Stagehand v4 is the browser.** Stagehand's `extract(schema)` turns a page into a
  validated object; the Python SDK talks to Browserbase's hosted service, so the image carries no
  Chromium. Sessions are single-use, 120 s, untracked, tagged with the run id.
- **Serper is the SERP**, with Firecrawl search and DuckDuckGo behind it. Jina Reader sits between
  Firecrawl and direct HTTP as the keyless middle.
- **The adapters are ours.** agno's `FirecrawlTools` pins `firecrawl-py==3.4.0` (legacy client, four
  endpoints, no JSON format) and `BrowserbaseTools` is navigate/screenshot/read over Playwright with
  no `extract`; neither records what it returned, and the ledger is the point. Each adapter here is
  ~60 lines against the current SDK and returns one shape the router understands.

## Alternatives considered

| Option | Why not |
|---|---|
| Exa / Tavily as primary search | Content-with-results is useful, but $7 / 1k (Exa) versus $0.30–1.00 / 1k (Serper); the scrape tier already fetches content, and only for pages worth reading. Revisit if snippet quality becomes the bottleneck. |
| Crawl4AI self-hosted | Free and capable, but a Chromium we run and patch, and no anti-bot layer; wrong trade for a one-process Railway app. |
| Apify actors for LinkedIn / Crunchbase / G2 | LinkedIn is denied by policy regardless of tool. Others are volatile, pay-per-event, and would be the only un-cited data on the stack. Not on it. |
| Paid enrichment (Apollo, PDL, Hunter) | Contact-level data at $0.05–0.28 per record; a different product decision (buying personal data) than fetching what a company publishes. Left as a Tier 4 the operator can add behind the same budget. |
| Firecrawl `/agent` | See above. |
| Self-hosted Steel / plain Playwright | A warm browser is a standing cost and our fingerprint; the whole stack is pay-per-use. |

## Consequences

- With no keys the stack still works (Tier 0 + DuckDuckGo + Jina + HTTP) and costs $0.
- Every key upgrades one tier; the ledger records which provider answered.
- Vendor SDKs are pinned; both Firecrawl (weekly releases) and Stagehand (v4 in August 2026) move fast.
