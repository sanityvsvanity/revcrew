"""Mock HubSpot adapter: writes to mock_crm_objects table, logs to console."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.db import get_pool


class MockHubSpot:
    """Postgres-backed mock CRM."""

    async def upsert_contact(
        self, email: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        existing = await self.search_contact(email)
        if existing:
            existing["properties"].update(properties)
            pool = await get_pool()
            async with pool.connection() as conn:
                await conn.execute(
                    "UPDATE mock_crm_objects SET payload = %s "
                    "WHERE type = 'contact' AND payload->>'email' = %s",
                    (json.dumps(existing), email),
                )
            print(f"[MOCK hubspot] updated contact '{email}' (id={existing['id']})")
            return existing
        contact_id = str(uuid.uuid4())[:8]
        payload = {"id": contact_id, "email": email, "properties": properties}
        pool = await get_pool()
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO mock_crm_objects (type, payload) VALUES (%s, %s)",
                ("contact", json.dumps(payload)),
            )
        print(f"[MOCK hubspot] created contact '{email}' (id={contact_id})")
        return payload

    async def upsert_company(
        self, domain: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        pool = await get_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT payload FROM mock_crm_objects "
                "WHERE type = 'company' AND payload->>'domain' = %s",
                (domain,),
            )
            row = await cur.fetchone()
            if row:
                existing = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                existing.setdefault("properties", {}).update(properties)
                await conn.execute(
                    "UPDATE mock_crm_objects SET payload = %s "
                    "WHERE type = 'company' AND payload->>'domain' = %s",
                    (json.dumps(existing), domain),
                )
                print(f"[MOCK hubspot] updated company '{domain}' (id={existing.get('id')})")
                return existing
            company_id = str(uuid.uuid4())[:8]
            payload = {"id": company_id, "domain": domain, "properties": properties}
            await conn.execute(
                "INSERT INTO mock_crm_objects (type, payload) VALUES (%s, %s)",
                ("company", json.dumps(payload)),
            )
        print(f"[MOCK hubspot] created company '{domain}' (id={company_id})")
        return payload

    async def create_deal(
        self, name: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        deal_id = str(uuid.uuid4())[:8]
        amount = properties.get("amount", "$0")
        payload = {"id": deal_id, "name": name, "properties": properties}
        pool = await get_pool()
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO mock_crm_objects (type, payload) VALUES (%s, %s)",
                ("deal", json.dumps(payload)),
            )
        print(f"[MOCK hubspot] created deal '{name}' ({amount}) (id={deal_id})")
        return payload

    async def log_note(
        self, object_type: str, object_id: str, body: str
    ) -> dict[str, Any]:
        note_id = str(uuid.uuid4())[:8]
        payload = {
            "id": note_id,
            "object_type": object_type,
            "object_id": object_id,
            "body": body,
        }
        pool = await get_pool()
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO mock_crm_objects (type, payload) VALUES (%s, %s)",
                ("note", json.dumps(payload)),
            )
        print(f"[MOCK hubspot] logged note on {object_type}/{object_id}")
        return payload

    async def create_task(
        self, title: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        task_id = str(uuid.uuid4())[:8]
        payload = {"id": task_id, "title": title, "properties": properties}
        pool = await get_pool()
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO mock_crm_objects (type, payload) VALUES (%s, %s)",
                ("task", json.dumps(payload)),
            )
        print(f"[MOCK hubspot] created task '{title}'")
        return payload

    async def associate(
        self, from_type: str, from_id: str, to_type: str, to_id: str
    ) -> None:
        print(f"[MOCK hubspot] associated {from_type}/{from_id} -> {to_type}/{to_id}")

    async def search_contact(self, email: str) -> dict[str, Any] | None:
        pool = await get_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT payload FROM mock_crm_objects "
                "WHERE type = 'contact' AND payload->>'email' = %s",
                (email,),
            )
            row = await cur.fetchone()
            if row:
                return row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return None

    async def get_timeline(
        self, object_type: str, object_id: str
    ) -> list[dict[str, Any]]:
        pool = await get_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT payload FROM mock_crm_objects "
                "WHERE type = 'note' AND payload->>'object_id' = %s "
                "ORDER BY created_at DESC LIMIT 20",
                (object_id,),
            )
            rows = await cur.fetchall()
            return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]
