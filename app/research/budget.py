"""Per-account research budget: the cap that makes a pay-per-use stack safe.

Every provider on the stack is metered (Firecrawl credits, Serper queries,
Browserbase browser-seconds plus the model behind Stagehand) and none of them
ships a hard spend cap, so the cap lives here. A tool call that would breach
the budget is refused with a terminal envelope; the model is told to note a gap
rather than try another angle.

Unit prices are the public list prices verified 2026-09-08 (docs/research-stack.md
has the sources). They exist to turn "credits" and "seconds" into one number a
budget can be set in; when a plan changes, change ``UNIT_USD`` and the ledger's
historical rows keep the price they were recorded at.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings

# provider → USD per unit (unit named in the comment)
UNIT_USD: dict[str, float] = {
    "firecrawl": 0.00083,  # per credit, Standard plan ($83 / 100k credits)
    "serper": 0.001,  # per query, entry tier
    "ddg": 0.0,  # keyless, unmetered, best-effort
    "jina": 0.0,  # r.jina.ai keyless tier
    "basic": 0.0,  # direct HTTP fetch
    "browserbase": 0.12 / 3600,  # per browser-second, Developer plan overage
    "stagehand_model": 0.01,  # per extract/act call, cheap-model estimate
    "greenhouse": 0.0,
    "lever": 0.0,
    "ashby": 0.0,
    "google_news": 0.0,
    "crm": 0.0,
    "demo": 0.0,
}


class BudgetExceeded(Exception):
    """Raised by ``charge`` when a call would breach the run's budget."""


@dataclass(frozen=True)
class Budget:
    max_calls: int
    max_credits: float
    max_browser_seconds: float
    max_usd: float

    @classmethod
    def from_settings(cls) -> "Budget":
        return cls(
            max_calls=settings.RESEARCH_MAX_CALLS_PER_ACCOUNT,
            max_credits=settings.RESEARCH_MAX_CREDITS_PER_ACCOUNT,
            max_browser_seconds=settings.RESEARCH_MAX_BROWSER_SECONDS_PER_ACCOUNT,
            max_usd=settings.RESEARCH_MAX_USD_PER_ACCOUNT,
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "max_calls": self.max_calls,
            "max_credits": self.max_credits,
            "max_browser_seconds": self.max_browser_seconds,
            "max_usd": self.max_usd,
        }


def price(provider: str, units: float) -> float:
    return round(UNIT_USD.get(provider, 0.0) * units, 6)


def check(
    ctx,
    budget: Budget,
    *,
    credits: float = 0.0,
    browser_seconds: float = 0.0,
    usd: float = 0.0,
) -> str | None:
    """Return a refusal reason if one more call with these costs would breach the budget."""
    if ctx.calls + 1 > budget.max_calls:
        return f"research budget: {budget.max_calls} tool calls per account reached"
    if ctx.credits + credits > budget.max_credits:
        return f"research budget: {budget.max_credits:g} provider credits per account reached"
    if ctx.browser_seconds + browser_seconds > budget.max_browser_seconds:
        return f"research budget: {budget.max_browser_seconds:g} browser seconds per account reached"
    if ctx.cost_usd + usd > budget.max_usd:
        return f"research budget: ${budget.max_usd:.2f} per account reached"
    return None
