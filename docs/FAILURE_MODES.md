# Failure modes

What happens when a dependency is down. Every row was exercised by a test, by removing a key locally, or
by a probe. The last column is where an operator sees it without reading logs.

| Dependency down | Effect on the crew | Effect on data | Shows as |
|---|---|---|---|
| Postgres | Nothing works. The gate, the outbox, the ledger and the mocks all live there. `/health` returns `degraded` and Railway restarts the process. | Nothing is written. Webhooks return 5xx and Slack and Instantly retry. | `/health` reports `database: down` |
| Slack (dead token or API outage) | Cards and digests fail to post. Approval rows still exist and can be approved later from a re-posted card. | Nothing is lost; the row is written before the post. | `/health?probe=1` reports `slack: degraded` or `down`; the reminder sweep logs it |
| HubSpot | Approve's push fails at the CRM stage. The card gets a Retry button, and stages that already succeeded are skipped on retry. | `push_status=push_failed` with per-stage progress. | The card thread; the digest's push failures |
| Instantly | The push fails at the campaign stage after CRM succeeded. Retry resumes at the campaign. | No duplicate campaign, because progress is recorded per stage. | As above |
| Model provider (dead key) | Agents cannot run. Reply triage falls back to Anthropic when configured, otherwise to the keyword classifier. Demo mode is unaffected. | Triage still writes a note and a task from the fallback. | `/health?probe=1` reports `model: degraded`; workflow run errors |
| Firecrawl (dead key, credits exhausted) | Tier 2 falls back to Jina Reader, then direct HTTP; Tier 1 falls back to DuckDuckGo. Rows record `error` with the HTTP status. | Research continues at the free tier and briefs may be thinner. | Ledger rows; `firecrawl: degraded` |
| Serper | Search falls back to Firecrawl search, then DuckDuckGo. | | `serper: degraded` |
| Browserbase (402 or quota) | The escalation is recorded as `blocked` and the page is reported unreadable with a terminal envelope. Nothing else changes. | | `browserbase: degraded`; `attempts` on the tool result |
| A target website (bot wall, JavaScript shell, robots disallow) | An `empty`, `blocked` or `denied` row. The browser is used only if policy allows. Otherwise the researcher is told to record a gap. | | Ledger; the brief's `gaps` |
| Research budget exhausted | Further calls are refused with `do_not_retry` and the researcher finishes with what it has. | `refused` rows; run `spent` at the cap. | The evidence line on the approval card; the digest's research spend |
| A prospect reply that contains instructions | The reply text is fenced as untrusted before any model sees it. Triage classifies it and does not follow it. | Only a note and a task can be written from triage (source allowlist in the guard). | `write_audit` shows a refusal if a write was attempted |
| Process restart mid-workflow | The in-flight workflow run is lost and the lead event stays `processed`. Re-post the lead. Approvals already opened survive. | No partial external writes, because the workflow ends at the gate. | The `events` table; no card |
| Slack retry or duplicate webhook | Deduplicated by `X-Slack-Retry-Num`. Event context ids hash the payload, so a redelivery deduplicates and a new reply is processed. | Idempotent through the guard. | `write_audit` rows marked `deduped` |
