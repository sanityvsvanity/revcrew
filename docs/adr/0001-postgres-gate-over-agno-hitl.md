# ADR 0001 — Keep the Postgres approval gate; end the workflow at it

Date: 2026-09-08 · Status: accepted

## Context

agno 3.0 ships workflow human-in-the-loop as a first-class primitive: `Step(human_review=HumanReview(
requires_confirmation=True))` pauses a workflow run, AgentOS exposes `/workflows/{id}/runs/{run_id}/continue`,
and `QueueConfig(durable=True)` makes the paused run survive a deploy. RevCrew's gate predates this: a
row in `approvals` with the full payload, a Block Kit card with Approve / Edit / Reject / View emails,
reminders, TTL expiry, an approver allowlist, and a resumable push with a Retry button.

The v1 `lead_pipeline` also had a defect: a `push_and_log` step ran immediately after `approval_gate`,
so the live intake path (`/api/leads` → `lead_received` → `lead_pipeline.arun`) created a campaign and
CRM records before anyone clicked. The demo never hit it because the demo drives the beats by hand.

## Decision

1. The workflow ends at `approval_gate`. The only path to HubSpot or Instantly is a human Approve in
   Slack calling `push_approved_run`. `tests/test_pipeline_shape.py` pins the shape.
2. The gate stays in Postgres for v2. agno's `HumanReview` is not adopted yet.

## Why not agno's HITL now

| agno `HumanReview` gives | RevCrew's gate has that agno's does not |
|---|---|
| Pause/continue in the framework, visible in AgentOS | Edit-in-place modal with edit history; View emails; Reject with reason rolled into the digest |
| Durable across deploys with `QueueConfig(durable=True)` (needs the job queue) | Zero-key demo: the full gate runs against local Postgres with mocks |
| One continue endpoint | Reminders after 24 h, expiry after 72 h, approver allowlist, Retry that resumes a half-failed push |

Adopting `HumanReview` means re-implementing the card UX on agno's Slack interface or losing it, and
running AgentOS's durable queue in the demo. The card UX *is* the product's demo. The trade is worth
making when a second chat surface (Teams, web) needs the same gate; then the framework's pause is
the shared primitive and the card becomes a renderer. Until then, one gate in Postgres, ending the
workflow, is the smaller and more honest system.

## Consequences

- A lead that scores above threshold produces exactly one `approvals` row and one card, and nothing else.
- `_approval_gate_step` now carries the grounded brief's sources, gaps and research report into the
  payload, so the card can show evidence.
- Re-evaluate when: agno's Slack interface renders `HumanReview` cards with custom blocks, or a second surface appears.
