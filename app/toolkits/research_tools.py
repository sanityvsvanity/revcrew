"""Research toolkit: web search, page fetch, CRM history, demo enrichment.

Two provider tiers, resolved the same way as the model factory:
- basic (no keys): DuckDuckGo search plus a direct page fetch
- firecrawl (FIRECRAWL_API_KEY set): Firecrawl search and scrape, which
  survive rate limits and JavaScript-heavy pages far better

RESEARCH_PROVIDER=auto picks Firecrawl when its key is set, basic otherwise.
A Firecrawl failure falls back to basic for that call and logs it; research
never fails silently. Every search result carries its URL so the researcher
can cite real sources.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agno.tools import tool

from app.config import settings

logger = logging.getLogger(__name__)

DEMO_DATA_DIR = Path(__file__).resolve().parents[2] / "demo" / "data"

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"
FETCH_MAX_CHARS = 6000
SEARCH_MAX_RESULTS = 5


# ── provider resolution ──


def resolve_research_provider(
    provider: str | None = None, firecrawl_key: str | None = None
) -> str:
    """Resolve the effective research provider. Mirrors the model factory."""
    provider = (provider if provider is not None else settings.RESEARCH_PROVIDER).lower()
    key = firecrawl_key if firecrawl_key is not None else settings.FIRECRAWL_API_KEY
    if provider == "auto":
        return "firecrawl" if key else "basic"
    if provider == "firecrawl" and not key:
        logger.warning("RESEARCH_PROVIDER=firecrawl but FIRECRAWL_API_KEY is empty, using basic")
        return "basic"
    if provider in ("basic", "firecrawl"):
        return provider
    logger.warning("Unknown RESEARCH_PROVIDER '%s', using basic", provider)
    return "basic"


# ── URL hygiene ──

_PRIVATE_HOSTS = {"localhost", "0.0.0.0", "host.docker.internal"}


def url_allowed(url: str) -> bool:
    """Only public http(s) URLs. Blocks localhost and private/reserved IPs.

    Checks literal hosts, not DNS resolution: this is hygiene against the
    model wandering into internal endpoints, not a hard security boundary.
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
        return True  # a normal hostname
    return not (
        addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    )


# ── formatting helpers (pure, tested) ──


def strip_html(html: str) -> str:
    """Reduce an HTML page to readable text."""
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)</?(p|br|div|li|h[1-6]|tr)[^>]*>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def format_results(results: list[dict[str, str]]) -> str:
    """Render search results as numbered entries with their URLs."""
    if not results:
        return "No results found for this query."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.get('title', 'Untitled')}\n   {r.get('url', '')}\n   {r.get('snippet', '')}")
    return "\n".join(lines)


def format_crm_history(contact: dict[str, Any] | None, timeline: list[dict[str, Any]]) -> str:
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


# ── basic tier ──


def _ddg_search(query: str) -> list[dict[str, str]]:
    from ddgs import DDGS

    with DDGS() as ddgs:
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", "")[:300],
            }
            for r in ddgs.text(query, max_results=SEARCH_MAX_RESULTS)
        ]


async def _basic_search(query: str) -> list[dict[str, str]]:
    return await asyncio.to_thread(_ddg_search, query)


async def _basic_fetch(url: str) -> str:
    import httpx

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=10,
        headers={"User-Agent": "Mozilla/5.0 (compatible; RevCrew-Researcher)"},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return strip_html(resp.text)[:FETCH_MAX_CHARS]


# ── firecrawl tier ──


async def _firecrawl_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{FIRECRAWL_BASE}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {settings.FIRECRAWL_API_KEY}"},
        )
        resp.raise_for_status()
        return resp.json()


async def _firecrawl_search(query: str) -> list[dict[str, str]]:
    data = await _firecrawl_post("/search", {"query": query, "limit": SEARCH_MAX_RESULTS})
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": (r.get("description") or r.get("markdown") or "")[:300],
        }
        for r in data.get("data", [])
    ]


async def _firecrawl_fetch(url: str) -> str:
    data = await _firecrawl_post("/scrape", {"url": url, "formats": ["markdown"]})
    markdown = (data.get("data") or {}).get("markdown", "")
    return markdown[:FETCH_MAX_CHARS] if markdown else "Page fetched but empty."


# ── agent tools ──


@tool(name="web_search")
async def web_search(query: str) -> str:
    """Search the web. Returns numbered results with title, URL and snippet.

    Call this several times with different angles (overview, funding, hiring,
    tech stack), not once with a generic query.
    """
    provider = resolve_research_provider()
    if provider == "firecrawl":
        try:
            return format_results(await _firecrawl_search(query))
        except Exception as exc:
            logger.warning("Firecrawl search failed (%s), falling back to basic", exc)
    try:
        return format_results(await _basic_search(query))
    except Exception as exc:
        logger.warning("Web search failed for %r: %s", query, exc)
        return f"Search failed ({exc.__class__.__name__}). Note this as a research gap."


@tool(name="fetch_page")
async def fetch_page(url: str) -> str:
    """Fetch a web page and return its readable text (truncated).

    Use on URLs from web_search results or the company's own site. The
    homepage and careers page are usually the highest-value fetches.
    """
    if not url_allowed(url):
        return "That URL is not fetchable (only public http/https pages)."
    provider = resolve_research_provider()
    if provider == "firecrawl":
        try:
            return await _firecrawl_fetch(url)
        except Exception as exc:
            logger.warning("Firecrawl scrape failed for %s (%s), falling back", url, exc)
    try:
        return await _basic_fetch(url)
    except Exception as exc:
        logger.warning("Page fetch failed for %s: %s", url, exc)
        return f"Could not fetch {url} ({exc.__class__.__name__}). Note this as a research gap."


@tool(name="crm_history")
async def crm_history(email: str) -> str:
    """Look up this prospect in the CRM: existing contact and recent activity.

    Always check this. Prior conversations change the outreach angle entirely.
    """
    from app.integrations.registry import get_crm

    try:
        crm = get_crm()
        contact = await crm.search_contact(email)
        timeline: list[dict[str, Any]] = []
        if contact and contact.get("id"):
            timeline = await crm.get_timeline("contact", str(contact["id"]))
        return format_crm_history(contact, timeline)
    except Exception as exc:
        logger.warning("CRM history lookup failed for %s: %s", email, exc)
        return f"CRM lookup failed ({exc.__class__.__name__}). Note this as a research gap."


@tool(name="lookup_company_enrichment")
async def lookup_company_enrichment(domain: str) -> str:
    """Look up pre-loaded enrichment data for a company by domain (demo mode)."""
    enrichment = _load_enrichment(domain)
    if enrichment:
        return json.dumps(enrichment, indent=2)
    return f"No enrichment data for domain '{domain}'"


def _load_enrichment(domain: str) -> dict | None:
    """Load enrichment blob from demo/data/companies.json."""
    if not domain:
        return None
    companies_path = DEMO_DATA_DIR / "companies.json"
    if not companies_path.exists():
        return None
    try:
        companies = json.loads(companies_path.read_text())
        clean = domain.lower().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
        for entry in companies:
            entry_domain = entry.get("domain", "").lower().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
            if entry_domain == clean:
                return entry
    except (json.JSONDecodeError, KeyError):
        pass
    return None
