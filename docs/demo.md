# Demo guide

## Headless (zero credentials)

```bash
docker compose up -d
.venv/bin/python -m demo.run_demo --reset
```

Flags: `--paced` sleeps between beats for screen recording, `--lead 0|1|2` picks the Tier A seed lead, `--reset` clears mock state first.

Inspect what the run wrote:

```bash
docker exec -it revcrew-postgres-1 psql -U revcrew -d revcrew
select type, count(*) from mock_crm_objects group by type;
select run_id, status, resolved_at from approvals;
select id, kind, status, retries from events;
```

## Live Slack demo

1. Create the Slack app from `slack/manifest.yaml`, install it, invite the bot to a channel
2. Put `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_CHANNEL_ID` in `.env` (keep `DEMO_MODE=true`: chat goes live, CRM and outreach stay mocked)
3. Expose the app: `cloudflared tunnel --url http://localhost:8000`, then point the manifest URLs at the tunnel domain
4. Run `scripts/dev.sh`

The sequence that lands:

1. `/demo new-lead` posts the card: lead, score, subject lines, deal, and what approval will write
2. Try View emails and Edit first: the modal is pre-filled and saving updates the card in place
3. Click Approve. The card's buttons are replaced and the push confirmation posts: paused campaign, contact, company, deal, note
4. `/demo reply` runs a canned reply through the outbox. The triage alert lands with the drafted response
5. Mention the bot for call prep (needs a configured model provider)

## Recording script (3 minutes)

Two windows: Slack left, terminal or Agno Viz right.

- 0:00 Cold open on the empty channel. One line on what RevCrew is.
- 0:20 `/demo new-lead`. Read the score and the first subject line out loud.
- 0:50 Point at the Approve, Edit, Reject and View emails buttons. This is the point of the system: agents draft, humans decide.
- 1:10 Approve. Show the push confirmation, then flip to psql or HubSpot to show the records.
- 1:50 `/demo reply`. Show the triage alert and the drafted reply. Note that nothing auto-sends.
- 2:20 Call prep via mention. Read two lines of the brief.
- 2:45 Close on the state summary: every touch logged, every send gated, zero credentials for everything just shown.
