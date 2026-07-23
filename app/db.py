"""Database connection pool and schema initialization."""

from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg_pool import AsyncConnectionPool

from app.config import settings

_pool: AsyncConnectionPool | None = None
_schema_path = Path(__file__).parent / "schema.sql"


async def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        # Accept both plain libpq URLs and SQLAlchemy-style postgresql+psycopg://
        conninfo = settings.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
        _pool = AsyncConnectionPool(
            conninfo=conninfo,
            min_size=1,
            max_size=5,
            open=False,
        )
        await _pool.open()
        await _init_schema(_pool)
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
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None