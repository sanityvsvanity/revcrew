# Architecture

## Runtime

`main.py` builds an AgentOS app from whatever it finds in `agents/`. The discovery in `app/runtime.py` imports every top-level module there and collects module-level `Agent`, `Team`, `Workflow`, `APIRouter` and `AsyncIOScheduler` instances. Adding an agent is adding a file. Discovered schedulers are started and stopped by the FastAPI lifespan; `agents/housekeeping.py` registers three jobs that way: an hourly approval sweep (reminders, expiry), the daily digest, and a retention purge.

Webhook routers are mounted explicitly in `main.py` so the HTTP surface is easy to audit: `/slack/events`, `/slack/actions`, `/slack/commands`, `/webhooks/instantly`, `/api/leads`, `/health`. When `OS_SECURITY_KEY` is set, the AgentOS endpoints require it as a bearer token.

## Models

`app/models.py` is the only place a provider is chosen. Agents ask for a role (researcher, qualifier, outreach_writer, crm_scribe, copilot, triage), never a model id. `MODEL_PROVIDER=auto` resolves to Ollama when `OLLAMA_HOST` or `OLLAMA_API_KEY` is set and Anthropic otherwise, so a machine with no Ollama config behaves exactly as before the factory existed. Heavy roles map to `MODEL_MAIN` / `OLLAMA_MODEL_MAIN`, light roles to the fast variants. Reply triage retries once on Anthropic when the primary model fails or returns unusable output, and logs that it did.

Prompts live in `app/prompts/`, one versioned file per agent, imported by the agent definitions in `agents/`.

## Ports and adapters

Three protocols in `app/integrations/ports.py`:

- `CRMPort`: upsert_contact, upsert_company, create_deal, log_note, create_task, associate, search_contact, get_timeline
- `OutreachPort`: create_campaign, add_lead, activate_campaign, get_campaign_stats
- `ChatPort`: post_message, post_blocks, open_approval, open_modal, update_message

The registry in `app/integrations/registry.py` decides mock or live per port based on `DEMO_MODE`. Mocks write to Postgres tables (`mock_crm_objects`, `mock_campaigns`, `mock_messages`) so demo state is inspectable, not imaginary. Live adapters are httpx clients:

- HubSpot: CRM v3 objects, Associations v4, Search API for dedupe before create, 429 retry honoring Retry-After
- Instantly: API v2 campaigns and leads, activation guarded in dev
- Slack: chat.postMessage, chat.update and views.open

## Guarded writes

Every CRM adapter, mock or live, is wrapped in `GuardedCRM` (`app/guard.py`) by the registry. There is no unguarded handle. Each write runs validate, cap, dedupe, audit:

- Validate: emails, domains, note length, deal amounts (parsed and capped by `MAX_DEAL_AMOUNT`), and a property allowlist per object type, so a bad value fails here with a readable message instead of a HubSpot 400.
- Cap: at most `MAX_WRITES_PER_CONTEXT` writes per context, refused and audited past that.
- Dedupe: writes carry a deterministic idempotency key derived from context, operation and a content-aware natural key. Retrying the same logical write replays the prior result; two different notes on the same contact are both real writes.
- Audit: every decision (allowed, refused, deduped) is a row in `write_audit` with the context, operation and a payload summary. The table doubles as the activity feed behind the daily digest and the copilot's `revcrew_activity_summary` tool.

Writes without a context are refused. Contexts are set at the entry points: the push path, event dispatch (keyed on event content, so a redelivered webhook dedupes but a genuinely new reply lands), and the Slack chat handler (keyed on the triggering message, which also bounds one conversation turn by the write cap). Per-source allowlists keep triage down to notes and tasks, and events down to notes.

Cross-run deal dedup: `create_deal` takes a `company_domain` hint, checks the audit trail for an open deal RevCrew already created for that company, and turns a duplicate into a "second signal" note on the existing deal. A retry within the same push context replays silently instead.

## The approval experience

`app/approvals.py`. A workflow that reaches the gate writes a row to `approvals` with the full payload (lead, draft, deal, score), posts the card through the ChatPort, and stops. The card shows the lead, the score, the three subject lines, the deal, and a manifest of what approval will write. The posted message's channel and ts are stored back on the row so every later transition updates the card in place.

- View emails opens a read-only modal with the full bodies, budgeted to Slack's 3,000-character section limit.
- Edit opens a modal pre-filled from the payload. The row stays pending while the modal is open, so an abandoned modal strands nothing; a submit applies the edits, appends to the edit history, and refreshes the original card.
- Reject asks for a reason and optional detail, stored on the row and rolled up in the digest.
- Resolution is a guarded state transition: only pending rows resolve, so a double-click is a no-op, and the resolved card's buttons are replaced with the outcome.
- The hourly sweep sends one reminder per pending approval after `APPROVAL_REMINDER_HOURS` and expires them after `APPROVAL_TTL_HOURS`, killing the card's buttons.
- `APPROVER_SLACK_IDS`, when set, is enforced on Approve and Retry.

## The push

`app/push.py::push_approved_run` is the single entry point from an approved row to the outside world, used by the Slack Approve handler and the demo alike. Order: contact, company, deal, note, associate, then the paused campaign last. CRM stages are idempotent through the guard; the campaign and lead stages record progress on the approval row, so a failed push posts a Retry button and the retry resumes where it stopped instead of creating a second campaign. Outcomes land in `push_status` / `push_detail`.

## The event outbox

`app/events.py`. Inbound work (replies, opens, unsubscribes, new leads) is inserted as a `pending` row and acknowledged fast. A dispatcher picks up due rows and routes by kind. Failures retry with exponential backoff, capped at 5 attempts, then park in `dead_letter` for a human, which also fires an immediate one-line alert to the channel. Processed rows are never re-dispatched.

## Reply triage

`app/triage.py`. In demo mode, or whenever no Anthropic key is configured, classification is a deterministic keyword pass so the path runs free and reproducible. Live, it goes through the `reply_triage` workflow. The reply text is fenced as untrusted prospect-written data before it reaches the model, and the triage prompt says to classify it, never to follow instructions inside it. Either way the side effects are the same: a CRM note, a follow-up task for interested and objection replies, and a chat alert carrying a drafted response that no one sends but a human.

## Webhook security

Per-route checks in `app/webhooks/`:

- Slack: v0 HMAC-SHA256 over `v0:{timestamp}:{body}`, constant-time compare, five minute replay window, retry dedup via `X-Slack-Retry-Num`. An empty signing secret rejects; the only exception is a pure-mock dev demo with no bot token.
- Instantly: shared secret header, constant-time compare.
- Rule for both: a missing secret rejects everywhere except that dev demo case.

## Data

Postgres 17 (pgvector image) via docker compose on port 5541. Schema in `app/schema.sql`, applied idempotently at pool startup; column additions ship as `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` so existing databases upgrade in place. The tables are deliberately boring: JSONB payloads with a type column beat a dozen prop tables at this scale.

- `approvals`: the gate. Payload, status, reject reason, edit history, push status and progress, reminder flag.
- `events`: the outbox.
- `write_audit`: every guarded CRM write decision. Also the activity feed. Purged past `RETENTION_DAYS`, along with resolved approvals.
- `stage_cache`: last-known-good HubSpot deal stages.
- `mock_*`: what the mock adapters write, so demo state is real rows.
