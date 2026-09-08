# Failure modes — what happens when a dependency is down

Every row was exercised: by a test, by unplugging a key locally, or by a probe. "Shows as" is
where an operator sees it without reading logs.

| Dependency down | Effect on the crew | Effect on data | Shows as |
|---|---|---|---|
| **Postgres** | Nothing works: gate, outbox, ledger and mocks all live there. `/health` returns `degraded`, Railway restarts the process. | Nothing is written; webhooks return 5xx and Slack/Instantly retry. | `/health` → `database: down` |
| **Slack** (token dead / API down) | Cards and digests fail to post. Approvals still exist as rows; a rep can approve later from a re-posted card. | Nothing lost: the approval row precedes the post. | `/health?probe=1` → `slack: degraded/down`; reminder sweep logs |
| **HubSpot** | Approve's push fails at the CRM stage; the card gets a Retry button; already-succeeded stages are skipped on retry. | `push_status=push_failed` with progress. | Card thread, digest "push failures" |
| **Instantly** | Push fails at the campaign stage after CRM succeeded; Retry resumes at the campaign. | No duplicate campaign: progress is recorded per stage. | Same as above |
| **Model provider** (key dead) | Agents cannot run; reply triage falls back to Anthropic when configured, else to the deterministic keyword classifier. Demo mode is unaffected (canned outputs). | Triage still writes a note and task from the fallback. | `/health?probe=1` → `model: degraded`; workflow run errors |
| **Firecrawl** (key dead, credits out) | Tier 2 falls to Jina Reader, then direct HTTP; Tier 1 to DuckDuckGo. Rows record `error` with the HTTP status. | Research continues at the free tier; briefs may be thinner. | ledger rows; `firecrawl: degraded` |
| **Serper** | Search falls to Firecrawl search, then DuckDuckGo. | — | `serper: degraded` |
| **Browserbase** (402 / quota) | Escalation is recorded as `blocked`; the page is reported unreadable with a terminal envelope. Nothing else changes. | — | `browserbase: degraded`; `attempts` on the tool result |
| **A target website** (bot wall, JS shell, robots disallow) | `empty`/`blocked`/`denied` row; browser only if policy allows; otherwise the researcher is told to record a gap. | — | ledger; brief `gaps` |
| **Research budget exhausted** | Further calls refused with `do_not_retry`; the researcher finishes with what it has. | `refused` rows; run `spent` at the cap. | approval card evidence line; digest research spend |
| **Prospect reply carries instructions** | Reply text is fenced as untrusted before any model sees it; triage classifies, never follows. | Only a note and a task can be written from triage (source allowlist in the guard). | `write_audit` shows the refusal if a write was attempted |
| **Process restart mid-workflow** | The in-flight workflow run is lost; the lead event stays `processed`. Re-post the lead. Approvals already opened survive. | No partial external writes: the workflow ends at the gate. | `events` table; no card |
| **Slack retry / duplicate webhook** | Deduped by `X-Slack-Retry-Num`; event context ids hash payload content, so a redelivery dedupes and a new reply lands. | Idempotent through the guard. | `write_audit` `deduped` rows |
