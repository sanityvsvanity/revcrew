"""Run the full 3-minute demo narrative headlessly in demo mode."""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


async def run_demo(paced: bool = False, lead_index: int = 0, reset: bool = False):
    """Drive the full demo narrative."""
    print("=" * 60)
    print("  RevCrew Demo — AI Revenue Crew in Action")
    print("=" * 60)

    # Load seed data
    leads = json.loads((DATA_DIR / "leads.json").read_text())
    replies = json.loads((DATA_DIR / "replies.json").read_text())

    # Pick a Tier-A lead
    tier_a = [l for l in leads if l["tier"] == "A"]
    if lead_index >= len(tier_a):
        print(f"Lead index {lead_index} out of range (max {len(tier_a)-1})")
        return
    lead = tier_a[lead_index]

    print(f"\n📋 Lead: {lead['first_name']} {lead['last_name']} — {lead['title']} @ {lead['company']}")
    print(f"   Email: {lead['email']} | Domain: {lead['domain']}")
    print(f"   Signals: {lead['signals']}")

    if paced:
        time.sleep(1)

    # Beat 1-2: Research + Qualify
    print("\n--- Beat 1-2: Research & Qualify ---")
    print("🔍 Researcher is gathering intelligence...")
    if paced:
        time.sleep(1)

    # In demo mode, we simulate the pipeline steps
    # The actual agent runs require Anthropic API key
    # For headless demo, we print the expected flow

    print("   ✅ Account brief generated")
    print("   📊 ICP Score: 87/100 — Tier A")
    print("   Reasons: B2B SaaS fit, strong tech signals, VP-level contact, recent funding")

    if paced:
        time.sleep(1)

    # Beat 3: Draft outreach
    print("\n--- Beat 3: Draft Outreach ---")
    print("✍️  Outreach Writer drafting sequence...")
    if paced:
        time.sleep(1)

    print("   Step 1: 'Quick question about {company}' — references recent funding")
    print("   Step 2: 'How {similar_company} scaled outbound' — case study")
    print("   Step 3: 'Worth a 15-min chat?' — soft CTA")

    if paced:
        time.sleep(1)

    # Beat 4: Approval gate
    print("\n--- Beat 4: Approval Gate ---")
    print("🛑 Sequence ready for review — posted to #gtm-desk with Approve/Edit/Reject")
    if paced:
        time.sleep(1)

    # Auto-approve in demo mode
    print("   ✅ Auto-approved (demo mode)")

    if paced:
        time.sleep(1)

    # Beat 5: Push to Instantly + HubSpot
    print("\n--- Beat 5: Push to Instantly + HubSpot ---")
    print("📤 Creating campaign in Instantly...")
    print("   [MOCK instantly] created campaign 'Outreach - Meridian HQ' (3 steps)")
    print("📋 Logging to HubSpot...")
    print("   [MOCK hubspot] upserted contact 'sarah.chen@meridianhq.com'")
    print("   [MOCK hubspot] upserted company 'meridianhq.com'")
    print("   [MOCK hubspot] created deal 'Meridian HQ — Outbound'")

    if paced:
        time.sleep(1)

    # Beat 6: Simulated reply → triage
    print("\n--- Beat 6: Reply Handling ---")
    reply = replies[0]  # interested reply
    print(f"📨 Inbound reply from {reply['from']}:")
    print(f"   \"{reply['body'][:80]}...\"")
    if paced:
        time.sleep(1)

    print("   🏷️  Triage: INTERESTED (high urgency)")
    print("   📋 HubSpot task created: 'Follow up with Sarah Chen — pricing call'")
    print("   💬 Slack alert posted to #gtm-desk with suggested reply draft")

    if paced:
        time.sleep(1)

    # Beat 7: Call prep
    print("\n--- Beat 7: Call Prep ---")
    print("@RevCrew prep me for the Meridian HQ call")
    if paced:
        time.sleep(1)

    print("   📋 Call Brief: Meridian HQ")
    print("   - HR tech platform, 75 employees, Series A $12M")
    print("   - Using Salesforce + Outreach — ripe for AI-powered workflow")
    print("   - Key talking points: automate SDR research, qualify inbound faster")
    print("   - Recent: hired 3 AEs, launched AI performance module")

    print("\n" + "=" * 60)
    print("  ✅ Demo complete — 7 beats, zero credentials, exit 0")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Run RevCrew demo")
    parser.add_argument("--paced", action="store_true", help="Sleep between beats for recording")
    parser.add_argument("--lead", type=int, default=0, help="Lead index (0-2 for Tier A)")
    parser.add_argument("--reset", action="store_true", help="Reset mock state before running")
    args = parser.parse_args()

    asyncio.run(run_demo(paced=args.paced, lead_index=args.lead, reset=args.reset))


if __name__ == "__main__":
    main()