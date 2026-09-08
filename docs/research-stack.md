# The research stack: evidence-grade account research

> Status: shipped in v2.0.0 (2026-09-08). Code: `app/research/`, `app/toolkits/research_tools.py`,
> `app/toolkits/_contract.py`. Tests: `tests/test_research_*.py`, `tests/test_grounding.py`,
> `tests/test_signals.py`, `tests/test_pipeline_shape.py`. Decisions: `docs/adr/`.

## The problem it solves

A research agent's failure mode is not "no answer"; it is a confident, well-formatted answer
with nothing under it. The measurement that shaped this design came from a predecessor system's
trace review on 2026-08-11: a 30-company brief in which 22 companies had no tool evidence at
all, every founder LinkedIn URL was invented, and numbers carried source labels like
"(source: Latka)" that no tool had returned. The prompt already said *never invent a source*.

Three things follow. The check has to run after generation, in code, against a record of what
the tools actually returned. Every fetch has to leave that record, misses included, or "nothing
found" and "nothing looked for" are indistinguishable. And the sources have to be cheap and
bounded enough that the researcher can afford to look before it writes.

## The shape

```
lead ──► research run (budget, ledger slice)
           │
           ├─ Tier 0  signals   Greenhouse / Lever / Ashby job boards · Google News RSS · CRM   free, parsed by code
           ├─ Tier 1  search    Serper → Firecrawl search → DuckDuckGo                          ≈ $0.001 / query
           ├─ Tier 2  scrape    ledger cache → Firecrawl → Jina Reader → direct HTTP            1 credit / page
           │          extract   Firecrawl JSON format, one page, one schema                     5 credits / page
           └─ Tier 3  browser   Stagehand v4 on Browserbase, opt-in, escalation only            ≈ $0.12 / browser-hour + model
                                                                                                    │
           evidence ledger  ◄──────────── every call, hit or miss ──────────────────────────────────┘
                 │
           grounding gate   strips any URL the ledger does not hold; moves unevidenced claims to gaps
                 │
           AccountBrief + report  ──►  qualifier ──► … ──► approval card ("7 sources verified · 2 unverified links removed")
```

| Module | Owns |
|---|---|
| `app/research/context.py` | The run a tool call belongs to (a `ContextVar`; the pipeline sets it, ad-hoc copilot research gets one per agno run). |
| `app/research/budget.py` | Per-account caps: calls, provider credits, browser seconds, dollars. Unit prices with their sources. |
| `app/research/policy.py` | Deny list (LinkedIn, social, review sites; `RESEARCH_DENY_DOMAINS` extends), browser opt-in, robots.txt on direct fetches, `tos_class` per row. |
| `app/research/evidence.py` | The ledger: `research_runs` + `evidence` tables, URL normalisation, cache reads, spend queries. |
| `app/research/providers/` | One adapter per source. Same return shape; never raise for a provider failure. |
| `app/research/router.py` | The waterfall. Records every attempt, charges the budget, escalates on evidence, never on preference. |
| `app/research/grounding.py` | The gate. Removes, moves, reports; never writes a fact. |
| `app/toolkits/_contract.py` | The envelope every tool returns, error classification, identical-failure breaker. |
| `app/toolkits/research_tools.py` | The seven tools the researcher holds, on top of all the above. |

## Tiers, providers and prices

Prices are list prices verified against vendor pages on 2026-09-08; `app/research/budget.py::UNIT_USD`
holds the numbers the budget uses and the ledger stores the price a row was charged at.

| Tier | Provider | What it is for | Unit | Price | Source |
|---|---|---|---|---|---|
| 0 | Greenhouse / Lever / Ashby | Open roles from the company's own job board: the cleanest buying signal there is | request | free, no key | public board JSON endpoints |
| 0 | Google News RSS | Recent coverage, publisher named | request | free, no key | `news.google.com/rss` |
| 0 | CRM port | Prior contact; "not cold" changes the angle | call | own data | — |
| 1 | Serper.dev | Google SERP, stable schema, prepaid | query | $1.00 → $0.30 / 1k | serper.dev pricing |
| 1 | Firecrawl search | SERP from the key most operators already hold | 10 results | 2 credits | docs.firecrawl.dev/billing |
| 1 | DuckDuckGo (`ddgs`) | keyless floor | query | free, rate-limited | — |
| 2 | Firecrawl scrape | JS rendering, proxy rotation on block, robots honoured, 48h cache (`max_age`) | page | 1 credit (≈5 when the enhanced proxy retries) | docs.firecrawl.dev/billing, /features/proxies |
| 2 | Firecrawl JSON format | One page → one schema-validated object | page | 5 credits (1 + 4) | docs.firecrawl.dev/billing |
| 2 | Jina Reader (`r.jina.ai`) | Clean markdown for most public pages, keyless | request | free tier; $0.02 / 1M tokens with a key | jina.ai/reader |
| 2 | Direct HTTP | The floor; the only tier where we are the crawler, so the only one that reads robots.txt | request | free | — |
| 3 | Browserbase + Stagehand v4 | `extract(schema)` on JavaScript shells and bot walls | browser-second | $0.12 / hour overage on the $20 Developer plan; 1 GB proxy included, $12 / GB after | browserbase.com/pricing |
| 3 | Stagehand model | The model behind `act` / `extract`; omitted = Browserbase Model Gateway billed to the session | call | ≈ $0.01 on a small model | docs.stagehand.dev |

Firecrawl plans: Free 1,000 credits / 2 concurrent; Hobby $16 / 5k; Standard $83 / 100k / 25
concurrent. Credits do not roll over. `/agent` (Firecrawl's autonomous mode) is deliberately not on
the stack: its default ceiling is 2,500 credits per call and it navigates on its own, which is the
wrong shape for a per-account budget.

Agno ships `FirecrawlTools` and `BrowserbaseTools`, and both were read before this was written.
`FirecrawlTools` pins `firecrawl-py==3.4.0` against the legacy `FirecrawlApp` class and wraps four
of the seven endpoints; `BrowserbaseTools` is navigate/screenshot/read-DOM over raw Playwright, with
no `extract`. Neither records what it returned. The adapters here call `firecrawl-py` 4.x and
`stagehand` 4.x directly and are ~60 lines each. See `docs/adr/0002-firecrawl-first-browser-last.md`.

## What one account costs

Typical pipeline run: CRM check, homepage fetch, job board, news, two or three searches, one JSON
extract. Measured against the unit prices above:

| Path | Calls | Credits | Browser | Cost |
|---|---|---|---|---|
| Keyless (DDG + Jina + Tier 0) | 8–10 | 0 | 0 | $0.00 |
| Firecrawl + Serper | 8–10 | 6–12 | 0 | $0.01–$0.02 |
| … plus a browser escalation | +1 | — | 15–60 s | +$0.01–$0.02 |
| Budget ceiling (defaults) | 25 | 40 | 180 s | $0.50 |

The default budget is ten to twenty times the typical spend on purpose: a run that hits it is a
run that went wrong, and the refusal row in the ledger says where.

## The ledger

`research_runs`: one row per researched account — budget, spend, grounding report, status.
`evidence`: one row per provider call — `tier`, `provider`, `kind` (`search` · `page` · `extract`
· `browse` · `signal` · `crm` · `enrichment`), `status` (`ok` · `empty` · `blocked` · `denied` ·
`error` · `refused`), URL (raw and normalised), query, title, content (capped at 12,000 chars),
error and class, credits, dollars, browser seconds, latency, `tos_class`, JSON `meta` (search
results, extracted fields, session ids), `fetched_at`.

Four readers: the grounding gate (`run_urls`), the router's cache (`cached_page`, 48h), the daily
digest (`spend_since`), and anyone with `psql` asking *where did this fact come from*:

```sql
SELECT tier, provider, kind, status, url, credits, cost_usd, left(error, 60)
FROM evidence WHERE run_id = 'rr-…' ORDER BY id;
```

Rows are purged with the rest of the audit data after `RETENTION_DAYS`.

## The gate

`app/research/grounding.py::ground(brief, allowed_urls, evidence_records)`:

1. `sources` keeps only URLs that normalise to a URL the ledger holds for this run (search hits
   count; a search result is a real, tool-returned URL).
2. URLs inside prose fields are treated the same way; an unverifiable one becomes
   `[unverified link removed]` and the sentence stays.
3. With zero successful evidence rows, `tech_signals`, `buying_triggers` and `key_people` move to
   `gaps` as unverified. With any evidence, unlinked claims stay: the gate can prove a URL was not
   returned; it cannot prove a sentence false.
4. Nothing is ever added. The report (`GroundingReport`) is stored on the run and rendered on the
   approval card as one line.

`tests/test_pipeline_shape.py::test_research_step_grounds_what_the_model_invents` runs the real
research step with a scripted model that fetches one page and then cites it and an invented
LinkedIn URL; the test asserts the first survives, the second is stripped, and the ledger holds both
facts.

## Policy and compliance

- **Denied by default:** `linkedin.com`, `facebook.com`, `instagram.com`, `x.com`, `twitter.com`,
  `tiktok.com`, `glassdoor.com(.au)`, `indeed.com`, `seek.com.au`. Their terms prohibit automated
  collection and LinkedIn enforces it: hiQ v. LinkedIn ended in 2022 with an injunction and
  deletion order against the scraper; Proxycurl was sued in January 2026 and shut down in July 2026
  under a permanent injunction. Denied URLs are dropped from search results before the model sees
  them and refused by every fetch tier; the refusal is a ledger row.
- **Browser tier is opt-in** (`RESEARCH_BROWSER_ENABLED=false` by default) and only ever reached
  by escalation after a cheaper tier returned a shell or was blocked. Sessions: `keep_alive=False`,
  120 s timeout, `solve_captchas=False`, `record_session=False`, tagged with the run id.
- **robots.txt** is read on direct fetches (cached per host, fail-open with a log line); Firecrawl
  honours it on its side. A `denied` row from robots stops the waterfall: the browser is never used
  to route around it.
- **Personal data.** The stack collects what a company publishes about itself. Person names appear
  only when a page prints them with a role. Under the Australian Privacy Act (as amended December
  2024, with the 2026 exposure draft broadening "personal information") every stored row carries
  its source URL, fetch time and `tos_class`, and rows expire with `RETENTION_DAYS`.

## Failure behaviour

| Condition | What happens | Where it shows |
|---|---|---|
| Provider errors | Next provider in the chain; row with `status=error` and the message | ledger; `attempts` in the tool result |
| Every provider fails | Tool returns `ok:false`, `error_class`, `do_not_retry` | model sees it, notes a gap; digest counts failed lookups |
| Same failure 3× in 120 s | Breaker: refused before the call | envelope `breaker:true` |
| Search returns nothing | `verified_empty:true` — an answer, chain stops | ledger `empty` row |
| Page is a JS shell / blocked | `empty`/`blocked` row, then browser if policy allows | `attempts` shows the escalation or the skip reason |
| Budget would be breached | Refused before the call, `refused` row, terminal envelope | ledger; run `spent` |
| Provider key missing | Tier is skipped, not attempted | `/health?probe=1` says `unconfigured` |
| Provider key dead | `/health?probe=1` says `degraded` (401/402/403/429) | probes, not memory |

## Configuration

See `.env.example` → "Research stack". Nothing is required; each key turns on one tier.
