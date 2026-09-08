"""Tier 0: free, deterministic buying signals. No key, no model, no scraping.

Two sources that a B2B researcher trusts more than a search snippet, both served as public JSON or
RSS by the platform itself:

- Open roles from the three applicant-tracking systems most growth-stage companies publish through:
  Greenhouse (``boards-api.greenhouse.io``), Lever (``api.lever.co``) and Ashby
  (``api.ashbyhq.com/posting-api``). A company hiring three SDRs and a RevOps lead is a buying signal,
  and the board token is visible on the company's own careers page.
- Recent news from Google News RSS, scoped to the company name.

Everything here is parsed by code and returned as data. The model decides what it means; it does not
decide what was found.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

from app.research.policy import USER_AGENT

ATS_PATTERNS = {
    "greenhouse": re.compile(
        r"boards?\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9\-_]+)", re.I
    ),
    "lever": re.compile(r"jobs\.lever\.co/([a-z0-9\-_]+)", re.I),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([a-z0-9\-_.]+)", re.I),
}

SALES_WORDS = (
    "sales",
    "account executive",
    "sdr",
    "bdr",
    "revenue",
    "revops",
    "growth",
    "customer success",
    "partnerships",
    "gtm",
    "go-to-market",
)
ENG_WORDS = ("engineer", "developer", "data", "platform", "devops", "sre", "ml", "ai")


def detect_ats(text: str) -> list[tuple[str, str]]:
    """(ats, board_token) pairs referenced in a page's text or links."""
    found: list[tuple[str, str]] = []
    for ats, pattern in ATS_PATTERNS.items():
        for m in pattern.finditer(text or ""):
            token = m.group(1).rstrip(".")
            if (ats, token) not in found:
                found.append((ats, token))
    return found


def guess_tokens(domain: str, company: str) -> list[str]:
    """Board tokens to try when no careers page named one."""
    base = (domain or "").lower().split(":")[0]
    base = base[4:] if base.startswith("www.") else base
    stem = base.split(".")[0] if base else ""
    slug = re.sub(r"[^a-z0-9]+", "", (company or "").lower())
    out: list[str] = []
    for t in (stem, slug, slug.replace("inc", ""), stem.replace("-", "")):
        if t and t not in out:
            out.append(t)
    return out


def _board_url(ats: str, token: str) -> str:
    if ats == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=false"
    if ats == "lever":
        return f"https://api.lever.co/v0/postings/{token}?mode=json"
    return f"https://api.ashbyhq.com/posting-api/job-board/{token}"


def parse_jobs(ats: str, payload: Any) -> list[dict[str, str]]:
    jobs: list[dict[str, str]] = []
    if ats == "greenhouse":
        for j in (payload or {}).get("jobs", []):
            jobs.append(
                {
                    "title": j.get("title", ""),
                    "location": (j.get("location") or {}).get("name", ""),
                    "department": ", ".join(
                        d.get("name", "") for d in j.get("departments", []) or []
                    ),
                    "url": j.get("absolute_url", ""),
                    "posted": j.get("updated_at", "") or j.get("first_published", ""),
                }
            )
    elif ats == "lever":
        for j in payload or []:
            cats = j.get("categories") or {}
            jobs.append(
                {
                    "title": j.get("text", ""),
                    "location": cats.get("location", ""),
                    "department": cats.get("team", "") or cats.get("department", ""),
                    "url": j.get("hostedUrl", ""),
                    "posted": datetime.fromtimestamp(
                        (j.get("createdAt") or 0) / 1000, tz=timezone.utc
                    ).isoformat()
                    if j.get("createdAt")
                    else "",
                }
            )
    elif ats == "ashby":
        for j in (payload or {}).get("jobs", []):
            jobs.append(
                {
                    "title": j.get("title", ""),
                    "location": j.get("location", ""),
                    "department": j.get("department", "") or j.get("team", ""),
                    "url": j.get("jobUrl", ""),
                    "posted": j.get("publishedAt", ""),
                }
            )
    return jobs


def summarize_jobs(jobs: list[dict[str, str]]) -> dict[str, Any]:
    titles = [j.get("title", "").lower() for j in jobs]
    sales = sum(1 for t in titles if any(w in t for w in SALES_WORDS))
    eng = sum(1 for t in titles if any(w in t for w in ENG_WORDS))
    depts: dict[str, int] = {}
    for j in jobs:
        d = j.get("department") or "unspecified"
        depts[d] = depts.get(d, 0) + 1
    return {
        "open_roles": len(jobs),
        "sales_roles": sales,
        "engineering_roles": eng,
        "departments": dict(sorted(depts.items(), key=lambda kv: -kv[1])[:8]),
    }


async def fetch_board(ats: str, token: str) -> dict[str, Any]:
    import httpx

    started = time.monotonic()
    url = _board_url(ats, token)
    try:
        async with httpx.AsyncClient(
            timeout=15, headers={"User-Agent": USER_AGENT}
        ) as client:
            resp = await client.get(url)
        if resp.status_code == 404:
            return {
                "provider": ats,
                "status": "empty",
                "url": url,
                "jobs": [],
                "credits": 0.0,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": "no such board",
            }
        if resp.status_code != 200:
            return {
                "provider": ats,
                "status": "error",
                "url": url,
                "jobs": [],
                "credits": 0.0,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": f"HTTP {resp.status_code}",
            }
        jobs = parse_jobs(ats, resp.json())
        return {
            "provider": ats,
            "status": "ok" if jobs else "empty",
            "url": url,
            "jobs": jobs,
            "credits": 0.0,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "provider": ats,
            "status": "error",
            "url": url,
            "jobs": [],
            "credits": 0.0,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": f"{ats} failed: {exc}",
        }


def parse_news_rss(xml_text: str, limit: int = 8) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    for item in root.iter("item"):
        source = item.find("source")
        items.append(
            {
                "title": (item.findtext("title") or "").strip(),
                "url": (item.findtext("link") or "").strip(),
                "published": (item.findtext("pubDate") or "").strip(),
                "source": (source.text or "").strip() if source is not None else "",
            }
        )
        if len(items) >= limit:
            break
    return items


async def google_news(company: str, region: str = "AU") -> dict[str, Any]:
    import httpx

    started = time.monotonic()
    q = quote_plus(f'"{company}"')
    lang = "en-AU" if region == "AU" else "en-US"
    url = f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={region}&ceid={region}:en"
    try:
        async with httpx.AsyncClient(
            timeout=15, headers={"User-Agent": USER_AGENT}
        ) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return {
                "provider": "google_news",
                "status": "error",
                "url": url,
                "items": [],
                "credits": 0.0,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": f"HTTP {resp.status_code}",
            }
        items = parse_news_rss(resp.text)
        return {
            "provider": "google_news",
            "status": "ok" if items else "empty",
            "url": url,
            "items": items,
            "credits": 0.0,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "provider": "google_news",
            "status": "error",
            "url": url,
            "items": [],
            "credits": 0.0,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": f"news failed: {exc}",
        }
