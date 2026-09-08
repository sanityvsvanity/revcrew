# ADR 0003 — An evidence ledger and a grounding gate, in code, after generation

Date: 2026-09-08 · Status: accepted

## Context

Prompts that say "never invent a source" reduce fabrication; they do not eliminate it, and the
residue is indistinguishable from real research on a Slack card. The measured case
(2026-08-11, predecessor system): 22 of 30 accounts with zero tool evidence, ten fabricated LinkedIn
URLs, fake source labels on unevidenced numbers.

## Decision

- Every research tool call writes a row to `evidence` — including misses, refusals and budget
  denials — with tier, provider, URL, content, outcome, cost and `tos_class`. One `research_runs` row
  per account holds the budget, the spend and the grounding report.
- After the researcher returns, `grounding.ground()` removes any URL the run's ledger does not hold,
  from `sources` and from prose, moves claim lists to `gaps` when the run gathered nothing, and never
  adds a fact. The report is one line on the approval card.
- The same ledger is the cache (a page fetched in the last 48 h is free), the spend meter (per-account
  budget; daily digest), and the audit trail (`psql`).

## Why not …

| Alternative | Why not |
|---|---|
| A stricter prompt | Already tried (v1.1.0). The failure is structural: the model completes patterns. |
| An LLM judge on the brief | agno's judge sees input and output, not tool results; it would be guessing what was returned. A code scorer reads `RunOutput.tools` (the eval suite does this too). |
| Schema-level `Claim.source_ids` with `min_length=1` | Good pattern (gpt-researcher, deep-research repos use it); it forces a citation, not a *real* one. The gate checks reality; the schema can be tightened later on top of it. |
| Logging instead of a table | Four readers need to query it: the gate, the cache, the digest and a human. |

## Consequences

- Research is auditable to the row and priced to the cent; the card says how much of the brief is verified.
- Storage grows with research volume; content is capped at 12,000 chars per row and purged with
  `RETENTION_DAYS`.
- A grounded brief can be *thinner* than an ungrounded one. That is the intended trade.
