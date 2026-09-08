# Security

## Reporting

Email gagan@gtmpro.com.au with the details. There is no bounty program.

## Threat model

RevCrew reads text written by prospects, holds CRM and outreach credentials, and can write to a CRM and
create paused campaigns. The controls, by the threat each addresses:

| Threat | Control | Where |
|---|---|---|
| Prompt injection through prospect replies or CRM notes | Text is wrapped in `<crm_data source="prospect_correspondence">` before any model sees it. Prompts instruct the model to classify it and not to follow it. Skills cannot relax this. | `app/toolkits/crm_tools.py::_fence_crm_data`, `app/prompts/*`, `tests/test_skills.py` |
| Prompt injection through scraped pages | Page text reaches only the researcher, which holds no write tools, and its output passes the grounding gate. Firecrawl's `check_prompt_injection` is available per extraction. | `agents/researcher.py`, `app/research/grounding.py` |
| An agent writing to the CRM on its own | Every CRM write passes through `GuardedCRM`: a context is required, operations are allowlisted per source, writes are capped per context, deduplicated by an idempotency key, and recorded in an audit row. There is no unguarded handle. | `app/guard.py`, `app/integrations/registry.py` |
| Outreach sent without a human | Campaigns are created paused. Activation refuses in `ENV=dev` unless forced. The workflow ends at the approval gate, and the push runs only from a verified Slack click by an allowed approver. | `app/push.py`, `app/webhooks/slack.py`, ADR 0001 |
| Forged webhooks | Slack v0 HMAC with a five minute window and retry deduplication. Instantly uses a shared-secret header with a constant-time compare. A missing secret rejects the request except in a pure-mock dev demo. | `app/webhooks/signature.py`, `tests/test_signature.py` |
| SSRF through research URLs | Only public http(s) URLs are fetched. Private, loopback and link-local hosts and `.internal` or `.local` names are refused before any fetch. | `app/toolkits/research_tools.py::url_allowed` |
| Scraping platforms whose terms forbid it | A deny list applied before any tier and to search results, an opt-in browser tier, robots.txt on direct fetches, and a `tos_class` on every row. | `app/research/policy.py` |
| Runaway spend on metered providers | A per-account budget on calls, credits, browser seconds and dollars is checked before each call. Browser sessions are single use with a hard timeout. | `app/research/budget.py`, `app/research/providers/browser.py` |
| Skills executing code | The `get_skill_script` tool is removed, and a skill folder that contains `scripts/` refuses to load. | `app/skills.py` |
| Credentials in logs or the audit table | Secrets live only in the environment. `gitleaks` runs in pre-commit. Tool envelopes do not echo credential-named arguments. | `.pre-commit-config.yaml`, `.gitignore` |
| Unauthenticated AgentOS endpoints | `OS_SECURITY_KEY` enables bearer auth on the AgentOS API. The app warns at boot when it is unset in live mode. | `main.py` |
| Personal data retention | Evidence rows, audit rows and resolved approvals are purged after `RETENTION_DAYS` (default 90). | `agents/housekeeping.py` |

## Out of scope

- Multi-tenant isolation. One workspace, one CRM, one operator.
- Encryption of Postgres at rest. Use the managed Postgres your host provides.
- Rate limiting the public intake route. Put it behind an API gateway.
