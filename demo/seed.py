"""Seed demo data into the mock database (idempotent)."""

import asyncio
import json
from pathlib import Path

from app.db import get_pool, close_pool

DATA_DIR = Path(__file__).parent / "data"


async def seed():
    pool = await get_pool()

    # Load leads
    leads_path = DATA_DIR / "leads.json"
    if leads_path.exists():
        leads = json.loads(leads_path.read_text())
        async with pool.connection() as conn:
            for lead in leads:
                await conn.execute(
                    "INSERT INTO mock_crm_objects (type, payload) VALUES ('lead', $1) "
                    "ON CONFLICT DO NOTHING",
                    (json.dumps(lead),),
                )
        print(f"Seeded {len(leads)} leads")

    # Load companies
    companies_path = DATA_DIR / "companies.json"
    if companies_path.exists():
        companies = json.loads(companies_path.read_text())
        async with pool.connection() as conn:
            for company in companies:
                await conn.execute(
                    "INSERT INTO mock_crm_objects (type, payload) VALUES ('company', $1) "
                    "ON CONFLICT DO NOTHING",
                    (json.dumps(company),),
                )
        print(f"Seeded {len(companies)} companies")

    # Load replies
    replies_path = DATA_DIR / "replies.json"
    if replies_path.exists():
        replies = json.loads(replies_path.read_text())
        async with pool.connection() as conn:
            for reply in replies:
                await conn.execute(
                    "INSERT INTO mock_crm_objects (type, payload) VALUES ('reply', $1) "
                    "ON CONFLICT DO NOTHING",
                    (json.dumps(reply),),
                )
        print(f"Seeded {len(replies)} replies")

    # Print counts
    async with pool.connection() as conn:
        for obj_type in ("lead", "company", "reply"):
            result = await conn.execute(
                "SELECT COUNT(*) FROM mock_crm_objects WHERE type=$1",
                (obj_type,),
            )
            count = (await result.fetchone())[0]
            print(f"  {obj_type}s in DB: {count}")

    await close_pool()


if __name__ == "__main__":
    asyncio.run(seed())