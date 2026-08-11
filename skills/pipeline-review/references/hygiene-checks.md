# Hygiene checks

Run these against `revcrew_activity_summary`. Each one says what to look for,
what it means, and what to recommend. Skip any check the data cannot answer, and
list it under "Not visible" instead of guessing.

---

## 1. Approvals waiting on a human

**Look at** the pending count and how long the oldest has been open.

| Age | Reading | Recommend |
| --- | --- | --- |
| Under `APPROVAL_REMINDER_HOURS` (default 24) | Normal | Nothing |
| Past the reminder threshold | Drifting | Name the accounts; ask who owns them |
| Approaching `APPROVAL_TTL_HOURS` (default 72) | About to expire | Flag by name — expiry loses the drafted work |

A steady pending count with a rising oldest age is the signal that matters: work
is arriving and nobody is clearing it.

---

## 2. Approve / reject / expire mix

**Look at** the ratio across the window.

- Rejections clustered on one reason mean the upstream agent is wrong, not the
  rep. Tone rejections point at the outreach writer's prompt; wrong-contact
  rejections point at the ICP rubric or the intake source.
- A near-100% approve rate is not necessarily good news. It can mean the gate is
  being clicked through rather than read.
- Any expiry is wasted work. One is noise; a pattern is a staffing problem.

**Recommend** the specific upstream change, not "review more carefully".

---

## 3. Blocked and deduplicated writes

**Look at** write counts grouped by decision.

- `blocked` — the guard refused. Repeats on one object type usually mean a cap,
  a validation rule, or a missing field, not misbehaviour.
- `deduped` — a second signal folded into an existing record. Healthy. A high
  rate means the same accounts keep re-entering the funnel, which is an intake
  question worth raising.
- A window with writes attempted and none succeeding is an incident. Say so in
  the first line.

---

## 4. Push failures

**Look at** approved runs with no corresponding CRM and campaign writes.

An approval that never turned into a push is the worst state in the system: a
human said yes and nothing happened. Name every one. The retry button on the
Slack card is the fix, and a human presses it.

---

## 5. Reply handling

**Look at** triage events and the follow-up tasks that came out of them.

Replies classified as `interested` with no follow-up task are the most expensive
leak in the funnel — the buyer raised their hand and nobody came. Check these
before anything about volume.

---

## 6. Throughput, last

**Look at** leads processed, sequences drafted, contacts and deals created.

Volume goes at the bottom. It is the number people ask for and the one that
least often needs a decision.

---

## Review format

```
**Pipeline review — last {N} days**
{One line: the single thing that needs a human today. If nothing does, say that.}

**Waiting on you**
- {Account} — approval pending {X}h, expires in {Y}h
- {Account} — push failed, retry on the card in #gtm-desk

**Leaks**
- {Finding with the number behind it}

**What the crew did**
- {Approvals: X approved, Y rejected, Z pending}
- {CRM: X contacts, Y companies, Z deals, N blocked}
- {Replies: X triaged, Y interested}

**Next**
{One recommended action, addressed to a person.}

**Not visible**
{Checks the audit trail could not answer, if any.}
```
