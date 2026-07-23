"""Headless demo: drives the real pipeline infrastructure end to end.

What is real in this run: the Postgres-backed approval gate, the event outbox,
and the mock CRM, outreach and chat adapters (every call writes rows you can
inspect with psql). What is canned: the agent outputs, loaded from
demo/data/canned.json and validated against the schemas in app/schemas.py, so
the run is deterministic and needs zero credentials.

Set DEMO_MODE=false with an Anthropic key to run the real agents instead.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from app.approvals import get_approval_status, resolve_approval
from app.db import close_pool, get_pool
from app.events import dispatch_pending_events, enqueue_event
from demo.pipeline import complete_run, reset_state, start_run

DATA_DIR = Path(__file__).parent / "data"
WIDTH = 60


def banner(text: str):
    print("\n" + "=" * WIDTH)
    print(f"  {text}")
    print("=" * WIDTH)


def beat(n: int, title: str):
    print(f"\n[{n}/7] {title}")
    print("-" * WIDTH)


async def state_summary() -> list[str]:
    """Read back what the run actually wrote. Proof over narration."""
    pool = await get_pool()
    lines = []
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT type, COUNT(*) FROM mock_crm_objects GROUP BY type ORDER BY type"
        )
        crm_counts = ", ".join(f"{t}: {c}" for t, c in await cur.fetchall())
        lines.append(f"mock_crm_objects   {crm_counts or 'empty'}")

        cur = await conn.execute("SELECT COUNT(*), MAX(payload->>'status') FROM mock_campaigns")
        n, status = await cur.fetchone()
        lines.append(f"mock_campaigns     {n} ({status})" if n else "mock_campaigns     empty")

        cur = await conn.execute("SELECT status, COUNT(*) FROM approvals GROUP BY status")
        lines.append("approvals          " + (", ".join(f"{s}: {c}" for s, c in await cur.fetchall()) or "empty"))

        cur = await conn.execute("SELECT status, COUNT(*) FROM events GROUP BY status")
        lines.append("events             " + (", ".join(f"{s}: {c}" for s, c in await cur.fetchall()) or "empty"))

        cur = await conn.execute("SELECT COUNT(*) FROM mock_messages")
        lines.append(f"mock_messages      {(await cur.fetchone())[0]}")
    return lines


async def run_demo(paced: bool = False, lead_index: int = 0, reset: bool = False):
    banner("RevCrew demo: new lead to booked call, human in the loop")

    if reset:
        await reset_state()
        print("Mock state cleared.")

    pause = (lambda s=1: time.sleep(s)) if paced else (lambda s=1: None)

    # Beats 1 to 4: research, qualify, draft, open the approval gate.
    # start_run validates the canned outputs and writes the approvals row.
    run = await start_run(lead_index=lead_index)
    lead, brief, score, draft = run["lead"], run["brief"], run["score"], run["draft"]

    print(f"\nLead: {lead['first_name']} {lead['last_name']}, {lead['title']} at {lead['company']}")
    print(f"Email: {lead['email']} | Domain: {lead['domain']}")
    print(f"Signals: {lead['signals']}")
    pause()

    beat(1, "Research: account brief")
    print(f"  {brief.snapshot}")
    print(f"  Tech signals:    {', '.join(brief.tech_signals)}")
    print(f"  Buying triggers: {', '.join(brief.buying_triggers)}")
    pause()

    beat(2, "Qualify: ICP score")
    print(f"  Score {score.score}/100, Tier {score.tier}")
    print(f"  Reasons: {'; '.join(score.reasons)}")
    pause()

    beat(3, "Draft outreach sequence")
    for i, step in enumerate(draft.steps, 1):
        print(f"  Step {i} (+{step.wait_days}d): {step.subject}")
    print(f"  Notes: {draft.personalization_notes}")
    pause()

    beat(4, "Approval gate (Postgres-backed)")
    run_id = run["run_id"]
    status = await get_approval_status(run_id)
    print(f"\n  approvals row {run_id}: {status['status']}")
    pause()
    resolution = await resolve_approval(run_id, "approved")
    print(f"  approvals row {run_id}: {resolution['status']} (auto-approved in demo mode)")
    pause()

    # Beat 5: push through the real ports. Rows land in mock_campaigns and
    # mock_crm_objects. Campaigns are always created paused.
    beat(5, "Push to outreach and CRM")
    await complete_run(run_id)
    pause()

    # Beat 6: a reply arrives through the event outbox and gets triaged.
    # The event row is real, the dispatch is real, the classifier is the
    # deterministic demo path in app/triage.py.
    beat(6, "Inbound reply through the event outbox")
    replies = json.loads((DATA_DIR / "replies.json").read_text())
    reply = replies[0]
    print(f"  Reply from {reply['from']}: \"{reply['body'][:70]}...\"")
    event_id = await enqueue_event("instantly", "reply_received", reply)
    print(f"  events row {event_id}: pending")
    dispatched = await dispatch_pending_events()
    print(f"  dispatched {dispatched} event(s): triage, CRM task, chat alert above")
    pause()

    # Beat 7: call prep brief. Canned in demo mode; the copilot agent serves
    # this live when an Anthropic key is configured.
    beat(7, "Call prep")
    print(f"  @RevCrew prep me for the {lead['company']} call")
    for line in run["call_brief"]:
        print(f"  - {line}")

    banner("Demo complete")
    print("\nState written to Postgres by this run:")
    for line in await state_summary():
        print(f"  {line}")
    print("\nZero credentials required. Inspect with:")
    print("  docker exec -it revcrew-postgres-1 psql -U revcrew -d revcrew")
    await close_pool()


def main():
    parser = argparse.ArgumentParser(description="Run the RevCrew demo")
    parser.add_argument("--paced", action="store_true", help="Sleep between beats for recording")
    parser.add_argument("--lead", type=int, default=0, help="Tier A lead index (0-2)")
    parser.add_argument("--reset", action="store_true", help="Clear mock state before running")
    args = parser.parse_args()

    asyncio.run(run_demo(paced=args.paced, lead_index=args.lead, reset=args.reset))


if __name__ == "__main__":
    main()
