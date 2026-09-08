"""Evidence-grade research: tiered sources, one ledger, a grounding gate.

The package answers one question for every fact the researcher produces:
*which tool call is this from?* It is organised around that:

- ``context``   — the research run the current tool call belongs to.
- ``budget``    — per-account caps on calls, credits, browser seconds and dollars.
- ``policy``    — which domains may be fetched, by which tier, and robots.txt.
- ``evidence``  — the ledger: every fetch, hit or miss, as a Postgres row.
- ``providers`` — Tier 0 signals, Tier 1 search, Tier 2 scrape, Tier 3 browser.
- ``router``    — the waterfall: cheapest source first, escalate on evidence.
- ``grounding`` — the gate: a brief may only cite what the ledger holds.

Design record: docs/research-stack.md and docs/adr/0003-evidence-ledger.md.
"""
