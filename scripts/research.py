#!/usr/bin/env python
"""Research one account from the command line and print the ledger.

    .venv/bin/python scripts/research.py acme.example --company "Acme" --email jo@acme.example

Runs the real research step (researcher agent → grounding gate) against the
configured providers and model, then prints the grounded brief, the grounding
report, and every evidence row. The same code path the pipeline uses; nothing
is pushed anywhere. Needs a model provider and Postgres; every other key is optional.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def _main(args: argparse.Namespace) -> int:
    from dotenv import load_dotenv

    load_dotenv()

    from agno.workflow.types import StepInput

    from agents.pipelines import _research_step
    from app.db import close_pool, get_pool
    from app.research.evidence import run_summary

    lead = {
        "first_name": args.first_name,
        "last_name": args.last_name,
        "title": args.title,
        "company": args.company or args.domain.split(".")[0].title(),
        "domain": args.domain,
        "email": args.email or f"hello@{args.domain}",
        "signals": args.signals,
    }
    try:
        out = await _research_step(StepInput(input=json.dumps(lead)))
        brief = out.content
        research = brief.pop("_research", {})
        print("\n=== Grounded brief ===")
        print(json.dumps(brief, indent=2))
        print("\n=== Grounding ===")
        print(research.get("grounding", ""))
        print(f"spent: {research.get('spent')}")

        summary = await run_summary(research["run_id"])
        pool = await get_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT tier, provider, kind, status, COALESCE(NULLIF(url,''), query), credits::float, "
                "cost_usd::float, latency_ms, left(error, 70) FROM evidence WHERE run_id = %s ORDER BY id",
                (research["run_id"],),
            )
            rows = await cur.fetchall()
        print(f"\n=== Ledger {research['run_id']} ({summary['status']}) ===")
        print(
            f"{'tier':4} {'provider':12} {'kind':9} {'status':8} {'cr':>5} {'usd':>8} {'ms':>6}  target / error"
        )
        for tier, provider, kind, status, target, credits, usd, ms, err in rows:
            print(
                f"{tier:<4} {provider:12} {kind:9} {status:8} {credits:5.1f} {usd:8.4f} {ms:6}  {target[:60]}"
                + (f"  ← {err}" if err else "")
            )
        return 0
    finally:
        await close_pool()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("domain")
    ap.add_argument("--company", default="")
    ap.add_argument("--email", default="")
    ap.add_argument("--first-name", default="")
    ap.add_argument("--last-name", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--signals", default="")
    return asyncio.run(_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
