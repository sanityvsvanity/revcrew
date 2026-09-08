# Going live

The condensed checklist. The full walkthrough with context is in the README under "Setup, step by step".

Work through these in order. Each one can go live independently thanks to the port registry: chat can be live while CRM stays mocked.

## Slack

1. Create the app at api.slack.com/apps from `slack/manifest.yaml`, with the three `PLACEHOLDER` URLs pointed at your deployment or tunnel. The server must be running: Slack verifies the events URL on save.
2. Install to your workspace, copy the bot token and signing secret to `.env`
3. Create the channel, invite the bot, put the channel ID in `.env`
4. Verify: `curl -H "Authorization: Bearer $SLACK_BOT_TOKEN" https://slack.com/api/auth.test`
5. Optional: put the Slack user IDs allowed to approve in `APPROVER_SLACK_IDS`, comma-separated. Anyone else clicking Approve gets told to find an approver.

## HubSpot

1. Use a [developer test account](https://developers.hubspot.com/get-started) first, not your production portal
2. Create a private app with scopes: `crm.objects.contacts.read/write`, `crm.objects.companies.read/write`, `crm.objects.deals.read/write`
3. Token goes in `HUBSPOT_PRIVATE_APP_TOKEN`
4. Verify: `curl -H "Authorization: Bearer $TOKEN" "https://api.hubapi.com/crm/v3/objects/contacts?limit=1"`

The adapter dedupes before create: contacts by email, companies by domain. Notes are prefixed `RevCrew:` so you can always tell what the system wrote.

## Instantly

1. API v2 key from your workspace settings into `INSTANTLY_API_KEY`
2. Set a webhook shared secret in `INSTANTLY_WEBHOOK_SECRET` and configure the webhook to send it in the `X-RevCrew-Secret` header, pointed at `/webhooks/instantly`
3. Campaigns are created paused. Activation raises in dev on purpose. Review the campaign in the Instantly UI before you activate anything.

## Cutover checklist

- `ENV=prod` set, which makes missing webhook secrets a hard reject
- `DEMO_MODE=false`
- `OS_SECURITY_KEY` set if the deployment is reachable from anywhere you don't control
- A test lead through `/api/leads` lands in HubSpot and a paused campaign appears in Instantly
- A simulated reply at `/webhooks/instantly` produces a triage alert and a CRM task
- The daily digest arrives at the hour you set in `DIGEST_HOUR` / `DIGEST_TZ`
- No campaign has ever been activated by the system: check `write_audit` and the Instantly UI

## Research providers (all optional)

| Key | Turns on | Without it |
|---|---|---|
| `SERPER_API_KEY` | Tier 1 Google SERP (Serper.dev, prepaid) | Firecrawl search if that key is set, else DuckDuckGo |
| `FIRECRAWL_API_KEY` | Tier 2 scrape with JS rendering, proxies, 48h cache; JSON extraction; Tier 1 fallback search | Jina Reader, then direct HTTP; `extract_page_fields` refuses |
| `JINA_API_KEY` | Higher rate limit on Jina Reader | keyless `r.jina.ai` |
| `BROWSERBASE_API_KEY` + `BROWSERBASE_PROJECT_ID` + `RESEARCH_BROWSER_ENABLED=true` | Tier 3 browser (Stagehand v4) for JS shells and bot walls, escalation only | the page is reported unreadable and the researcher records a gap |
| `STAGEHAND_MODEL` / `STAGEHAND_MODEL_API_KEY` | The model behind Stagehand `extract` | Browserbase Model Gateway, billed to the session |

Verify any of them live: `curl 'http://localhost:8000/health?probe=1'`. Budgets, deny list and cache
TTL are documented in `.env.example` and `docs/research-stack.md`.
