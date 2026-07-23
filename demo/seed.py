"""Seed demo data into the mock database. Safe to run repeatedly."""

import asyncio
import json
from pathlib import Path

from app.db import close_pool, get_pool

DATA_DIR = Path(__file__).parent / "data"

SEED_TYPES = ("lead", "company", "reply")


async def seed():
    pool = await get_pool()

    # Reset previously seeded rows so repeated runs converge on the same state
    async with pool.connection() as conn:
        await conn.execute(
            "DELETE FROM mock_crm_objects WHERE type = ANY(%s)",
            (list(SEED_TYPES),),
        )

    for obj_type, plural, filename in (
        ("lead", "leads", "leads.json"),
        ("company", "companies", "companies.json"),
        ("reply", "replies", "replies.json"),
    ):
        path = DATA_DIR / filename
        if not path.exists():
            continue
        items = json.loads(path.read_text())
        async with pool.connection() as conn:
            for item in items:
                await conn.execute(
                    "INSERT INTO mock_crm_objects (type, payload) VALUES (%s, %s)",
                    (obj_type, json.dumps(item)),
                )
        print(f"Seeded {len(items)} {plural}")

    async with pool.connection() as conn:
        for obj_type, plural in (("lead", "leads"), ("company", "companies"), ("reply", "replies")):
            cur = await conn.execute(
                "SELECT COUNT(*) FROM mock_crm_objects WHERE type = %s",
                (obj_type,),
            )
            count = (await cur.fetchone())[0]
            print(f"  {plural} in DB: {count}")

    await close_pool()


if __name__ == "__main__":
    asyncio.run(seed())
