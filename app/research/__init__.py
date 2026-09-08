"""Research package: tiered sources, one ledger, a grounding gate.

For every fact the researcher produces, the package can answer which tool call it came from.
It is organised around that:

- ``context``    the research run the current tool call belongs to
- ``budget``     per-account caps on calls, credits, browser seconds and dollars
- ``policy``     which domains may be fetched, by which tier, and robots.txt
- ``evidence``   the ledger: every fetch, hit or miss, as a Postgres row
- ``providers``  Tier 0 signals, Tier 1 search, Tier 2 scrape, Tier 3 browser
- ``router``     the waterfall: cheapest source first, escalate on an empty or blocked result
- ``grounding``  the gate: a brief may only cite what the ledger holds

Design notes: docs/research-stack.md and docs/adr/0003-evidence-ledger.md.
"""
