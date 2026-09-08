# Security

## Reporting

Email gagan@gtmpro.com.au with the details. There is no bounty; there is a prompt reply.

## Threat model, in one page

RevCrew reads prospect-authored text, holds CRM and outreach credentials, and can write to a CRM
and create (paused) campaigns. The controls, by what they protect against:

| Threat | Control | Where |
|---|---|---|
| Prompt injection via prospect replies or CRM notes | Text is wrapped in `<crm_data source="prospect_correspondence">` before any model sees it; prompts say classify, never follow; skills cannot relax this. | `app/toolkits/crm_tools.py::_fence_crm_data`, `app/prompts/*`, `tests/test_skills.py` |
| Prompt injection via scraped web pages | Page text reaches only the researcher, which holds no write tools; its output passes the grounding gate; Firecrawl's `check_prompt_injection` is available per extract. | `agents/researcher.py`, `app/research/grounding.py` |
| An agent writing to the CRM on its own initiative | Every CRM write passes `GuardedCRM`: context required, per-source operation allowlist, per-context cap, idempotency, audit row. No unguarded handle exists. | `app/guard.py`, `app/integrations/registry.py` |
| Outreach sent without a human | Campaigns are created paused; activation refuses in `ENV=dev` unless forced; the workflow ends at the approval gate; the push runs only from a verified Slack click by an allowed approver. | `app/push.py`, `app/webhooks/slack.py`, ADR 0001 |
| Forged webhooks | Slack v0 HMAC with a 5-minute window and retry dedup; Instantly shared-secret header, constant-time compare; a missing secret rejects except in a pure-mock dev demo. | `app/webhooks/signature.py`, `tests/test_signature.py` |
| SSRF through research URLs | Only public http(s); literal private/loopback/link-local hosts and `.internal`/`.local` refused before any fetch. | `app/toolkits/research_tools.py::url_allowed` |
| Scraping platforms whose terms forbid it | Deny list applied before any tier and to search results; browser tier opt-in; robots.txt on direct fetches; every row carries a `tos_class`. | `app/research/policy.py` |
| Runaway spend on metered providers | Per-account budget on calls, credits, browser seconds and dollars, checked before the call; single-use browser sessions with a hard timeout. | `app/research/budget.py`, `app/research/providers/browser.py` |
| Skills executing code | The `get_skill_script` tool is removed; a skill folder containing `scripts/` refuses to load. | `app/skills.py` |
| Credentials in logs or the audit table | Secrets live in env only; `gitleaks` runs in pre-commit; tool envelopes never echo credential-named arguments. | `.pre-commit-config.yaml`, `.gitignore` |
| Unauthenticated AgentOS endpoints | `OS_SECURITY_KEY` enables bearer auth on the AgentOS API; the app warns at boot when it is unset in live mode. | `main.py` |
| Personal data retention | Evidence, audit and resolved approvals are purged after `RETENTION_DAYS` (default 90). | `agents/housekeeping.py` |

## What is deliberately out of scope

- Multi-tenant isolation. One workspace, one CRM, one operator.
- Encrypting Postgres at rest. Use your host's managed Postgres encryption.
- Rate limiting the public intake route. Put it behind your API gateway.
