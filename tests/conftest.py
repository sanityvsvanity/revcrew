"""Shared test helpers. DB-backed tests skip cleanly when Postgres is not running."""

import asyncio

import pytest


def _db_available() -> bool:
    try:
        import psycopg

        from app.config import settings

        conninfo = settings.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(conninfo, connect_timeout=2):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _db_available(),
    reason="Postgres not reachable, run: docker compose up -d",
)


def run_db_test(scenario):
    """Run an async scenario against a clean database, all in one event loop.

    The connection pool is loop-bound, so reset, scenario and close must share
    the same asyncio.run call.
    """

    async def wrapper():
        from app.db import close_pool, get_pool

        pool = await get_pool()
        async with pool.connection() as conn:
            await conn.execute(
                "TRUNCATE mock_crm_objects, mock_campaigns, mock_messages, approvals, events, write_audit "
                "RESTART IDENTITY"
            )
        try:
            await scenario()
        finally:
            await close_pool()

    asyncio.run(wrapper())
