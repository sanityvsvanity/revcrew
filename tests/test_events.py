"""Event outbox: dispatch, retry with backoff, dead-letter."""

from tests.conftest import requires_db, run_db_test


@requires_db
def test_enqueue_and_dispatch():
    async def scenario():
        from app.db import get_pool
        from app.events import dispatch_pending_events, enqueue_event

        event_id = await enqueue_event(
            "instantly",
            "reply_received",
            {"from": "sarah.chen@meridianhq.com", "subject": "Re: pricing", "body": "Interested, send over pricing."},
        )
        assert event_id > 0

        dispatched = await dispatch_pending_events()
        assert dispatched == 1

        pool = await get_pool()
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT status FROM events WHERE id = %s", (event_id,))
            assert (await cur.fetchone())[0] == "processed"

            # Triage side effects: a note, a follow-up task, a chat alert
            cur = await conn.execute("SELECT COUNT(*) FROM mock_crm_objects WHERE type = 'task'")
            assert (await cur.fetchone())[0] == 1
            cur = await conn.execute("SELECT COUNT(*) FROM mock_messages")
            assert (await cur.fetchone())[0] == 1

    run_db_test(scenario)


@requires_db
def test_processed_events_not_redispatched():
    async def scenario():
        from app.events import dispatch_pending_events, enqueue_event

        await enqueue_event(
            "instantly",
            "reply_received",
            {"from": "x@example.com", "subject": "s", "body": "out of office until Monday"},
        )
        assert await dispatch_pending_events() == 1
        assert await dispatch_pending_events() == 0

    run_db_test(scenario)


@requires_db
def test_failed_event_retries_then_dead_letters(monkeypatch):
    import app.events as events_mod

    async def boom(source, kind, payload):
        raise RuntimeError("handler down")

    monkeypatch.setattr(events_mod, "_handle_event", boom)

    async def scenario():
        from app.db import get_pool
        from app.events import dispatch_pending_events, enqueue_event

        event_id = await enqueue_event("instantly", "reply_received", {"from": "x@example.com"})
        pool = await get_pool()

        # Drive through all retries by clearing the backoff timestamp each round
        for expected_retry in range(1, events_mod.MAX_RETRIES + 1):
            await dispatch_pending_events()
            async with pool.connection() as conn:
                cur = await conn.execute(
                    "SELECT retries, status FROM events WHERE id = %s", (event_id,)
                )
                retries, status = await cur.fetchone()
                assert retries == expected_retry
                assert status == "pending"
                await conn.execute(
                    "UPDATE events SET next_attempt_at = NOW() WHERE id = %s", (event_id,)
                )

        # One more failure pushes it past MAX_RETRIES into dead_letter
        await dispatch_pending_events()
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT status FROM events WHERE id = %s", (event_id,))
            assert (await cur.fetchone())[0] == "dead_letter"

    run_db_test(scenario)
