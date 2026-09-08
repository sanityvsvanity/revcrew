# RevCrew

[![ci](https://github.com/sanityvsvanity/revcrew/actions/workflows/ci.yml/badge.svg)](https://github.com/sanityvsvanity/revcrew/actions/workflows/ci.yml)

An agentic revenue crew for B2B sales teams. It researches accounts, scores leads against your ICP, drafts outreach and logs every touch. Your reps approve, edit or reject from Slack. Agents do the work. Humans keep the judgment calls.

Built on [Agno 3.0.7](https://github.com/agno-agi/agno) with FastAPI and Postgres. Five agents, one team, two workflows. Since v2 the researcher runs on a tiered research stack with a ledger: every fact in an account brief traces to a recorded tool call, every research call is budgeted and priced, and a grounding gate removes anything the model made up before a rep sees it. The design is in [docs/research-stack.md](docs/research-stack.md).

## Where it fits (examples):

- A founder or first sales hire doing outbound alone. The crew handles research, scoring and drafts; you approve from Slack between calls.
- A small SDR team on HubSpot and Instantly. Every touch is logged, deals are deduped across runs, and the manager reads a digest instead of asking around.
- Evaluating agent systems. Mock mode runs the whole pipeline against Postgres with zero credentials, so you can inspect exactly what an agent team would do to your CRM before you connect one.

## Two ways in

```bash
git clone https://github.com/sanityvsvanity/revcrew && cd revcrew
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python start.py
```

`start.py` asks one question: demo or live.

**Demo, zero keys.** The full pipeline runs against local Postgres in about two minutes: real approval gate, real outbox, real database state, canned agent outputs. No credentials, no .env editing. The demo walks a Tier A lead from intake to booked call in seven beats and exits 0.

**Live, your stack.** The wizard collects Slack, HubSpot, Instantly and model credentials one integration at a time, checks each against the real API as you enter it, and writes your `.env`. Everything is optional and independent: connect one integration, test it, come back for the next. Slack alone already gives you the full approval experience with CRM and outreach safely mocked.

Prefer commands over prompts? `docker compose up -d && .venv/bin/python -m demo.run_demo` is the demo, and [Setup, step by step](#setup-step-by-step) is live mode by hand.

Working with a coding agent? Point it at this repo and tell it to follow [AGENTS.md](AGENTS.md). It covers the spin-up, what credentials to ask you for at each stage, and how to verify every integration before touching the next.

## What the demo actually runs

Worth being precise about, because most agent demos are smoke and mirrors.

Real in every demo run:

- The approval gate. A row lands in the `approvals` table, the Block Kit message goes through the ChatPort, and the push step is unreachable until the row flips to approved. Kill the process mid-run and the approval survives.
- The event outbox. Replies enter as `events` rows and get dispatched with capped retries and a dead-letter state.
- Every adapter call. The mock HubSpot, Instantly and Slack adapters write real rows to Postgres that you can inspect with psql.

Canned in demo mode: the agent outputs. They live in `demo/data/canned.json`, validate against the schemas in `app/schemas.py`, and exist so the demo is deterministic and free. Set `DEMO_MODE=false` with a model provider configured (Ollama or an Anthropic key) and the real agents run instead. The research stack then runs for real as well, at the free tier if you add no other keys.

Also real in every mode, and tested against Postgres in CI: the evidence ledger, the grounding gate, the per-account research budget, the domain policy, and the rule that the workflow ends at the approval gate.

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

## Make it score your ICP, not ours

The rubric lives in [`app/icp.yaml`](app/icp.yaml): target segments, weighted criteria, tier cutoffs and hard disqualifiers. The qualifier's scoring instructions are built from this file at startup, so what you write there is exactly what the agent scores against. Edit it in place, or point `ICP_PATH` at your own copy to keep your rubric out of the repo, then restart.

Weights must sum to 100 and every criterion needs a description. A broken rubric stops the server with an error that says which line to fix. Check an edit without restarting:

```bash
.venv/bin/python -c "from app.icp import load_icp; load_icp(); print('rubric ok')"
```

The B tier cutoff comes from `ICP_SCORE_THRESHOLD`, the same number that gates the pipeline: leads scoring below it never reach the outreach writer. One caveat: demo mode agent outputs are canned, so a rubric edit shows up in live runs, not in the demo walkthrough.

## Give the copilot your playbooks

The pipeline agents have one job each and a short prompt to match. The copilot is the exception: it fields whatever a rep types into Slack, and that work has real procedure behind it. [`skills/`](skills) holds that procedure as three playbooks (call prep, objection handling, pipeline review) in the [Agent Skills](https://agentskills.io/specification) format, which agno loads natively.

Only a skill's name and description sit in the copilot's prompt, about 600 tokens for all three. The body is fetched with a tool call when a request actually matches, so a rep asking "what's the status on Northwind" pays nothing for the call prep playbook, and a rep asking to prep for a call gets the whole thing: the brief format, the question bank, and the rules that stop a guessed funding round reaching a live conversation.

Two constraints make this safe to leave switched on:

- **Skills are read-only.** The spec allows a `scripts/` directory the agent may execute. RevCrew removes that tool, and a skill folder shipping `scripts/` refuses to load with an error telling you to put the logic in `app/toolkits/` instead, where the write guard and the audit trail apply. The copilot reads prospect-authored text; it does not need a way to run code.
- **Skills cannot loosen the rules.** Untrusted-input fencing, the approval gate and never sending on the agent's own initiative live in `app/prompts/copilot.py` and hold on every turn, including the ones where no skill loads. A skill adds procedure; it never gets the last word on what the agent may do.

`objection-handling/references/proof-points.md` ships as an empty template, and the skill is told not to cite it while the `TODO` markers remain — fill it with your own customers and competitive positioning, the same way you replace the rubric. `SKILLS_PATH` points the whole directory somewhere private; `SKILLS_ENABLED=false` turns it off. [`skills/README.md`](skills/README.md) covers writing your own.

## How research works

The dangerous failure of a research agent is a confident brief with nothing behind it. The case that shaped v2 came from an earlier system of mine: a 30-company brief in which 22 companies had no tool evidence and every founder LinkedIn URL was invented, even though the prompt said not to invent sources. So in v2 the rule is enforced in code after the model runs, and the sources are cheap enough that the researcher can afford to look first.

Sources are tiered, cheapest first, and the stack only escalates when a cheaper tier returned nothing or was blocked.

| Tier | Source | Key needed | What it gives |
|---|---|---|---|
| 0 | Greenhouse / Lever / Ashby job boards, Google News RSS, your CRM | none | Open roles by department (the cleanest buying signal there is), recent coverage with the publisher named, prior contact |
| 1 | [Serper](https://serper.dev) → Firecrawl search → DuckDuckGo | optional | Search results with real URLs, ~$0.001 a query when metered |
| 2 | [Firecrawl](https://firecrawl.dev) v2 → [Jina Reader](https://jina.ai/reader) → direct HTTP | optional | Page text with JavaScript rendered and proxies rotated on a block; one page → one schema-validated object for 5 credits |
| 3 | [Stagehand v4](https://docs.stagehand.dev) on [Browserbase](https://browserbase.com) | opt-in | A real browser for JavaScript shells and bot walls: `extract(schema)` instead of a 40 KB blob; single-use sessions, 120 s cap |

Every call, whether it succeeded, returned nothing, was blocked or was refused, is a row in the `evidence` table with its tier, provider, URL, content, cost and terms class. That table is the whitelist the grounding gate checks against, the 48-hour fetch cache, the meter behind the per-account budget (25 calls, 40 credits, 180 browser seconds and $0.50 by default), and the answer to "where did this fact come from" in one query.

After the researcher returns, `app/research/grounding.py` removes every URL the ledger does not hold, both from `sources` and from prose, moves claim lists into `gaps` when nothing was fetched, and adds nothing. The report goes on the approval card as one line: `Evidence: 7 sources verified, 2 unverified links removed, 9 lookups, $0.011`.

LinkedIn, social platforms and review sites are denied before any tier runs and are dropped from search results before the model sees them. The browser tier is off unless enabled and is only reached by escalation. robots.txt is read on direct fetches. The compliance detail, with sources, is in [docs/research-stack.md](docs/research-stack.md).

What one account costs, against list prices checked on 2026-09-08: $0.00 on the keyless path, $0.01 to $0.02 with Firecrawl and Serper, and about $0.02 more when a page needs the browser. The default budget ceiling is ten to twenty times that.

All seven research tools return the same envelope (`ok`, `error`, an error class and a `do_not_retry` flag), and a failure repeated three times with the same arguments inside two minutes is refused before the provider is called again. You can run the research step from a shell without Slack:

```bash
.venv/bin/python scripts/research.py canva.com --company Canva
```

## Architecture

| Component | Model tier | Job |
| --- | --- | --- |
| researcher | main | Account brief from the tiered research stack (Tier 0 signals → search → scrape → browser), grounded against the evidence ledger, outputs `AccountBrief` |
| qualifier | fast | Scores against `app/icp.yaml`, no tools, outputs `LeadScore` |
| outreach_writer | main | Drafts sequences, outputs `SequenceDraft`, holds no send tools |
| crm_scribe | fast | Sole holder of CRM write tools |
| copilot + gtm_desk | main | Slack-facing team that fields questions and call prep, holds the `skills/` playbooks |
| lead_pipeline | workflow | research (inside a budgeted, recorded run), qualify, gate on score, draft, approval. It stops there; the push runs only from a human Approve |
| reply_triage | workflow | classify, log to CRM, alert the rep |

Agents ask `app/models.py` for a role, never a model id, so the whole crew moves between providers with env vars. On Ollama the main tier is qwen3:14b and the fast tier qwen3:4b by default; on Anthropic they are Sonnet and Haiku. Prompts live as versioned files in `app/prompts/`.

The integrations are ports and adapters. `CRMPort`, `OutreachPort` and `ChatPort` are protocols in `app/integrations/ports.py`; `DEMO_MODE` decides whether the registry hands out mocks or the live HubSpot, Instantly and Slack adapters. One partial-live rule: in demo mode with a `SLACK_BOT_TOKEN` set, chat goes live while CRM and outreach stay mocked, which is the right setup for demos in a real workspace.

More detail in [docs/architecture.md](docs/architecture.md).

## Humans stay in control

- Nothing is pushed anywhere until a human clicks Approve. The workflow ends at the gate (`tests/test_pipeline_shape.py` fails if a step is added after it), and the push reads its inputs from the approved row, so there is no path around it ([ADR 0001](docs/adr/0001-postgres-gate-over-agno-hitl.md)).
- Every CRM write goes through a guard: validated, capped per run, deduplicated, and logged to an audit table you can query. The copilot's answer to "what did you do this week" comes from that table, not from memory.
- A second qualified signal for a company with an open deal becomes a note on that deal, not a duplicate deal.
- Suggested replies are drafts. The system never sends a reply on its own.
- Campaigns are always created paused. Activation refuses to run when `ENV=dev` unless forced.

## Setup, step by step

`.venv/bin/python start.py` automates the install and the credential collection below, including a live check of each key as you enter it. This section is the same path by hand, plus the parts a wizard cannot do for you (creating the Slack app, the HubSpot private app, the Instantly webhook).

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

Heavy roles (research, writing, copilot) use `OLLAMA_MODEL_MAIN` (default qwen3:14b) or Sonnet; light roles (scoring, triage, CRM entry) use `OLLAMA_MODEL_FAST` (default qwen3:4b) or Haiku. Set `MODEL_PROVIDER=anthropic` or `ollama` to pin a provider regardless of what else is configured. The defaults are local Ollama model names. On ollama.cloud the hosted models have their own ids (for example `glm-5.2` and `glm-5.3-flash`), so set `OLLAMA_MODEL_MAIN` and `OLLAMA_MODEL_FAST` to two ids from your account. `/health?probe=1` reports `degraded` with the available ids when a configured model is not on the host.

When Ollama is primary and an Anthropic key is also set, reply triage retries once on Anthropic if the local model fails or returns unusable output, and says so in the logs. Small local models occasionally miss structured output; the retry is there so a flaky classification never drops a prospect reply.

### 7. Put it online

The app is one uvicorn process plus Postgres. Any host that runs both works; Railway, Render and Fly all do it with a managed Postgres attached. A `Dockerfile` and `railway.toml` are included; the image carries no browser, because the browser tier runs on Browserbase.

1. Provision Postgres 17 and set `DATABASE_URL`. The schema applies itself on first start.
2. Deploy from the Dockerfile, or with `pip install -r requirements.txt` as the build step and this as the start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

3. Set the environment variables from your `.env`. Set `OS_SECURITY_KEY` to a long random string: it becomes the bearer token protecting the AgentOS API endpoints. Set `TIMEZONE` to yours: every agent sees the date labelled with its weekday in that zone, and the digest fires in it.
4. Update the three Slack URLs (events, actions, commands) and the Instantly webhook to the deployment domain.

### 8. Cut over to live

- `ENV=prod`, which makes missing webhook secrets a hard reject
- `DEMO_MODE=false`
- Send a test lead through `/api/leads`: it should land in HubSpot with a paused campaign in Instantly
- Simulate a reply at `/webhooks/instantly`: it should produce a triage alert and a CRM task
- Open `/health?probe=1`: every configured integration should read `ok`; anything `degraded` is a dead key
- Confirm the digest arrives at the hour set in `DIGEST_HOUR` in `TIMEZONE`
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

## Tests, evals and CI

```bash
.venv/bin/python -m pytest
```

168 tests, about two seconds. The v1 suite covers schemas, discovery, the setup wizard, the ICP rubric, skills safety, signatures, outbox retry and dead-letter, webhook auth, guarded writes, the approval flow end to end and the demo golden path. v2 adds the tool contract and breaker, the domain policy, the grounding gate, the Tier 0 parsers against fixtures shaped like the real APIs, the ledger and router against Postgres with fake providers (waterfall, verified-empty, escalation and its policy gate, budget refusal, cache), and one test that runs the real research step with a scripted model. That model is an agno `Model` subclass that fetches a page and then cites it together with an invented LinkedIn URL; the test asserts that the gate keeps the first, removes the second, and the ledger records both. DB-backed tests skip when Postgres is down.

Evals (`evals/`, built on `agno.eval`) are the regression suite for the model's behaviour. There is one case per failure that has already happened: fabricated URLs, deny-list respect, verified-empty as an answer, and prospect-text injection. They are scored by code that reads the run's tool results, because a judge that only sees input and output cannot know what a tool returned. They cost real calls and run on demand:

```bash
.venv/bin/python scripts/evals.py --list
.venv/bin/python scripts/evals.py --tag researcher
```

CI (`.github/workflows/ci.yml`) runs on every push: ruff, the full test suite against a Postgres service container, the zero-key demo end to end, and a boot check that the app starts and `/health` reports the database. There is no deploy step.

## Observability and operations

- Health. `/health` is the cheap liveness check Railway polls. `/health?probe=1` makes one live, read-only call per configured integration (model, Slack, HubSpot, Instantly, Firecrawl, Serper, Browserbase) and reports one of four states for each: `ok`, `degraded` (reachable but refused, such as a dead key or no credit), `down`, `unconfigured`. Results are not cached between requests.
- Traces. `TRACING_ENABLED=true` turns on agno's OpenTelemetry exporter into your Postgres (`agno_traces`, `agno_spans`), which AgentOS renders as a span tree per run. The [Agno Viz](https://github.com/sanityvsvanity/Agno-viz) bridge is separate: install its package and set the `AGNO_VIZ_*` pair to see the crew in 3D.
- Cost. Research spend is priced per row when it is written and summarised in the daily digest (`Research: 12 accounts, 91 lookups, $0.14`). Per-account detail is in `research_runs`.
- When something is down, [docs/FAILURE_MODES.md](docs/FAILURE_MODES.md) lists what breaks, what survives and where it shows.
- Threat model: [SECURITY.md](SECURITY.md). Rules learned from failures: [docs/LESSONS.md](docs/LESSONS.md). Design decisions: [docs/adr](docs/adr/).

## Who built this

Gagan Dasari. I run [GTMpro](https://gtmpro.com.au), an agentic GTM engineering practice in Melbourne. I build agent teams for revenue work: research, qualification, outreach and conversation, wired into the stack you already run.

gagan@gtmpro.com.au · [LinkedIn](https://www.linkedin.com/in/gaganbuilds) · [GitHub](https://github.com/sanityvsvanity)
