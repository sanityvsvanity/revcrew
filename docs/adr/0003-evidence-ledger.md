# ADR 0003: an evidence ledger and a grounding gate, applied in code after generation

Date: 2026-09-08. Status: accepted.

## Context

A prompt that says "never invent a source" reduces fabrication. It does not remove it, and what remains
looks the same as real research on a Slack card. The measured case, from an earlier internal system in
August 2026: 22 of 30 accounts with no tool evidence, ten fabricated LinkedIn URLs, and made-up source
labels on unevidenced numbers.

## Decision

- Every research tool call writes a row to `evidence`, including misses, refusals and budget denials,
  with tier, provider, URL, content, outcome, cost and `tos_class`. One `research_runs` row per account
  holds the budget, the spend and the grounding report.
- After the researcher returns, `grounding.ground()` removes any URL the run's ledger does not hold from
  `sources` and from prose, moves claim lists to `gaps` when the run gathered nothing, and adds nothing.
  The report is shown as one line on the approval card.
- The same ledger serves as the cache (a page fetched in the last 48 hours costs nothing), the spend
  meter (per-account budget and the daily digest) and the audit trail.

## Alternatives considered

| Alternative | Reason not chosen |
|---|---|
| A stricter prompt | Tried in v1.1.0. The failure is structural: the model completes patterns. |
| An LLM judge over the brief | agno's judge sees the input and the output, not the tool results, so it would be guessing what was returned. A code scorer reads `RunOutput.tools`; the eval suite does this. |
| A schema constraint such as `Claim.source_ids` with `min_length=1` | Used by gpt-researcher and similar projects. It forces a citation but not a real one. The gate checks reality, and a schema constraint can be layered on later. |
| Logging instead of a table | Four readers need to query it: the gate, the cache, the digest and a person. |

## Consequences

- Research is auditable to the row and priced to the cent, and the card says how much of the brief is
  verified.
- Storage grows with research volume. Content is capped at 12,000 characters per row and purged with
  `RETENTION_DAYS`.
- A grounded brief can be thinner than an ungrounded one. That trade is accepted.
