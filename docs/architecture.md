# Architecture

## Runtime

`main.py` builds an AgentOS app from whatever it finds in `agents/`. The discovery in `app/runtime.py` imports every top-level module there and collects module-level `Agent`, `Team`, `Workflow`, `APIRouter` and `AsyncIOScheduler` instances. Adding an agent is adding a file.

Webhook routers are mounted explicitly in `main.py` so the HTTP surface is easy to audit: `/slack/events`, `/slack/actions`, `/slack/commands`, `/webhooks/instantly`, `/api/leads`, `/health`.

## Ports and adapters

Three protocols in `app/integrations/ports.py`:

- `CRMPort`: upsert_contact, upsert_company, create_deal, log_note, create_task, associate, search_contact, get_timeline
- `OutreachPort`: create_campaign, add_lead, activate_campaign, get_campaign_stats
- `ChatPort`: post_message, post_blocks, open_approval, update_message

The registry in `app/integrations/registry.py` decides mock or live per port based on `DEMO_MODE`. Mocks write to Postgres tables (`mock_crm_objects`, `mock_campaigns`, `mock_messages`) so demo state is inspectable, not imaginary. Live adapters are httpx clients:

- HubSpot: CRM v3 objects, Associations v4, Search API for dedupe before create, 429 retry honoring Retry-After
- Instantly: API v2 campaigns and leads, activation guarded in dev
- Slack: chat.postMessage and chat.update

## The approval gate

`app/approvals.py`. A workflow that reaches the gate writes a row to `approvals` with the drafted sequence in the payload, posts Approve, Edit, Reject buttons through the ChatPort, and stops. Resolution comes from a Slack button click or, in the headless demo, an explicit call. The push step reads its inputs from the approved row, which gives two properties:

1. No path to the outreach push except through an approved row
2. A restart between gate and approval loses nothing

## The event outbox

`app/events.py`. Inbound work (replies, opens, unsubscribes, new leads) is inserted as a `pending` row and acknowledged fast. A dispatcher picks up due rows and routes by kind. Failures retry with exponential backoff, capped at 5 attempts, then park in `dead_letter` for a human. Processed rows are never re-dispatched.

## Reply triage

`app/triage.py`. In demo mode, or whenever no Anthropic key is configured, classification is a deterministic keyword pass so the path runs free and reproducible. Live, it goes through the `reply_triage` workflow and a Haiku classifier. Either way the side effects are the same: a CRM note, a follow-up task for interested and objection replies, and a chat alert carrying a drafted response that no one sends but a human.

## Webhook security

`app/webhooks/signature.py` plus per-route checks:

- Slack: v0 HMAC-SHA256 over `v0:{timestamp}:{body}`, constant-time compare, five minute replay window, retry dedup via `X-Slack-Retry-Num`
- Instantly: shared secret header, constant-time compare
- Rule for both: a missing secret rejects when `ENV=prod` and warns when dev

## Data

Postgres 17 (pgvector image) via docker compose on port 5541. Schema in `app/schema.sql`, applied idempotently at pool startup. The demo tables are deliberately boring: JSONB payloads with a type column beat a dozen prop tables at this scale.
