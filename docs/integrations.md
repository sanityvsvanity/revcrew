# Going live

Work through these in order. Each one can go live independently thanks to the port registry: chat can be live while CRM stays mocked.

## Slack

1. Create the app at api.slack.com/apps from `slack/manifest.yaml`
2. Install to your workspace, copy the bot token and signing secret to `.env`
3. Create the channel, invite the bot, put the channel ID in `.env`
4. Point the manifest URLs (events, actions, commands) at your deployment or tunnel
5. Verify: `curl -H "Authorization: Bearer $SLACK_BOT_TOKEN" https://slack.com/api/auth.test`

## HubSpot

1. Use a developer test account first, not your production portal
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
- A test lead through `/api/leads` lands in HubSpot and a paused campaign appears in Instantly
- A simulated reply at `/webhooks/instantly` produces a triage alert and a CRM task
- No campaign has ever been activated by the system: check the audit trail
