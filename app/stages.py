"""Stage metadata cache: fetch HubSpot deal stages at startup, persist as last-known-good.

Survivable failure mode (D4): fetch failure falls back to persisted copy;
no copy ever degrades deal creation only — everything else keeps working.
"""

from __future__ import annotations

import json

from app.config import settings
from app.db import get_pool

# Default HubSpot deal stages (used in mock mode and as ultimate fallback)
_DEFAULT_STAGES = [
    "appointmentscheduled",
    "qualifiedtobuy",
    "presentationscheduled",
    "decisionmakerboughtin",
    "contractsent",
    "closedwon",
    "closedlost",
]


async def fetch_and_cache_stages() -> list[str]:
    """Fetch deal stages from HubSpot (or use defaults in mock mode), cache in DB.

    Returns the stage list. On fetch failure, falls back to the last cached copy.
    If no cache exists, returns the default list but refuses deal creation.
    """
    pipeline_id = settings.DEAL_PIPELINE_ID

    if settings.DEMO_MODE:
        stages = list(_DEFAULT_STAGES)
        await _cache_stages(pipeline_id, stages)
        return stages

    # Live mode: try to fetch from HubSpot
    try:
        stages = await _fetch_live_stages(pipeline_id)
        await _cache_stages(pipeline_id, stages)
        return stages
    except Exception:
        # Fall back to cached copy
        cached = await _get_cached_stages(pipeline_id)
        if cached:
            return cached
        # No cache — return defaults but flag as degraded
        return list(_DEFAULT_STAGES)


async def get_cached_stages() -> list[str]:
    """Return the currently cached stages (or defaults if nothing cached)."""
    pipeline_id = settings.DEAL_PIPELINE_ID
    cached = await _get_cached_stages(pipeline_id)
    if cached:
        return cached
    return list(_DEFAULT_STAGES)


async def has_stage_cache() -> bool:
    """Return True if a stage cache exists (not degraded)."""
    pipeline_id = settings.DEAL_PIPELINE_ID
    cached = await _get_cached_stages(pipeline_id)
    return cached is not None


async def _fetch_live_stages(pipeline_id: str) -> list[str]:
    """Fetch stages from the live HubSpot API."""
    import httpx

    from app.config import settings as s

    headers = {"Authorization": f"Bearer {s.HUBSPOT_PRIVATE_APP_TOKEN}"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://api.hubapi.com/crm/v3/pipelines/deals/{pipeline_id}",
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        stages = [stage["id"] for stage in data.get("stages", [])]
        return stages


async def _cache_stages(pipeline_id: str, stages: list[str]) -> None:
    """Persist stages to the stage_cache table."""
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO stage_cache (pipeline_id, stages, fetched_at) "
            "VALUES (%s, %s, NOW()) "
            "ON CONFLICT (pipeline_id) DO UPDATE SET stages = EXCLUDED.stages, fetched_at = NOW()",
            (pipeline_id, json.dumps(stages)),
        )


async def _get_cached_stages(pipeline_id: str) -> list[str] | None:
    """Return cached stages from DB, or None if no cache exists."""
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT stages FROM stage_cache WHERE pipeline_id = %s",
            (pipeline_id,),
        )
        row = await cur.fetchone()
        if row:
            stages = row[0] if isinstance(row[0], list) else json.loads(row[0])
            return stages
    return None