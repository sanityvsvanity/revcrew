# AGENTS.md

Instructions for coding agents setting up RevCrew on behalf of a human operator. If a person pointed you at this repo and said "spin this up", follow this file top to bottom. Everything here is also in the [README](README.md) in human-oriented form.

First question to the operator, before doing anything: demo first, or straight toward live? Demo needs zero credentials and takes about two minutes; live needs whichever of Slack, HubSpot, Instantly and model keys they want to connect. Recommend demo first unless they already know the system: it proves the install works before any credential is involved. (`start.py` asks a human this same question interactively; as an agent, ask it in chat and drive the steps below yourself.)

## Ground rules

- Stay in mock mode (`DEMO_MODE=true`, the default) until the operator explicitly asks to go live. Mock mode needs zero credentials and writes only to local Postgres.
- Never activate an outreach campaign. The system creates campaigns paused by design; activation is a human action in the Instantly UI.
- HubSpot means a developer test account unless the operator explicitly says production. Do not point `HUBSPOT_PRIVATE_APP_TOKEN` at a production portal on your own initiative.
- Secrets go in `.env`, which is gitignored. Never commit credentials, and never echo full token values back into the chat.
- Integrations go live one at a time, in the order below, with a verification step after each. Do not batch them.

## Spin up with zero credentials

Requirements: Python 3.12 and Docker. Check both before starting; these are the two things most likely to be missing.

```bash
docker compose up -d
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m demo.run_demo
```

Success looks like: the demo prints seven beats, ends with a "State written to Postgres by this run" block, and exits 0. Postgres runs on port 5541 (not 5432, to avoid clashing with an existing local instance) and the schema applies itself on startup.

If the demo passes, run the test suite:

```bash
.venv/bin/python -m pytest
```

81 tests. DB-backed tests skip automatically when Postgres is down, so a low pass count usually means the Docker container is not up.

Then start the server and confirm it is healthy:

```bash
./scripts/dev.sh
curl http://localhost:8000/health
```

`dev.sh` copies `.env.example` to `.env` if one does not exist and serves on port 8000. Report the demo output and test count to the operator before going further.

## Customize the ICP rubric

Do this before connecting anything. The shipped rubric targets B2B SaaS, which is almost certainly not the operator's ICP, and every live lead will be scored against whatever is in the rubric file.

Interview the operator, in their language, not yaml:

- Which industries or segments are ideal, and which are explicitly out of scope
- Company size band (employees, revenue, whatever they think in)
- Signals that make a lead hot: tech stack, hiring, funding, expansion
- Who they want to talk to (roles, seniority)
- Instant disqualifiers (competitors, agencies, personal email domains, regions)
- Roughly how they would weight those against each other

Then write their answers into `app/icp.yaml` (or a copy referenced by `ICP_PATH`): `target_segments` with include and exclude lists, weighted `criteria` (weights must sum to 100, every criterion needs a description), `tiers`, and `hard_disqualifiers`. The qualifier's scoring instructions are rendered from this file at startup, so this file is the whole customization surface.

Validate before restarting:

```bash
.venv/bin/python -c "from app.icp import load_icp; load_icp(); print('rubric ok')"
```

Read the rendered result back to the operator in plain English and confirm it matches what they said. Two things to tell them: `ICP_SCORE_THRESHOLD` in `.env` is the score below which leads never reach outreach, and demo mode agent outputs are canned, so the new rubric shows in live runs, not in the demo walkthrough.

## Going live, one integration at a time

Each stage lists what to ask the operator to gather. Ask for the whole list for a stage up front, then wire and verify before moving on. Full walkthrough with screenshots-level detail: [README, "Setup, step by step"](README.md#setup-step-by-step).

### Stage 1: Slack

Ask the operator for:

- A Slack workspace where they can install apps.
- If running locally, permission to open a tunnel: `cloudflared tunnel --url http://localhost:8000` (or their preferred tunnel). Slack must be able to reach the server.

Then walk them through app creation at api.slack.com/apps using `slack/manifest.yaml`, replacing `PLACEHOLDER` in the three URLs with the tunnel or deployment domain. The server must be running when they save; Slack verifies the events URL immediately.

Collect into `.env`: `SLACK_BOT_TOKEN` (xoxb, from OAuth), `SLACK_SIGNING_SECRET` (Basic Information), `SLACK_CHANNEL_ID` (a channel the bot has been invited to). Optionally `APPROVER_SLACK_IDS`.

Verify: restart the server, run `/demo new-lead` in the channel. An approval card with Approve, Edit, Reject and View emails buttons should appear. In demo mode chat is live while CRM and outreach stay mocked, so every button is safe to click.

### Stage 2: HubSpot

Ask the operator for a private app token from a HubSpot developer test account with read and write scopes on contacts, companies and deals. Point them at developers.hubspot.com/get-started if they do not have a test account.

Collect: `HUBSPOT_PRIVATE_APP_TOKEN`, optionally `HUBSPOT_DEFAULT_OWNER_ID`.

Verify:

```bash
curl -H "Authorization: Bearer $HUBSPOT_PRIVATE_APP_TOKEN" "https://api.hubapi.com/crm/v3/objects/contacts?limit=1"
```

### Stage 3: Instantly

Ask the operator for an API v2 key from their Instantly workspace settings, and have them configure a webhook to `https://<domain>/webhooks/instantly` sending a shared secret in the `X-RevCrew-Secret` header.

Collect: `INSTANTLY_API_KEY`, `INSTANTLY_WEBHOOK_SECRET` (same value as the header).

### Stage 4: Models

Ask the operator which provider they want. `MODEL_PROVIDER=auto` (default) resolves to Ollama when Ollama is configured, Anthropic otherwise:

- ollama.cloud: `OLLAMA_API_KEY` set, `OLLAMA_HOST` empty
- Local Ollama: `OLLAMA_HOST` set, e.g. http://localhost:11434
- Anthropic: `ANTHROPIC_API_KEY` set, no Ollama variables

Ollama defaults are qwen3:14b for heavy roles and qwen3:4b for light ones. If Ollama is primary, recommend also setting `ANTHROPIC_API_KEY`: reply triage then retries once on Anthropic when the local model produces unusable output.

### Stage 5: Deployment

One uvicorn process plus Postgres 17; Railway, Render and Fly all work with a managed Postgres attached. Build step `pip install -r requirements.txt`, start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Set `DATABASE_URL` and the variables from `.env`, and generate a long random `OS_SECURITY_KEY` (it becomes the bearer token on the AgentOS API). After deploy, update the three Slack URLs and the Instantly webhook to the new domain.

### Stage 6: Cutover

Only with explicit operator confirmation: `ENV=prod`, `DEMO_MODE=false`. Then run the checks in the README's "Cut over to live" section: a test lead through `POST /api/leads`, a simulated reply through the webhook, digest arrival, and a `write_audit` query confirming no campaign was ever activated by the system.

## Map of the code

| Path | What lives there |
| --- | --- |
| `agents/` | The five agents and the two workflows |
| `app/models.py` | Model factory; the only place a provider is chosen |
| `app/icp.yaml`, `app/icp.py` | The ICP rubric and its loader; the qualifier scores against this |
| `app/prompts/` | Versioned prompt files per agent |
| `app/guard.py` | Guarded CRM writes: validation, caps, dedup, audit |
| `app/approvals.py`, `app/push.py` | Approval state machine and the sole push entry point |
| `app/integrations/` | Ports, plus mock and live adapters; `DEMO_MODE` picks |
| `app/webhooks/` | Slack, Instantly and lead intake endpoints |
| `demo/` | Deterministic demo pipeline and seed data |
| `docs/` | Architecture, demo and integration guides |

## Common failure points

- `python3` is not 3.12: use `python3.12` explicitly, the venv pins it from there.
- Demo or tests fail on DB errors: `docker compose up -d` was not run, or something else took port 5541.
- Slack manifest save fails: the server is not running or the tunnel URL is wrong; Slack verifies the events URL at save time.
- Slack card buttons do nothing: `SLACK_SIGNING_SECRET` missing or the actions URL still says `PLACEHOLDER`.
- Live agents error immediately: no model provider configured; see Stage 4.
