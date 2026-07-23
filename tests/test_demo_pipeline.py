"""Golden path: the demo leaves the exact state it claims to leave."""

from tests.conftest import requires_db, run_db_test


@requires_db
def test_demo_golden_path():
    async def scenario():
        from app.db import get_pool
        from demo.run_demo import run_demo

        await run_demo(paced=False, lead_index=0, reset=False)

        pool = await get_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT type, COUNT(*) FROM mock_crm_objects GROUP BY type"
            )
            counts = dict(await cur.fetchall())
            assert counts.get("contact") == 1
            assert counts.get("company") == 1
            assert counts.get("deal") == 1
            assert counts.get("task") == 1
            assert counts.get("note", 0) >= 2

            cur = await conn.execute("SELECT payload->>'status' FROM mock_campaigns")
            rows = await cur.fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "paused", "campaigns must always be created paused"

            cur = await conn.execute("SELECT status FROM approvals")
            assert [r[0] for r in await cur.fetchall()] == ["approved"]

            cur = await conn.execute("SELECT status FROM events")
            assert [r[0] for r in await cur.fetchall()] == ["processed"]

    run_db_test(scenario)


@requires_db
def test_demo_reruns_cleanly():
    """Two runs against the same database must not error or duplicate approvals."""

    async def scenario():
        from app.db import get_pool
        from demo.run_demo import run_demo

        await run_demo(paced=False, lead_index=0, reset=False)
        await run_demo(paced=False, lead_index=1, reset=False)

        pool = await get_pool()
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT COUNT(*) FROM approvals WHERE status = 'approved'")
            assert (await cur.fetchone())[0] == 2
            cur = await conn.execute("SELECT COUNT(*) FROM mock_campaigns")
            assert (await cur.fetchone())[0] == 2

    run_db_test(scenario)
