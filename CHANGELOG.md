# Changelog

## Unreleased

- Google News RSS returns redirect URLs (`news.google.com/rss/articles/...`). Resolve them to the
  publisher URL before they reach the ledger so citations read well on a card.
- Serper and the Lever and Ashby paths are covered by fixtures only. Run them once with real keys and a
  company that uses them, then record the result in `docs/research-stack.md`.
- Adopt agno `HumanReview` on the approval step when a second chat surface arrives (ADR 0001).
- Run `ruff format` over the whole repository in one commit. CI checks formatting only on the v2 modules.

## 2.0.0, 2026-09-08

The researcher now runs on a tiered, budgeted, recorded research stack, and a grounding gate keeps a
brief to what a tool actually returned. Design: `docs/research-stack.md`. Decisions: `docs/adr/`.

### Added
- `app/research/`: run context, per-account budget, domain policy (deny list, browser opt-in,
  robots.txt), evidence ledger (`research_runs` and `evidence` tables), providers (Greenhouse, Lever and
  Ashby job boards, Google News RSS, Serper, Firecrawl v2 search, scrape and JSON format, Jina Reader,
  direct HTTP, Stagehand v4 on Browserbase), the waterfall router, and the grounding gate.
- `app/toolkits/_contract.py`: every tool returns an envelope with an error class and a retry flag, and
  repeated identical failures trip a breaker.
- Seven research tools on one `ResearchTools` toolkit. Researcher prompt v2.0.0.
- `app/probes.py` and `/health?probe=1`: live, four-state integration probes.
- An evidence line on the approval card and research spend in the daily digest.
- `evals/`: a regression suite on `agno.eval` with a code `GroundingScorer`, run by `scripts/evals.py`.
- `scripts/research.py`: run the research step for one domain from a shell.
- GitHub Actions CI: lint, the test suite against Postgres, the zero-key demo end to end, and a boot check.
- `Dockerfile`, `railway.toml`, `SECURITY.md`, `docs/FAILURE_MODES.md`, `docs/LESSONS.md`, three ADRs.
- agno's OpenTelemetry tracing into Postgres behind `TRACING_ENABLED`.
- A `TIMEZONE` setting. Every pipeline agent receives the date labelled with its weekday.

### Changed
- agno 2.5.17 to 3.0.7. Workflow executors read `StepInput.previous_step_outputs`, and `Workflow` is
  keyword-only.
- `lead_pipeline` ends at the approval gate. The `push_and_log` step that ran right after opening the
  gate is removed. The only push path is a human Approve (ADR 0001).
- Pipeline agents carry no history and no memory.
- Ollama Cloud models are built with native structured outputs off, so the schema goes in the prompt.
- `app/db.get_pool` is event-loop aware.
- `DIGEST_TZ` defaults to `TIMEZONE`, which defaults to UTC (was `America/Chicago`).
- `python-multipart` is pinned; AgentOS form routes need it.

### Removed
- `RESEARCH_PROVIDER` as the only research knob. It remains as the pin for the scrape tier.

## 1.x, July to August 2026

Approval experience, guarded CRM writes, event outbox, model factory, ICP rubric, copilot skills, and the
first evidence-based researcher. See the git history.
