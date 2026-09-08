# The research stack

Status: shipped in v2.0.0 (2026-09-08). Code lives in `app/research/`, `app/toolkits/research_tools.py`
and `app/toolkits/_contract.py`. Tests: `tests/test_research_*.py`, `tests/test_grounding.py`,
`tests/test_signals.py`, `tests/test_pipeline_shape.py`. Decision records: `docs/adr/`.

## Why it exists

The dangerous failure of a research agent is a well-formatted brief with no evidence behind it. I
saw this on an earlier internal system in August 2026: a 30-company brief where 22 companies had no
tool evidence at all, every founder LinkedIn URL was invented, and numbers carried source labels
that no tool had returned. The prompt already told the model not to invent sources.

Three design consequences follow. The check has to run after generation, in code, against a record
of what the tools returned. Every fetch has to leave a record, including misses, so that "nothing
found" and "nothing looked for" can be told apart. And the sources have to be cheap and bounded
enough that the researcher can afford to look before it writes.

## Shape

```
lead -> research run (budget, ledger slice)
          |
          |- Tier 0  signals   Greenhouse / Lever / Ashby job boards, Google News RSS, CRM     free, parsed by code
          |- Tier 1  search    Serper -> Firecrawl search -> DuckDuckGo                         about $0.001 per query
          |- Tier 2  scrape    ledger cache -> Firecrawl -> Jina Reader -> direct HTTP           1 credit per page
          |          extract   Firecrawl JSON format, one page, one schema                      5 credits per page
          |- Tier 3  browser   Stagehand v4 on Browserbase, opt-in, escalation only            about $0.12 per browser-hour plus model
          |
          evidence ledger: every call, hit or miss
          |
          grounding gate: removes URLs the ledger does not hold, moves unevidenced claims to gaps
          |
          AccountBrief + report -> qualifier -> ... -> approval card ("7 sources verified, 2 unverified links removed")
```

| Module | Responsibility |
|---|---|
| `app/research/context.py` | The run a tool call belongs to. A `ContextVar` set by the pipeline; ad-hoc copilot research gets one run per agno run. |
| `app/research/budget.py` | Per-account caps on calls, provider credits, browser seconds and dollars. Unit prices with their sources. |
| `app/research/policy.py` | Deny list (LinkedIn, social, review sites; `RESEARCH_DENY_DOMAINS` extends it), browser opt-in, robots.txt on direct fetches, `tos_class` per row. |
| `app/research/evidence.py` | The ledger: `research_runs` and `evidence` tables, URL normalisation, cache reads, spend queries. |
| `app/research/providers/` | One adapter per source. All return the same shape and none raise on a provider failure. |
| `app/research/router.py` | The waterfall. Records every attempt, charges the budget, escalates on an empty or blocked result. |
| `app/research/grounding.py` | The gate. Removes and moves; it never writes a fact. |
| `app/toolkits/_contract.py` | The envelope every tool returns, error classification, a breaker for repeated identical failures. |
| `app/toolkits/research_tools.py` | The seven tools the researcher holds. |

## Tiers, providers and prices

Prices are list prices checked against vendor pages on 2026-09-08. `app/research/budget.py::UNIT_USD`
holds the numbers the budget uses, and each ledger row stores the price it was charged at, so a later
price change does not rewrite history.

| Tier | Provider | Used for | Unit | Price | Source |
|---|---|---|---|---|---|
| 0 | Greenhouse / Lever / Ashby | Open roles from the company's own job board | request | free, no key | public board JSON endpoints |
| 0 | Google News RSS | Recent coverage with the publisher named | request | free, no key | `news.google.com/rss` |
| 0 | CRM port | Prior contact | call | own data | |
| 1 | Serper.dev | Google results, stable schema, prepaid | query | $1.00 down to $0.30 per 1k | serper.dev pricing |
| 1 | Firecrawl search | Search from the key most operators already hold | 10 results | 2 credits | docs.firecrawl.dev/billing |
| 1 | DuckDuckGo (`ddgs`) | Keyless fallback | query | free, rate-limited | |
| 2 | Firecrawl scrape | JavaScript rendering, proxy rotation on a block, robots honoured, 48h cache via `max_age` | page | 1 credit, about 5 when the enhanced proxy retries | docs.firecrawl.dev/billing and /features/proxies |
| 2 | Firecrawl JSON format | One page to one schema-validated object | page | 5 credits (1 + 4) | docs.firecrawl.dev/billing |
| 2 | Jina Reader (`r.jina.ai`) | Clean markdown for most public pages, keyless | request | free tier; $0.02 per 1M tokens with a key | jina.ai/reader |
| 2 | Direct HTTP | The fallback. The only tier where this app is the crawler, so the only one that reads robots.txt | request | free | |
| 3 | Browserbase + Stagehand v4 | `extract(schema)` on JavaScript shells and bot walls | browser-second | $0.12 per hour overage on the $20 Developer plan; 1 GB proxy included, $12 per GB after | browserbase.com/pricing |
| 3 | Stagehand model | The model behind `act` and `extract`. If unset, Browserbase's Model Gateway is used and billed to the session | call | about $0.01 on a small model | docs.stagehand.dev |

Firecrawl plans as of the check: Free 1,000 credits with 2 concurrent requests; Hobby $16 for 5k;
Standard $83 for 100k with 25 concurrent. Credits do not roll over. Firecrawl's `/agent` endpoint is
not on the stack because its default ceiling is 2,500 credits per call and it navigates on its own,
which does not fit a per-account budget.

agno ships `FirecrawlTools` and `BrowserbaseTools`. Both were read before this was written.
`FirecrawlTools` pins `firecrawl-py==3.4.0`, uses the legacy `FirecrawlApp` class and wraps four of
the endpoints. `BrowserbaseTools` does navigate, screenshot and read-DOM over Playwright and has no
`extract`. Neither records what it returned. The adapters here call `firecrawl-py` 4.x and `stagehand`
4.x directly and are about 60 lines each. See ADR 0002.

## What one account costs

A typical pipeline run does a CRM check, a homepage fetch, a job board lookup, a news lookup, two or
three searches and one JSON extract. Against the unit prices above:

| Path | Calls | Credits | Browser | Cost |
|---|---|---|---|---|
| Keyless (DuckDuckGo, Jina, Tier 0) | 8 to 10 | 0 | 0 | $0.00 |
| Firecrawl + Serper | 8 to 10 | 6 to 12 | 0 | $0.01 to $0.02 |
| Plus one browser escalation | +1 | | 15 to 60 s | +$0.01 to $0.02 |
| Budget ceiling (defaults) | 25 | 40 | 180 s | $0.50 |

The default budget is ten to twenty times typical spend. A run that reaches it has gone wrong somewhere,
and the refusal row in the ledger shows where.

## The ledger

`research_runs` holds one row per researched account: budget, spend, grounding report, status.

`evidence` holds one row per provider call: `tier`, `provider`, `kind` (`search`, `page`, `extract`,
`browse`, `signal`, `crm`, `enrichment`), `status` (`ok`, `empty`, `blocked`, `denied`, `error`,
`refused`), the URL raw and normalised, query, title, content capped at 12,000 characters, error and
error class, credits, dollars, browser seconds, latency, `tos_class`, a JSON `meta` column (search
results, extracted fields, session ids) and `fetched_at`.

Four things read it: the grounding gate (`run_urls`), the router's cache (`cached_page`, 48 hours by
default), the daily digest (`spend_since`), and anyone with `psql`:

```sql
SELECT tier, provider, kind, status, url, credits, cost_usd, left(error, 60)
FROM evidence WHERE run_id = 'rr-...' ORDER BY id;
```

Rows are purged with the rest of the audit data after `RETENTION_DAYS`.

## The gate

`app/research/grounding.py::ground(brief, allowed_urls, evidence_records)` does four things, in order:

1. `sources` keeps only URLs that normalise to a URL the ledger holds for this run. Search hits count,
   because a search result is a URL a tool returned.
2. URLs inside prose fields get the same treatment. An unverifiable one becomes
   `[unverified link removed]`; the sentence around it stays.
3. If the run has zero successful evidence rows, `tech_signals`, `buying_triggers` and `key_people`
   move into `gaps` marked unverified. If there is any evidence, unlinked claims stay, because the gate
   can prove that a URL was not returned but cannot prove that a sentence is false.
4. Nothing is added. The report (`GroundingReport`) is stored on the run and rendered on the approval
   card as one line.

`tests/test_pipeline_shape.py::test_research_step_grounds_what_the_model_invents` runs the real
research step with a scripted model that fetches one page and then cites it together with an invented
LinkedIn URL. The test asserts that the first survives, the second is stripped, and the ledger records
both.

## Policy and compliance

Denied by default: `linkedin.com`, `facebook.com`, `instagram.com`, `x.com`, `twitter.com`,
`tiktok.com`, `glassdoor.com` and `glassdoor.com.au`, `indeed.com`, `seek.com.au`. Their terms prohibit
automated collection, and LinkedIn enforces its terms: hiQ v. LinkedIn ended in 2022 with an
injunction and a deletion order against the scraper, and Proxycurl was sued in January 2026 and shut
down in July 2026 under a permanent injunction. Denied URLs are dropped from search results before the
model sees them and refused by every fetch tier. Each refusal is a ledger row.

The browser tier is off by default (`RESEARCH_BROWSER_ENABLED=false`) and is only reached by
escalation after a cheaper tier returned a shell or was blocked. Sessions use `keep_alive=False`, a
120 second timeout, `solve_captchas=False`, `record_session=False`, and carry the run id in
`user_metadata`.

robots.txt is read on direct fetches, cached per host, and treated as allow when the file cannot be
fetched (with a log line). Firecrawl honours robots on its side. A `denied` row from robots stops the
waterfall; the browser is not used to get around it.

On personal data: the stack collects what a company publishes about itself. Person names appear only
when a page prints them with a role. Every stored row carries its source URL, fetch time and
`tos_class`, and rows expire with `RETENTION_DAYS`. This is written with the Australian Privacy Act in
mind (amended December 2024; a 2026 exposure draft widens the definition of personal information).

## Verified live (2026-09-08)

All three runs used the code on this branch.

| Run | Model and providers | Result |
|---|---|---|
| `scripts/research.py canva.com --company Canva` | glm-5.2 on Ollama Cloud with the schema in the prompt; Firecrawl search and scrape; Tier 0 boards and news; mock CRM | 14 ledger rows, 11 Firecrawl credits, $0.0091, 13 sources verified, 0 removed, exit 0. The three job board guesses came back `empty`; two homepage fetches were served from Firecrawl's cache at 0 credits; four gaps recorded, including "careers page redirects to lifeatcanva.com". |
| `browser.extract("https://www.canva.com/pricing/")` | Stagehand 4.0.2 on Browserbase with the Model Gateway | `ok` in 23.3 browser-seconds; four plans with prices and audiences returned as structured facts; 11,760 prompt tokens on the gateway side. Three defects were found and fixed on the way (see LESSONS L15). |
| `firecrawl_extract("https://www.canva.com/about/", COMPANY_FACTS_SCHEMA)` | Firecrawl v2 JSON format | `ok` in 2.7 s for 5 credits. Returned `what_they_do`, one product and five named customers (Zoom, Bloomingdale's, Danone, Airbnb, Salesforce). Stack, headcount, pricing and leaders came back empty rather than guessed. |

Not exercised live: Serper (no key on the machine used; the adapter follows the documented request
and response and is covered through the router tests), Jina Reader with a key, and Lever or Ashby
against a company that uses them (the parsers are tested against fixtures in the documented shapes).

## Failure behaviour

| Condition | Behaviour | Where it shows |
|---|---|---|
| A provider errors | Next provider in the chain; a row with `status=error` and the message | ledger; `attempts` in the tool result |
| Every provider fails | The tool returns `ok:false` with an `error_class` and `do_not_retry` | the model records a gap; the digest counts failed lookups |
| The same failure three times in 120 s | The breaker refuses before the call | envelope carries `breaker:true` |
| A search returns nothing | `verified_empty:true`; the chain stops | ledger `empty` row |
| A page is a JavaScript shell or blocked | `empty` or `blocked` row, then the browser if policy allows | `attempts` shows the escalation or the reason it was skipped |
| The budget would be exceeded | Refused before the call, a `refused` row, a terminal envelope | ledger; run `spent` |
| A provider key is missing | The tier is skipped | `/health?probe=1` reports `unconfigured` |
| A provider key is dead | `/health?probe=1` reports `degraded` (401, 402, 403 or 429) | probes |

## Configuration

See `.env.example`, section "Research stack". Nothing is required; each key enables one tier.
