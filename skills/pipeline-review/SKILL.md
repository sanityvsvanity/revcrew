---
name: pipeline-review
description: Review pipeline and approval health — what is waiting on a human, what has gone stale, what the crew actually did, and where the funnel is leaking. Use when someone asks what is stuck, what happened this week, how the pipeline looks, or asks for a Monday review.
---

# Pipeline review

Answer from the audit trail, not from memory. Every number in a review comes out
of a tool call, and anything a tool cannot show is listed as not visible rather
than estimated.

## Procedure

1. **Fix the window.** Default to seven days. "This week", "since Monday" and
   "this month" all map to a day count — say which one you used.
2. **Pull the record.** `revcrew_activity_summary(days=N)` returns approval
   counts by status, CRM write counts by decision and object type, and recent
   activity rows. This is the source of truth for what the crew did.
3. **Run the checks** in `references/hygiene-checks.md` against what came back.
4. **Write the review** in the format at the bottom of that file: what happened,
   what needs a human, what is leaking, and one recommended next action.
5. **Stop there.** A review recommends; it does not act.

## Rules

- **Numbers come from tools.** If the summary does not contain it, you do not
  know it. "Not visible from the audit trail" is a complete and acceptable
  answer to a question about something the system does not record.
- **Pending is not idle.** An approval waiting two hours is the system working
  as designed. Only call something stuck once it passes the thresholds in the
  checks reference, which come from `APPROVAL_REMINDER_HOURS` and
  `APPROVAL_TTL_HOURS`.
- **Blocked writes are a finding, not a failure.** The guard refusing writes is
  the guard doing its job. Report the pattern — repeated blocks on one object
  type usually mean a misconfiguration, not an attack.
- **Review never acts.** Do not approve, reject, retry a push, write to the CRM,
  or activate a campaign. Every one of those is a human action, and a review that
  quietly performs one destroys the audit trail's meaning.
- **Lead with the exception.** A rep skims this. The first line says what needs
  them today; the counts go underneath.
