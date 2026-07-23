"""Research toolkit: Agno tools for web search and demo-data enrichment."""

from __future__ import annotations

import json
from pathlib import Path

from agno.tools import tool

DEMO_DATA_DIR = Path(__file__).resolve().parents[2] / "demo" / "data"


@tool(name="web_search_company")
async def web_search_company(company_name: str, domain: str = "") -> str:
    """Search the web for information about a company. Returns a summary of findings."""
    # In demo mode, check enrichment data first
    enrichment = _load_enrichment(domain)
    if enrichment:
        return json.dumps(enrichment, indent=2)

    # Fallback: use ddgs for live search
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(f"{company_name} company overview", max_results=3))
            if results:
                snippets = [r.get("body", "")[:300] for r in results]
                return "\n\n".join(snippets)
    except Exception:
        pass

    return f"No enrichment data found for {company_name}. Try providing a domain for demo lookup."


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
        # Normalize: strip protocol and www
        clean = domain.lower().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
        for entry in companies:
            entry_domain = entry.get("domain", "").lower().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
            if entry_domain == clean:
                return entry
    except (json.JSONDecodeError, KeyError):
        pass
    return None