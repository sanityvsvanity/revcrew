# Changelog

## 2.0.0 — 2026-09-08 — evidence-grade research

Headline: the researcher now runs on a tiered, budgeted, ledgered research stack, and a grounding
gate guarantees a brief only cites what a tool actually returned. Design: `docs/research-stack.md`;
decisions: `docs/adr/`.

### Added
- `app/research/`: run context, per-account budget, domain policy (deny list, browser opt-in,
  robots.txt), evidence ledger (`research_runs`, `evidence` tables), tiered providers
  (Greenhouse/Lever/Ashby job boards, Google News RSS, Serper, Firecrawl v2 search/scrape/JSON,
  Jina Reader, direct HTTP, Stagehand v4 on Browserbase), the waterfall router, the grounding gate.
- `app/toolkits/_contract.py`: every tool returns a truthful envelope with an error class and a
  retry flag; identical failures trip a breaker.
- Seven research tools on one `ResearchTools` toolkit; researcher prompt v2.0.0.
- `app/probes.py` and `/health?probe=1`: live, four-state integration probes.
- Evidence line on the approval card; research spend in the daily digest.
- `evals/` regression suite on `agno.eval` with a code `GroundingScorer`; `scripts/evals.py`.
- GitHub Actions CI: lint, tests against Postgres, the zero-key demo golden path, a boot check.
- `Dockerfile`, `railway.toml`, `SECURITY.md`, `docs/FAILURE_MODES.md`, `docs/LESSONS.md`, three ADRs.
- agno's OpenTelemetry tracing into Postgres behind `TRACING_ENABLED`.
- `TIMEZONE` setting; every pipeline agent receives the date labelled with its weekday.

### Changed
- **agno 2.5.17 → 3.0.7.** Workflow executors read `StepInput.previous_step_outputs`; `Workflow` is keyword-only.
- `lead_pipeline` ends at the approval gate. The `push_and_log` step that ran right after opening
  the gate is gone; the only push path is a human Approve (ADR 0001).
- Pipeline agents carry no history and no memory.
- Ollama Cloud models are built with native structured outputs off (schema goes in the prompt).
- `app/db.get_pool` is event-loop-aware.
- `DIGEST_TZ` defaults to `TIMEZONE` (was `America/Chicago`).

### Removed
- The single-provider `RESEARCH_PROVIDER` tiering as the only knob (kept as the scrape-tier pin).

## 1.x — 2026-07 → 2026-08

Approval experience, guarded CRM writes, event outbox, model factory, ICP rubric, copilot skills,
evidence-based researcher v1. See git history.
