# ADR 0002: Firecrawl first, a browser last, and our own adapters instead of agno's toolkits

Date: 2026-09-08. Status: accepted.

## Context

Account research needs four capabilities: search, page to text, page to structured fields, and a real
browser for pages that render nothing without JavaScript or sit behind a bot wall. Vendors were checked
against their own documentation and pricing pages on 2026-09-08; details are in `docs/research-stack.md`.

## Decision

- Escalation follows cost. Free Tier 0 signals and the CRM come first, then a metered search API, then a
  scrape API, then a headless browser. Escalation happens after an `empty` or `blocked` result, and the
  browser tier is off unless enabled.
- Firecrawl is the scrape API. It renders JavaScript, rotates proxies on a block, honours robots.txt,
  caches through `max_age`, and its JSON format returns schema-validated fields for 5 credits. Its
  `/agent` endpoint is excluded because of its 2,500-credit default ceiling and autonomous navigation.
- Browserbase with Stagehand v4 is the browser. Stagehand's `extract(schema)` turns a page into a
  validated object. The Python SDK talks to Browserbase's hosted service, so the container image carries
  no Chromium. Sessions are single use, capped at 120 seconds, not recorded, and tagged with the run id.
- Serper is the search API, with Firecrawl search and DuckDuckGo behind it. Jina Reader sits between
  Firecrawl and direct HTTP as the keyless option.
- The adapters are written here. agno's `FirecrawlTools` pins `firecrawl-py==3.4.0` (the legacy client,
  four endpoints, no JSON format) and `BrowserbaseTools` does navigate, screenshot and read over Playwright
  with no `extract`. Neither records what it returned, and the ledger depends on that record. Each adapter
  here is about 60 lines against the current SDK and returns one shape the router understands.

## Alternatives considered

| Option | Reason not chosen |
|---|---|
| Exa or Tavily as the primary search | Content with results is useful, but Exa is $7 per 1k against Serper's $0.30 to $1.00 per 1k, and the scrape tier already fetches content for the pages worth reading. Worth revisiting if snippet quality becomes the limit. |
| Self-hosted Crawl4AI | Free and capable, but it means running and patching a Chromium with no anti-bot layer. A poor fit for a single-process Railway app. |
| Apify actors for LinkedIn, Crunchbase, G2 | LinkedIn is denied by policy whatever the tool. The others are volatile, priced per event, and would be the only uncited data on the stack. |
| Paid enrichment (Apollo, People Data Labs, Hunter) | Contact-level data at $0.05 to $0.28 per record is a different product decision (buying personal data) from fetching what a company publishes. Left as an optional Tier 4 behind the same budget. |
| Firecrawl `/agent` | See above. |
| Self-hosted Steel or plain Playwright | A warm browser is a standing cost and a fingerprint of ours to maintain. The stack is pay-per-use throughout. |

## Consequences

- With no keys the stack still runs (Tier 0, DuckDuckGo, Jina, HTTP) at no cost.
- Each key enables one tier, and the ledger records which provider answered.
- Vendor SDKs are pinned exactly. Firecrawl releases weekly and Stagehand moved to v4 in August 2026.
