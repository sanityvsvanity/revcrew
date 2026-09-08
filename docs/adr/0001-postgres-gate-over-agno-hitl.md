# ADR 0001: keep the Postgres approval gate and end the workflow at it

Date: 2026-09-08. Status: accepted.

## Context

agno 3.0 has workflow human-in-the-loop built in. `Step(human_review=HumanReview(requires_confirmation=True))`
pauses a workflow run, AgentOS exposes `/workflows/{id}/runs/{run_id}/continue`, and
`QueueConfig(durable=True)` keeps a paused run across a deploy.

RevCrew's gate predates this. It is a row in `approvals` holding the full payload, a Block Kit card with
Approve, Edit, Reject and View emails, reminders, expiry, an approver allowlist, and a push that can be
retried from where it failed.

The v1 `lead_pipeline` also had a defect. A `push_and_log` step ran immediately after `approval_gate`,
so the live intake path (`/api/leads` to `lead_received` to `lead_pipeline.arun`) created a campaign
and CRM records before anyone had clicked. The demo never showed it because the demo drives the beats
by hand.

## Decision

1. The workflow ends at `approval_gate`. The only path to HubSpot or Instantly is a human Approve in
   Slack, which calls `push_approved_run`. `tests/test_pipeline_shape.py` pins this.
2. The gate stays in Postgres for v2. agno's `HumanReview` is not adopted yet.

## Comparison

| agno `HumanReview` provides | RevCrew's gate provides that agno's does not |
|---|---|
| Pause and continue inside the framework, visible in AgentOS | An Edit modal that updates the card in place and keeps an edit history; View emails; Reject with a reason that rolls into the digest |
| Durability across deploys with `QueueConfig(durable=True)`, which needs the job queue | A zero-key demo where the full gate runs against local Postgres with mocks |
| One continue endpoint | Reminders after 24 hours, expiry after 72, an approver allowlist, and a Retry that resumes a half-failed push |

Adopting `HumanReview` would mean rebuilding the card on agno's Slack interface or dropping those
features, and running AgentOS's durable queue in the demo. The card is what the demo shows. The switch
becomes worth it when a second chat surface (Teams, a web UI) needs the same gate; the framework pause
then becomes the shared primitive and the Slack card becomes one renderer of it.

## Consequences

- A lead that scores above threshold produces one `approvals` row and one card, and nothing else.
- `_approval_gate_step` carries the grounded brief's sources, gaps and research report into the payload
  so the card can show evidence.
- Revisit when agno's Slack interface can render `HumanReview` cards with custom blocks, or when a second
  surface appears.
