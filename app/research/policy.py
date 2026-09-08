"""Domain policy: what the stack may fetch, from where, and how.

Three decisions, all made in code before any provider is called:

1. Denied domains are never fetched by any tier. LinkedIn heads the list. Its terms prohibit
   automated collection and it enforces them: hiQ v. LinkedIn ended with an injunction in 2022, and
   Proxycurl was shut down under one in July 2026. Social platforms and review sites with the same
   terms follow. ``RESEARCH_DENY_DOMAINS`` extends the list; nothing removes the defaults.
2. The browser tier is opt-in. A headless browser is the most expensive and the most intrusive tool
   on the stack, so it runs only when ``RESEARCH_BROWSER_ENABLED`` is true, only on a domain that is
   not denied, and only after a cheaper tier returned a JavaScript shell or was blocked.
3. robots.txt is honoured on direct fetches. Firecrawl honours it on its side; the basic ``httpx`` tier
   checks it here, cached per host. A robots fetch that fails is logged and treated as allow, which
   is the usual convention.

Every fetch also carries a ``tos_class`` into the ledger so a reviewer can see, per row, what kind of
source it was: ``public_web``, ``public_api``, ``own_crm`` or ``demo_fixture``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from urllib import robotparser
from urllib.parse import urlparse

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_DENY: frozenset[str] = frozenset(
    {
        "linkedin.com",
        "facebook.com",
        "instagram.com",
        "x.com",
        "twitter.com",
        "tiktok.com",
        "glassdoor.com",
        "glassdoor.com.au",
        "indeed.com",
        "seek.com.au",
    }
)

USER_AGENT = "RevCrewResearcher/2.0 (+https://github.com/sanityvsvanity/revcrew)"

_robots_cache: dict[str, tuple[float, robotparser.RobotFileParser | None]] = {}
_ROBOTS_TTL_S = 600.0


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def registrable(host: str) -> str:
    """Collapse ``www.au.linkedin.com`` to ``linkedin.com`` for policy matching.

    Good enough for a deny list of well-known platforms; not a public-suffix
    implementation, and it does not need to be, because a false positive here
    only means one more domain is denied.
    """
    parts = host.split(".")
    if (
        len(parts) >= 3
        and parts[-2] in {"com", "co", "org", "net", "gov", "edu"}
        and len(parts[-1]) == 2
    ):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def deny_list() -> frozenset[str]:
    extra = {
        d.strip().lower()
        for d in settings.RESEARCH_DENY_DOMAINS.split(",")
        if d.strip()
    }
    return DEFAULT_DENY | frozenset(extra)


def is_denied(url_or_host: str) -> bool:
    host = host_of(url_or_host) if "://" in url_or_host else url_or_host.lower()
    if not host:
        return False
    reg = registrable(host)
    return reg in deny_list() or host in deny_list()


def deny_reason(url: str) -> str:
    return (
        f"{registrable(host_of(url))} is on the research deny list (terms prohibit automated "
        "collection). Use what the CRM or public sources say and record a gap."
    )


def browser_allowed(url: str) -> tuple[bool, str]:
    """May the browser tier open this URL? Returns (allowed, reason)."""
    if not settings.RESEARCH_BROWSER_ENABLED:
        return False, "browser tier is disabled (RESEARCH_BROWSER_ENABLED=false)"
    if not (settings.BROWSERBASE_API_KEY and settings.BROWSERBASE_PROJECT_ID):
        return (
            False,
            "browser tier is not configured (BROWSERBASE_API_KEY / BROWSERBASE_PROJECT_ID)",
        )
    if is_denied(url):
        return False, deny_reason(url)
    return True, ""


def _fetch_robots(host: str, scheme: str) -> robotparser.RobotFileParser | None:
    import httpx

    rp = robotparser.RobotFileParser()
    try:
        resp = httpx.get(
            f"{scheme}://{host}/robots.txt",
            timeout=5,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
    except Exception as exc:  # network failure: allow, but say so
        logger.info("robots: %s unreachable (%s); treating as allow", host, exc)
        return None
    if resp.status_code >= 400:
        return None  # no robots file: allow
    rp.parse(resp.text.splitlines())
    return rp


async def robots_allows(url: str) -> bool:
    """True unless the host's robots.txt disallows our user agent for this path."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    now = time.monotonic()
    cached = _robots_cache.get(host)
    if cached and now - cached[0] < _ROBOTS_TTL_S:
        rp = cached[1]
    else:
        rp = await asyncio.to_thread(_fetch_robots, host, parsed.scheme or "https")
        _robots_cache[host] = (now, rp)
    if rp is None:
        return True
    return rp.can_fetch(USER_AGENT, url) and rp.can_fetch("*", url)


def reset_robots_cache() -> None:
    _robots_cache.clear()
