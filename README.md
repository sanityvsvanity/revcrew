# RevCrew

An AI revenue crew for B2B sales teams. It researches accounts, scores leads against your ICP, drafts outreach and logs every touch. Your reps approve, edit or reject from Slack. Agents do the work. Humans keep the judgment calls.

Built on [Agno](https://github.com/agno-agi/agno) with FastAPI and Postgres. Five agents, one team, two workflows.

## Where it fits

- A founder or first sales hire doing outbound alone. The crew handles research, scoring and drafts; you approve from Slack between calls.
- A small SDR team on HubSpot and Instantly. Every touch is logged, deals are deduped across runs, and the manager reads a digest instead of asking around.
- Evaluating agent systems. Mock mode runs the whole pipeline against Postgres with zero credentials, so you can inspect exactly what an agent team would do to your CRM before you connect one.

## Quickstart

```bash
git clone https://github.com/sanityvsvanity/revcrew && cd revcrew
docker compose up -d
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m demo.run_demo
```

No credentials, no API keys, no .env editing. The demo walks a Tier A lead from intake to booked call in seven beats and exits 0.

## What the demo actually runs

Worth being precise about, because most agent demos are smoke and mirrors.

Real in every demo run:

- The approval gate. A row lands in the `approvals` table, the Block Kit message goes through the ChatPort, and the push step is unreachable until the row flips to approved. Kill the process mid-run and the approval survives.
- The event outbox. Replies enter as `events` rows and get dispatched with capped retries and a dead-letter state.
- Every adapter call. The mock HubSpot, Instantly and Slack adapters write real rows to Postgres that you can inspect with psql.

Canned in demo mode: the agent outputs. They live in `demo/data/canned.json`, validate against the schemas in `app/schemas.py`, and exist so the demo is deterministic and free. Set `DEMO_MODE=false` with an `ANTHROPIC_API_KEY` and the real agents run instead.

The demo closes by reading the state back out of Postgres:

```
State written to Postgres by this run:
  mock_crm_objects   company: 1, contact: 1, deal: 1, note: 2, task: 1
  mock_campaigns     1 (paused)
  approvals          approved: 1
  events             processed: 1
  mock_messages      2
```

## The seven beats

1. A new lead arrives with intent signals
2. Researcher produces an account brief
3. Qualifier scores it against the ICP rubric in `app/icp.yaml`
4. Outreach writer drafts a three step sequence
5. The approval gate opens in Slack. Approve pushes a paused campaign to Instantly and contact, company, deal and note to HubSpot
6. A reply comes back through the webhook, gets triaged, and the rep gets an alert with a drafted response
7. Ask the copilot to prep you for the call

## Architecture

| Component | Model | Job |
| --- | --- | --- |
| researcher | Sonnet | Account brief from web and CRM signals, outputs `AccountBrief` |
| qualifier | Haiku | Scores against `app/icp.yaml`, no tools, outputs `LeadScore` |
| outreach_writer | Sonnet | Drafts sequences, outputs `SequenceDraft`, holds no send tools |
| crm_scribe | Haiku | Sole holder of CRM write tools |
| copilot + gtm_desk | Sonnet | Slack-facing team that fields questions and call prep |
| lead_pipeline | workflow | research, qualify, gate on score, draft, approval, push |
| reply_triage | workflow | classify, log to CRM, alert the rep |

The integrations are ports and adapters. `CRMPort`, `OutreachPort` and `ChatPort` are protocols in `app/integrations/ports.py`; `DEMO_MODE` decides whether the registry hands out mocks or the live HubSpot, Instantly and Slack adapters. One partial-live rule: in demo mode with a `SLACK_BOT_TOKEN` set, chat goes live while CRM and outreach stay mocked, which is the right setup for demos in a real workspace.

More detail in [docs/architecture.md](docs/architecture.md).

## Humans stay in control

- Nothing is pushed anywhere until a human clicks Approve. The push step reads its inputs from the approved row, so there is no path around the gate.
- Every CRM write goes through a guard: validated, capped per run, deduplicated, and logged to an audit table you can query. The copilot's answer to "what did you do this week" comes from that table, not from memory.
- A second qualified signal for a company with an open deal becomes a note on that deal, not a duplicate deal.
- Suggested replies are drafts. The system never sends a reply on its own.
- Campaigns are always created paused. Activation refuses to run when `ENV=dev` unless forced.

## The daily loop

1. Leads arrive through `/api/leads`, or `/demo new-lead` while you're evaluating.
2. Each qualified lead becomes a Slack card: who they are, the score, three subject lines, the deal, and exactly what will be written. **View emails** shows the full bodies. **Edit** opens a pre-filled modal and updates the card in place. **Reject** asks why, and the reasons roll up in the digest.
3. **Approve** pushes contact, company, deal and a note to HubSpot, then a paused campaign to Instantly. You activate campaigns in the Instantly UI. If a push fails partway, the thread gets a Retry button, and retries skip whatever already succeeded.
4. Replies come back through the webhook, get triaged, and land as an alert with a drafted response and a follow-up task. Nothing sends without you.
5. Pending approvals get one reminder after 24 hours and expire after 72. Both are configurable.
6. Each morning a digest posts what was approved, rejected and written, plus anything that needs attention: failed pushes, dead-letter events.
7. Mention the bot for call prep or a straight answer about pipeline state.

## Slack

The app manifest is in `slack/manifest.yaml`. Once installed:

- `/demo new-lead` walks the next seed lead up to the approval gate
- Approve, Edit, Reject and View emails resolve the gate from the card; Approve completes the push
- `/demo reply` feeds a canned reply through the outbox and triage
- `/demo reset` clears mock state
- Mention the bot to talk to the crew (needs an Anthropic key)
- `APPROVER_SLACK_IDS` limits who can approve; empty means anyone in the channel

Webhook hygiene: Slack requests are verified with the v0 HMAC signature, stale timestamps outside a five minute window are rejected, and Slack retries are deduped. Instantly webhooks verify a shared secret. A missing secret rejects everywhere except a pure-mock dev demo.

## Models

Anthropic by default: Sonnet for research, writing and the copilot, Haiku for scoring, triage and CRM entry. To run on your own hardware, point `OLLAMA_HOST` at a local Ollama server, or set `OLLAMA_API_KEY` for ollama.cloud. Heavy roles use `OLLAMA_MODEL_MAIN` (default qwen3:14b), light roles `OLLAMA_MODEL_FAST` (default qwen3:4b). Reply triage retries once on Anthropic when the local model fails, and says so in the logs. No Ollama config means pure Anthropic and nothing changes.

## Going live

Copy `.env.example` to `.env` and fill in what you use:

| Variable | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Live agent runs |
| `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_CHANNEL_ID` | Slack app from `slack/manifest.yaml` |
| `HUBSPOT_PRIVATE_APP_TOKEN` | Private app with CRM object read and write scopes |
| `INSTANTLY_API_KEY`, `INSTANTLY_WEBHOOK_SECRET` | Instantly API v2 |
| `OS_SECURITY_KEY` | Bearer token for the AgentOS API on reachable deploys |

Then set `DEMO_MODE=false`. Test against a HubSpot developer sandbox and an Instantly test workspace before pointing it at production data. Integration guide in [docs/integrations.md](docs/integrations.md).

Approval TTLs, the digest schedule, write caps, retention and model provider settings all have sane defaults and are documented in `.env.example`.

## Tests

```bash
.venv/bin/python -m pytest
```

68 tests: schemas, discovery, signature rules, outbox retry and dead-letter, webhook auth, guarded writes, the approval flow end to end (edit in place, retry after a failed push, deal dedup, reject reasons), and a golden path test that asserts the demo leaves exactly the state it claims. DB-backed tests skip when Postgres is down.

## Observability

RevCrew ships with an OpenTelemetry bridge for [Agno Viz](https://github.com/sanityvsvanity/Agno-viz), a 3D topology visualizer for agent systems. Set `TRACING_ENABLED=true` with the `AGNO_VIZ_*` variables and watch the crew think in real time. The bridge package is not in `requirements.txt`: install it separately from the [Agno-viz repo](https://github.com/sanityvsvanity/Agno-viz), otherwise the flag is a no-op.

## Who built this

Gagan Dasari. I run [GTMpro](https://gtmpro.com.au), an agentic GTM engineering practice in Melbourne. I build agent teams for revenue work: research, qualification, outreach and conversation, wired into the stack you already run.

gagan@gtmpro.com.au · [LinkedIn](https://www.linkedin.com/in/gaganbuilds) · [GitHub](https://github.com/sanityvsvanity)
