"""Database connection pool and schema initialization.

One pool per process — and per event loop. psycopg's async pool is bound to
the loop that opened it; a pool created under one ``asyncio.run`` and reused
under another raises ``PoolClosed`` (or hangs) on first use. ``get_pool``
therefore remembers which loop opened the pool and rebuilds it when the
caller's loop differs or the pool was closed behind our back. In production
there is exactly one loop, so this costs a comparison; in tests and scripts
it is the difference between green and order-dependent failures.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from psycopg_pool import AsyncConnectionPool

from app.config import settings

_pool: AsyncConnectionPool | None = None
_pool_loop: asyncio.AbstractEventLoop | None = None
_schema_path = Path(__file__).parent / "schema.sql"


def _conninfo() -> str:
    # Accept both plain libpq URLs and SQLAlchemy-style postgresql+psycopg://
    return settings.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")


def _stale(loop: asyncio.AbstractEventLoop) -> bool:
    if _pool is None:
        return True
    if getattr(_pool, "closed", False):
        return True
    return _pool_loop is not loop or _pool_loop.is_closed()


async def get_pool() -> AsyncConnectionPool:
    global _pool, _pool_loop
    loop = asyncio.get_running_loop()
    if _stale(loop):
        old = _pool
        _pool = None
        if old is not None and not getattr(old, "closed", False) and _pool_loop is loop:
            try:
                await old.close()
            except Exception:  # noqa: BLE001 - a dead pool cannot block a new one
                pass
        pool = AsyncConnectionPool(
            conninfo=_conninfo(), min_size=1, max_size=5, open=False
        )
        await pool.open()
        await _init_schema(pool)
        _pool, _pool_loop = pool, loop
    return _pool


async def _init_schema(pool: AsyncConnectionPool) -> None:
    """Execute schema.sql idempotently."""
    if not _schema_path.exists():
        return
    sql = _schema_path.read_text()
    async with pool.connection() as conn:
        await conn.execute(sql)
        await conn.commit()


async def close_pool() -> None:
    global _pool, _pool_loop
    if _pool is not None:
        try:
            await _pool.close()
        finally:
            _pool = None
            _pool_loop = None
