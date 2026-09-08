"""The research run a tool call belongs to.

A run is one account's worth of research: one budget, one ledger slice, one
grounding report. The pipeline starts a run before it calls the researcher and
finishes it after the grounding gate. Ad-hoc research from the Slack copilot
has no pipeline around it, so the tools start an ``adhoc`` run on first use.

The run id travels in a ``contextvars.ContextVar``: the pipeline step sets it in
the same coroutine that awaits the agent, and agno awaits tool calls inside
that coroutine, so every tool sees it without threading an argument through
the model.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field

_current: contextvars.ContextVar["RunContext | None"] = contextvars.ContextVar(
    "research_run", default=None
)


@dataclass
class RunContext:
    run_id: str
    domain: str
    trigger: str = "pipeline"
    # In-process mirror of what the ledger has recorded for this run. The ledger
    # row is the truth; this avoids a query per tool call for budget checks.
    calls: int = 0
    credits: float = 0.0
    cost_usd: float = 0.0
    browser_seconds: float = 0.0
    urls: set[str] = field(default_factory=set)
    ok_records: int = 0


def current() -> RunContext | None:
    return _current.get()


def activate(ctx: RunContext) -> contextvars.Token:
    return _current.set(ctx)


def deactivate(token: contextvars.Token) -> None:
    _current.reset(token)
