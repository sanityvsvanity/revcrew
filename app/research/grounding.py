"""The grounding gate: a brief may only cite what the ledger holds.

The failure this exists for was measured, not imagined: a research trace on the
predecessor system (2026-08-11) produced a 30-company brief in which 22 rows had
no tool evidence and every founder LinkedIn URL was invented — plausible,
well-formatted, and false. No prompt fixed it, because the model was not lying
so much as completing a pattern. The check has to run *after* generation, in
code, against the record of what the tools actually returned.

Rules, in the order they apply:

1. Every URL in ``sources`` must normalise to a URL that a successful tool
   call returned for this run. Others are removed and counted.
2. URLs embedded in prose fields are treated the same way: an unverifiable
   link is replaced with ``[unverified link removed]``. The sentence stays —
   the gate can prove a URL was not returned by a tool; it cannot prove a
   sentence false.
3. If the run gathered **no** successful evidence at all, the lists that carry
   claims (``tech_signals``, ``buying_triggers``, ``key_people``) are moved into
   ``gaps`` as "unverified": with nothing fetched, nothing in them can be
   grounded, and an empty field is correct where a guessed one is harmful.
4. The gate only ever removes or moves; it never writes a new fact. Its report
   is stored on the research run and shown on the approval card, so a rep sees
   "7 sources · 2 unverified links removed" next to the score.

The same function guards ad-hoc copilot research and the eval suite, so the
one place the rule lives is the one place a test pins it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.research.evidence import normalize_url
from app.schemas import AccountBrief

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
REMOVED = "[unverified link removed]"
CLAIM_FIELDS = ("tech_signals", "buying_triggers", "key_people")


@dataclass
class GroundingReport:
    sources_kept: int = 0
    sources_removed: list[str] = field(default_factory=list)
    inline_links_removed: int = 0
    claims_moved_to_gaps: int = 0
    evidence_records: int = 0

    @property
    def clean(self) -> bool:
        return (
            not self.sources_removed
            and not self.inline_links_removed
            and not self.claims_moved_to_gaps
        )

    def as_dict(self) -> dict:
        return {
            "sources_kept": self.sources_kept,
            "sources_removed": self.sources_removed,
            "inline_links_removed": self.inline_links_removed,
            "claims_moved_to_gaps": self.claims_moved_to_gaps,
            "evidence_records": self.evidence_records,
            "clean": self.clean,
        }

    def line(self) -> str:
        """One line for a Slack card: what the rep needs to weigh the brief."""
        parts = [
            f"{self.sources_kept} source{'s' if self.sources_kept != 1 else ''} verified"
        ]
        removed = len(self.sources_removed) + self.inline_links_removed
        if removed:
            parts.append(
                f"{removed} unverified link{'s' if removed != 1 else ''} removed"
            )
        if self.claims_moved_to_gaps:
            parts.append(
                f"{self.claims_moved_to_gaps} unevidenced claim(s) moved to gaps"
            )
        if self.evidence_records == 0:
            parts.append("no evidence gathered")
        return " · ".join(parts)


def _allowed(url: str, allowed: set[str]) -> bool:
    return normalize_url(url) in allowed


def _scrub_text(text: str, allowed: set[str], report: GroundingReport) -> str:
    def repl(m: re.Match) -> str:
        if _allowed(m.group(0), allowed):
            return m.group(0)
        report.inline_links_removed += 1
        return REMOVED

    return _URL_RE.sub(repl, text or "")


def ground(
    brief: AccountBrief, allowed_urls: set[str], *, evidence_records: int
) -> tuple[AccountBrief, GroundingReport]:
    """Return a grounded copy of ``brief`` and the report of what changed."""
    report = GroundingReport(evidence_records=evidence_records)
    allowed = {normalize_url(u) for u in allowed_urls}
    data = brief.model_dump()

    kept: list[str] = []
    seen: set[str] = set()
    for url in data.get("sources", []) or []:
        if _allowed(url, allowed):
            norm = normalize_url(url)
            if norm not in seen:
                seen.add(norm)
                kept.append(url)
        else:
            report.sources_removed.append(url)
    data["sources"] = kept
    report.sources_kept = len(kept)

    data["snapshot"] = _scrub_text(data.get("snapshot", ""), allowed, report)
    for name in ("talking_points", *CLAIM_FIELDS):
        data[name] = [
            _scrub_text(item, allowed, report) for item in data.get(name, []) or []
        ]

    gaps = list(data.get("gaps", []) or [])
    if evidence_records == 0:
        for name in CLAIM_FIELDS:
            items = data.get(name, []) or []
            if items:
                report.claims_moved_to_gaps += len(items)
                gaps.append(
                    f"unverified (no evidence gathered): {name} = {'; '.join(items)[:300]}"
                )
                data[name] = []
    if report.sources_removed:
        gaps.append(
            f"{len(report.sources_removed)} cited URL(s) not returned by any tool were removed"
        )
    if report.inline_links_removed:
        gaps.append(
            f"{report.inline_links_removed} inline link(s) not returned by any tool were removed"
        )
    data["gaps"] = gaps

    return AccountBrief.model_validate(data), report
