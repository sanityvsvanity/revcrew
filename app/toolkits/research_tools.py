"""Research toolkit: the researcher's tools, each one recorded in the ledger.

Seven tools over the tiered stack in ``app/research``:

| tool                          | tier | provider chain                                     |
|-------------------------------|------|----------------------------------------------------|
| ``hiring_signals``            | 0    | Greenhouse, Lever and Ashby public job boards      |
| ``news_signals``              | 0    | Google News RSS                                    |
| ``web_search``                | 1    | Serper, then Firecrawl search, then DuckDuckGo     |
| ``fetch_page``                | 2, 3 | cache, Firecrawl, Jina Reader, HTTP, then browser  |
| ``extract_page_fields``       | 2    | Firecrawl JSON format (schema in, object out)      |
| ``crm_history``               |      | the CRM port (own data)                            |
| ``lookup_company_enrichment`` |      | demo fixtures                                      |

Every call runs inside a research run (``app/research/context.py``). The pipeline opens one per lead;
ad-hoc copilot research opens one per agno run, keyed by the ``run_context`` agno injects. Every call
is a ledger row, and every failure comes back as a ``{"ok": false, ...}`` envelope with a retry class
(``app/toolkits/_contract.py``).

Compatibility: ``format_results``, ``format_crm_history``, ``resolve_research_provider``,
``strip_html`` and ``url_allowed`` keep their v1 behaviour for callers and tests.
"""

from __future__ import annotations

import ipaddress
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agno.tools import Toolkit

from app.config import settings
from app.research import context as research_context
from app.research import evidence, router
from app.research.providers.scrape import strip_html  # noqa: F401 - re-exported for callers/tests
from app.toolkits._contract import envelope, wrap_tool

logger = logging.getLogger(__name__)

DEMO_DATA_DIR = Path(__file__).resolve().parents[2] / "demo" / "data"
FETCH_MAX_CHARS = settings.RESEARCH_FETCH_MAX_CHARS
SEARCH_MAX_RESULTS = 5

_adhoc_runs: dict[str, research_context.RunContext] = {}
_ADHOC_CAP = 256


# ── provider resolution (v1 API, kept) ──


def resolve_research_provider(
    provider: str | None = None, firecrawl_key: str | None = None
) -> str:
    """Effective scrape tier: ``firecrawl`` when its key is set, else ``basic``."""
    provider = (
        provider if provider is not None else settings.RESEARCH_PROVIDER
    ).lower()
    key = firecrawl_key if firecrawl_key is not None else settings.FIRECRAWL_API_KEY
    if provider == "auto":
        return "firecrawl" if key else "basic"
    if provider == "firecrawl" and not key:
        logger.warning(
            "RESEARCH_PROVIDER=firecrawl but FIRECRAWL_API_KEY is empty, using basic"
        )
        return "basic"
    if provider in ("basic", "firecrawl"):
        return provider
    logger.warning("Unknown RESEARCH_PROVIDER '%s', using basic", provider)
    return "basic"


# ── URL hygiene ──

_PRIVATE_HOSTS = {"localhost", "0.0.0.0", "host.docker.internal"}


def url_allowed(url: str) -> bool:
    """Only public http(s) URLs. Blocks localhost and private/reserved IPs.

    Literal-host hygiene against the model wandering into internal endpoints;
    the deny list in ``app/research/policy.py`` is the terms-of-service layer.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in _PRIVATE_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    )


# ── formatting helpers (pure, tested) ──


def format_results(results: list[dict[str, str]]) -> str:
    """Render search results as numbered entries with their URLs."""
    if not results:
        return "No results found for this query."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. {r.get('title', 'Untitled')}\n   {r.get('url', '')}\n   {r.get('snippet', '')}"
        )
    return "\n".join(lines)


def format_crm_history(
    contact: dict[str, Any] | None, timeline: list[dict[str, Any]]
) -> str:
    """Render CRM lookup results for the researcher."""
    if not contact:
        return "No existing CRM record for this contact. This is a cold prospect."
    props = contact.get("properties", contact)
    lines = [
        "Existing CRM contact found (this prospect is NOT cold):",
        f"  id: {contact.get('id', 'unknown')}",
    ]
    for key in ("email", "firstname", "lastname", "company", "lifecyclestage"):
        if props.get(key):
            lines.append(f"  {key}: {props[key]}")
    if timeline:
        lines.append("Recent activity:")
        for entry in timeline[:5]:
            stamp = entry.get("created_at") or entry.get("timestamp") or ""
            body = str(entry.get("body") or entry.get("type") or entry)[:200]
            lines.append(f"  - {stamp} {body}")
    else:
        lines.append("No timeline activity recorded.")
    return "\n".join(lines)


# ── run resolution ──


async def _ctx(
    run_context: Any = None, *, domain_hint: str = ""
) -> research_context.RunContext:
    """The research run this call belongs to; an ad-hoc run when no pipeline opened one."""
    current = research_context.current()
    if current is not None:
        return current
    key = getattr(run_context, "run_id", None) or "adhoc"
    ctx = _adhoc_runs.get(key)
    if ctx is None:
        if len(_adhoc_runs) >= _ADHOC_CAP:
            _adhoc_runs.pop(next(iter(_adhoc_runs)))
        ctx = await evidence.start_run(domain_hint or "adhoc", trigger="adhoc")
        _adhoc_runs[key] = ctx
    return ctx


def _domain_of(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


# ── tools ──


@wrap_tool(toolkit="research", timeout_s=90)
async def web_search(query: str, run_context=None) -> dict[str, Any]:
    """Search the web. Returns titled results with URLs and snippets.

    Call it several times with different angles (overview, funding, hiring,
    tech stack), not once with a generic query. An empty result set is a real
    answer: record the gap, do not rephrase the same query five times.
    """
    ctx = await _ctx(run_context)
    result = await router.search(ctx, query, limit=SEARCH_MAX_RESULTS)
    if result.get("ok"):
        result["rendered"] = format_results(result.get("results", []))
    return result


@wrap_tool(toolkit="research", timeout_s=180)
async def fetch_page(url: str, run_context=None) -> dict[str, Any]:
    """Fetch a public web page and return its readable text.

    Use on URLs from web_search results or the company's own site. The
    homepage, /about and /careers pages are usually the highest-value reads.
    Pages on the deny list (LinkedIn, social platforms) are refused by policy;
    do not try to reach them another way.
    """
    if not url_allowed(url):
        return envelope(
            "That URL is not fetchable (only public http/https pages).", "terminal"
        )
    ctx = await _ctx(run_context, domain_hint=_domain_of(url))
    return await router.fetch(ctx, url, max_chars=FETCH_MAX_CHARS)


COMPANY_FACTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "what_they_do": {
            "type": "string",
            "description": "One sentence: what the company sells and to whom",
        },
        "products": {"type": "array", "items": {"type": "string"}},
        "customers_named": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Customer names shown on the page, verbatim",
        },
        "integrations_or_stack": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Technologies, integrations or platforms named on the page",
        },
        "headcount_hint": {
            "type": "string",
            "description": "Team size or offices if stated",
        },
        "pricing_model": {
            "type": "string",
            "description": "How they charge, if stated",
        },
        "leaders": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Names with roles exactly as printed on the page",
        },
    },
    "required": ["what_they_do"],
}


@wrap_tool(toolkit="research", timeout_s=120)
async def extract_page_fields(url: str, run_context=None) -> dict[str, Any]:
    """Pull structured company facts from ONE page (what they do, products,
    named customers, stack, leaders). Costs more than fetch_page: use it on the
    single best page, usually the homepage or /about, after a fetch showed it
    is worth it. Needs Firecrawl; without it, read the text from fetch_page.
    """
    if not url_allowed(url):
        return envelope(
            "That URL is not fetchable (only public http/https pages).", "terminal"
        )
    ctx = await _ctx(run_context, domain_hint=_domain_of(url))
    return await router.extract(
        ctx,
        url,
        COMPANY_FACTS_SCHEMA,
        "Extract only facts stated on this page. Leave a field empty rather than guessing.",
    )


@wrap_tool(toolkit="research", timeout_s=90)
async def hiring_signals(domain: str, company: str, run_context=None) -> dict[str, Any]:
    """Open roles from the company's public job board (Greenhouse, Lever or
    Ashby), with counts of sales and engineering roles. Free and exact: a
    company hiring SDRs or RevOps is a buying trigger you can cite by URL.
    Call fetch_page on the careers page first when you can; its links name
    the board. No board found is a valid answer, not a failure.
    """
    ctx = await _ctx(run_context, domain_hint=domain)
    careers_text = ""
    return await router.hiring_signals(ctx, domain, company, careers_text)


@wrap_tool(toolkit="research", timeout_s=60)
async def news_signals(company: str, run_context=None) -> dict[str, Any]:
    """Recent news mentioning the company (Google News). Each item carries the
    publisher and a URL you may cite. Empty means no recent coverage was found.
    """
    ctx = await _ctx(run_context)
    return await router.news_signals(
        ctx, company, region=settings.SERPER_GL.upper() or "AU"
    )


@wrap_tool(toolkit="research", timeout_s=30)
async def crm_history(email: str, run_context=None) -> dict[str, Any]:
    """Look up this prospect in the CRM: existing contact and recent activity.

    Always check this. Prior conversations change the outreach angle entirely.
    """
    from app.integrations.registry import get_crm

    ctx = await _ctx(run_context)
    crm = get_crm()
    contact = await crm.search_contact(email)
    timeline: list[dict[str, Any]] = []
    if contact and contact.get("id"):
        timeline = await crm.get_timeline("contact", str(contact["id"]))
    rendered = format_crm_history(contact, timeline)
    await evidence.record(
        ctx,
        tier=0,
        provider="crm",
        kind="crm",
        status="ok",
        query=email,
        content=rendered,
        tos_class="own_crm",
        meta={"found": bool(contact), "timeline_entries": len(timeline)},
    )
    return {"ok": True, "found": bool(contact), "rendered": rendered}


@wrap_tool(toolkit="research", timeout_s=10)
async def lookup_company_enrichment(domain: str, run_context=None) -> dict[str, Any]:
    """Pre-loaded enrichment data for a company by domain (demo fixtures only)."""
    ctx = await _ctx(run_context, domain_hint=domain)
    enrichment = _load_enrichment(domain)
    await evidence.record(
        ctx,
        tier=0,
        provider="demo",
        kind="enrichment",
        status="ok" if enrichment else "empty",
        query=domain,
        content=json.dumps(enrichment or {})[:4000],
        tos_class="demo_fixture",
    )
    if enrichment:
        return {"ok": True, "found": True, "data": enrichment}
    return {
        "ok": True,
        "found": False,
        "note": f"No enrichment data for domain '{domain}'",
    }


def _load_enrichment(domain: str) -> dict | None:
    """Load enrichment blob from demo/data/companies.json."""
    if not domain:
        return None
    companies_path = DEMO_DATA_DIR / "companies.json"
    if not companies_path.exists():
        return None
    try:
        companies = json.loads(companies_path.read_text())
        clean = (
            domain.lower()
            .replace("https://", "")
            .replace("http://", "")
            .replace("www.", "")
            .rstrip("/")
        )
        for entry in companies:
            entry_domain = (
                entry.get("domain", "")
                .lower()
                .replace("https://", "")
                .replace("http://", "")
                .replace("www.", "")
                .rstrip("/")
            )
            if entry_domain == clean:
                return entry
    except (json.JSONDecodeError, KeyError):
        pass
    return None


class ResearchTools(Toolkit):
    """The researcher's toolkit. One instance is shared by the researcher agent."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name="research_tools",
            tools=[
                web_search,
                fetch_page,
                extract_page_fields,
                hiring_signals,
                news_signals,
                crm_history,
                lookup_company_enrichment,
            ],
            **kwargs,
        )


research_tools = ResearchTools()
