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

Working with a coding agent? Point it at this repo and tell it to follow [AGENTS.md](AGENTS.md). It covers the spin-up, what credentials to ask you for at each stage, and how to verify every integration before touching the next.

## What the demo actually runs

Worth being precise about, because most agent demos are smoke and mirrors.

Real in every demo run:

- The approval gate. A row lands in the `approvals` table, the Block Kit message goes through the ChatPort, and the push step is unreachable until the row flips to approved. Kill the process mid-run and the approval survives.
- The event outbox. Replies enter as `events` rows and get dispatched with capped retries and a dead-letter state.
- Every adapter call. The mock HubSpot, Instantly and Slack adapters write real rows to Postgres that you can inspect with psql.

Canned in demo mode: the agent outputs. They live in `demo/data/canned.json`, validate against the schemas in `app/schemas.py`, and exist so the demo is deterministic and free. Set `DEMO_MODE=false` with a model provider configured (Ollama or an Anthropic key) and the real agents run instead.

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

| Component | Model tier | Job |
| --- | --- | --- |
| researcher | main | Account brief from web and CRM signals, outputs `AccountBrief` |
| qualifier | fast | Scores against `app/icp.yaml`, no tools, outputs `LeadScore` |
| outreach_writer | main | Drafts sequences, outputs `SequenceDraft`, holds no send tools |
| crm_scribe | fast | Sole holder of CRM write tools |
| copilot + gtm_desk | main | Slack-facing team that fields questions and call prep |
| lead_pipeline | workflow | research, qualify, gate on score, draft, approval, push |
| reply_triage | workflow | classify, log to CRM, alert the rep |

Agents ask `app/models.py` for a role, never a model id, so the whole crew moves between providers with env vars. On Ollama the main tier is qwen3:14b and the fast tier qwen3:4b by default; on Anthropic they are Sonnet and Haiku. Prompts live as versioned files in `app/prompts/`.

The integrations are ports and adapters. `CRMPort`, `OutreachPort` and `ChatPort` are protocols in `app/integrations/ports.py`; `DEMO_MODE` decides whether the registry hands out mocks or the live HubSpot, Instantly and Slack adapters. One partial-live rule: in demo mode with a `SLACK_BOT_TOKEN` set, chat goes live while CRM and outreach stay mocked, which is the right setup for demos in a real workspace.

More detail in [docs/architecture.md](docs/architecture.md).

## Humans stay in control

- Nothing is pushed anywhere until a human clicks Approve. The push step reads its inputs from the approved row, so there is no path around the gate.
- Every CRM write goes through a guard: validated, capped per run, deduplicated, and logged to an audit table you can query. The copilot's answer to "what did you do this week" comes from that table, not from memory.
- A second qualified signal for a company with an open deal becomes a note on that deal, not a duplicate deal.
- Suggested replies are drafts. The system never sends a reply on its own.
- Campaigns are always created paused. Activation refuses to run when `ENV=dev` unless forced.

## Setup, step by step

Each integration goes live independently. Do them in order, test after each one, stop wherever you like: Slack alone is already a working demo, and mock mode needs nothing at all.

### 1. Install and run the demo

Requirements: Python 3.12, Docker.

```bash
git clone https://github.com/sanityvsvanity/revcrew && cd revcrew
docker compose up -d
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m demo.run_demo
```

Postgres runs on port 5541 and the schema applies itself at startup, including upgrades on existing databases.

### 2. Start the server

```bash
./scripts/dev.sh
```

This copies `.env.example` to `.env` if you don't have one and serves on port 8000. Check it's up:

```bash
curl http://localhost:8000/health
```

### 3. Connect Slack

Slack needs to reach your server. For a local trial, open a tunnel and note the domain it prints:

```bash
cloudflared tunnel --url http://localhost:8000
```

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From a manifest. Paste `slack/manifest.yaml`, replacing `PLACEHOLDER` in the three URLs with your tunnel or deployment domain. The server must be running: Slack verifies the events URL when you save.
2. Install the app to your workspace. Copy the Bot User OAuth Token (`xoxb-...`) into `SLACK_BOT_TOKEN`, and the Signing Secret from Basic Information into `SLACK_SIGNING_SECRET`.
3. Create a channel, `/invite @RevCrew` into it, and copy the channel ID (bottom of the channel details pane) into `SLACK_CHANNEL_ID`.
4. Restart the server, then run `/demo new-lead` in the channel. A card with Approve, Edit, Reject and View emails should appear. With `DEMO_MODE=true` chat is live while CRM and outreach stay mocked, so you can click everything without touching real systems.
5. Optional: put the Slack user IDs allowed to approve in `APPROVER_SLACK_IDS`, comma-separated. Empty means anyone in the channel.

### 4. Connect HubSpot

Use a [developer test account](https://developers.hubspot.com/get-started) first, not your production portal.

1. In the test account: Settings → Integrations → Private Apps → Create a private app.
2. Scopes: `crm.objects.contacts.read` and `.write`, same for `companies` and `deals`.
3. Copy the token into `HUBSPOT_PRIVATE_APP_TOKEN`.
4. Verify:

```bash
curl -H "Authorization: Bearer $HUBSPOT_PRIVATE_APP_TOKEN" "https://api.hubapi.com/crm/v3/objects/contacts?limit=1"
```

The adapter dedupes before create (contacts by email, companies by domain) and prefixes every note with `RevCrew:` so you can always tell what the system wrote. Set `HUBSPOT_DEFAULT_OWNER_ID` if you want tasks assigned to someone by default.

### 5. Connect Instantly

1. Copy an API v2 key from your workspace settings into `INSTANTLY_API_KEY`.
2. Configure a webhook pointed at `https://your-domain/webhooks/instantly`, sending a shared secret in the `X-RevCrew-Secret` header. Put the same value in `INSTANTLY_WEBHOOK_SECRET`.
3. Campaigns arrive paused, always. Review them in the Instantly UI before activating anything.

### 6. Pick your models

One setting decides the provider. `MODEL_PROVIDER=auto` (the default) uses Ollama whenever it is configured, Anthropic otherwise:

- ollama.cloud: set `OLLAMA_API_KEY` and leave `OLLAMA_HOST` empty
- Local Ollama: point `OLLAMA_HOST` at your server, e.g. `http://localhost:11434`
- Anthropic: set `ANTHROPIC_API_KEY` and no Ollama variables

Heavy roles (research, writing, copilot) use `OLLAMA_MODEL_MAIN` (default qwen3:14b) or Sonnet; light roles (scoring, triage, CRM entry) use `OLLAMA_MODEL_FAST` (default qwen3:4b) or Haiku. Set `MODEL_PROVIDER=anthropic` or `ollama` to pin a provider regardless of what else is configured.

When Ollama is primary and an Anthropic key is also set, reply triage retries once on Anthropic if the local model fails or returns unusable output, and says so in the logs. Small local models occasionally miss structured output; the retry is there so a flaky classification never drops a prospect reply.

### 7. Put it online

The app is one uvicorn process plus Postgres. Any host that runs both works; Railway, Render and Fly all do it with a managed Postgres attached.

1. Provision Postgres 17 and set `DATABASE_URL`. The schema applies itself on first start.
2. Deploy the repo with `pip install -r requirements.txt` as the build step and this as the start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

3. Set the environment variables from your `.env`. Set `OS_SECURITY_KEY` to a long random string: it becomes the bearer token protecting the AgentOS API endpoints.
4. Update the three Slack URLs (events, actions, commands) and the Instantly webhook to the deployment domain.

### 8. Cut over to live

- `ENV=prod`, which makes missing webhook secrets a hard reject
- `DEMO_MODE=false`
- Send a test lead through `/api/leads`: it should land in HubSpot with a paused campaign in Instantly
- Simulate a reply at `/webhooks/instantly`: it should produce a triage alert and a CRM task
- Confirm the digest arrives at the hour set in `DIGEST_HOUR` / `DIGEST_TZ`
- Check `write_audit` and the Instantly UI: no campaign has ever been activated by the system

Approval TTLs, the digest schedule, write caps, retention and model settings all have sane defaults, documented in `.env.example`. The condensed version of this section lives in [docs/integrations.md](docs/integrations.md).

## The daily loop

1. Leads arrive through `/api/leads`, or `/demo new-lead` while you're evaluating.
2. Each qualified lead becomes a Slack card: who they are, the score, three subject lines, the deal, and exactly what will be written. **View emails** shows the full bodies. **Edit** opens a pre-filled modal and updates the card in place. **Reject** asks why, and the reasons roll up in the digest.
3. **Approve** pushes contact, company, deal and a note to HubSpot, then a paused campaign to Instantly. You activate campaigns in the Instantly UI. If a push fails partway, the thread gets a Retry button, and retries skip whatever already succeeded.
4. Replies come back through the webhook, get triaged, and land as an alert with a drafted response and a follow-up task. Nothing sends without you.
5. Pending approvals get one reminder after 24 hours and expire after 72. Both are configurable.
6. Each morning a digest posts what was approved, rejected and written, plus anything that needs attention: failed pushes, dead-letter events.
7. Mention the bot for call prep or a straight answer about pipeline state.

## Slack commands

- `/demo new-lead` walks the next seed lead up to the approval gate
- `/demo reply` feeds a canned reply through the outbox and triage
- `/demo reset` clears mock state
- Mention the bot to talk to the crew (needs a configured model provider)

Webhook hygiene: Slack requests are verified with the v0 HMAC signature, stale timestamps outside a five minute window are rejected, and Slack retries are deduped. Instantly webhooks verify a shared secret. A missing secret rejects everywhere except a pure-mock dev demo.

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
