"""Approval interaction flow: edit in place, retry after failure, dedup, reject."""

from tests.conftest import requires_db, run_db_test


@requires_db
def test_edit_keeps_pending_and_applies_in_place():
    async def scenario():
        from app.approvals import get_approval_status
        from app.webhooks.slack import _handle_block_actions, _handle_view_submission
        from demo.pipeline import start_run

        run = await start_run(lead_index=0)
        run_id = run["run_id"]

        # The posted card is tracked so it can be updated in place later
        status = await get_approval_status(run_id)
        assert status["payload"].get("message_ts")

        # Clicking Edit must not lock or resolve the approval
        await _handle_block_actions(
            {
                "actions": [{"value": f"{run_id}:edit"}],
                "trigger_id": "t1",
                "user": {"id": "U1", "name": "maya"},
            }
        )
        assert (await get_approval_status(run_id))["status"] == "pending"

        # Submitting the modal applies the edits while still pending
        await _handle_view_submission(
            {
                "user": {"id": "U1", "name": "maya"},
                "view": {
                    "callback_id": f"edit_submit_{run_id}",
                    "private_metadata": run_id,
                    "state": {
                        "values": {
                            "subject_0": {
                                "subject_0": {
                                    "type": "plain_text_input",
                                    "value": "Edited subject",
                                }
                            },
                            "deal_amount": {
                                "deal_amount": {
                                    "type": "plain_text_input",
                                    "value": "$25,000",
                                }
                            },
                        }
                    },
                },
            }
        )
        status = await get_approval_status(run_id)
        assert status["status"] == "pending"
        data = status["payload"]["data"]
        assert data["draft"]["steps"][0]["subject"] == "Edited subject"
        assert data["deal"]["amount"] == "$25,000"
        assert status["payload"]["edits"], "edit history must be recorded"

    run_db_test(scenario)


@requires_db
def test_push_retry_resumes_without_duplicates():
    async def scenario():
        from app.approvals import get_push_detail
        from app.db import get_pool
        from app.integrations.registry import get_outreach
        from app.webhooks.slack import _handle_block_actions
        from demo.pipeline import start_run

        run = await start_run(lead_index=0)
        run_id = run["run_id"]

        outreach = get_outreach()
        original_add_lead = outreach.add_lead

        async def failing_add_lead(*args, **kwargs):
            raise RuntimeError("simulated outage")

        outreach.add_lead = failing_add_lead
        try:
            await _handle_block_actions(
                {
                    "actions": [{"value": f"{run_id}:approve"}],
                    "trigger_id": "t2",
                    "user": {"id": "U1", "name": "maya"},
                    "channel": {"id": "C1"},
                    "message": {"ts": "m1"},
                }
            )
        finally:
            outreach.add_lead = original_add_lead

        # Failure recorded with the progress reached (campaign already made)
        detail = await get_push_detail(run_id)
        assert detail["error"]
        assert detail["progress"]["campaign"]

        # Retry resumes: same campaign, no duplicates, ends pushed
        await _handle_block_actions(
            {
                "actions": [{"value": f"{run_id}:retry"}],
                "trigger_id": "t3",
                "user": {"id": "U1", "name": "maya"},
                "channel": {"id": "C1"},
                "message": {"ts": "m1"},
            }
        )
        pool = await get_pool()
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT COUNT(*) FROM mock_campaigns")
            assert (await cur.fetchone())[0] == 1
            cur = await conn.execute(
                "SELECT push_status FROM approvals WHERE run_id = %s", (run_id,)
            )
            assert (await cur.fetchone())[0] == "pushed"
            # A retry must not leave a "second signal" note
            cur = await conn.execute(
                "SELECT COUNT(*) FROM mock_crm_objects WHERE type = 'note' "
                "AND payload->>'body' LIKE '%%Second signal%%'"
            )
            assert (await cur.fetchone())[0] == 0

        # A second approved run for the same company dedupes the deal
        run2 = await start_run(lead_index=0)
        await _handle_block_actions(
            {
                "actions": [{"value": f"{run2['run_id']}:approve"}],
                "trigger_id": "t4",
                "user": {"id": "U1", "name": "maya"},
                "channel": {"id": "C1"},
                "message": {"ts": "m2"},
            }
        )
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM mock_crm_objects WHERE type = 'deal'"
            )
            assert (await cur.fetchone())[0] == 1
            cur = await conn.execute(
                "SELECT COUNT(*) FROM mock_crm_objects WHERE type = 'note' "
                "AND payload->>'body' LIKE '%%Second signal%%'"
            )
            assert (await cur.fetchone())[0] == 1

    run_db_test(scenario)


@requires_db
def test_reject_records_reason():
    async def scenario():
        from app.db import get_pool
        from app.webhooks.slack import _handle_view_submission
        from demo.pipeline import start_run

        run = await start_run(lead_index=1)
        run_id = run["run_id"]

        await _handle_view_submission(
            {
                "user": {"id": "U1", "name": "maya"},
                "view": {
                    "callback_id": f"reject_submit_{run_id}",
                    "private_metadata": run_id,
                    "state": {
                        "values": {
                            "reject_reason": {
                                "reject_reason": {
                                    "type": "static_select",
                                    "selected_option": {"value": "bad_timing"},
                                }
                            },
                            "reject_detail": {
                                "reject_detail": {
                                    "type": "plain_text_input",
                                    "value": "quarter end",
                                }
                            },
                        }
                    },
                },
            }
        )
        pool = await get_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT status, reject_reason, reject_detail FROM approvals "
                "WHERE run_id = %s",
                (run_id,),
            )
            assert await cur.fetchone() == ("rejected", "bad_timing", "quarter end")

    run_db_test(scenario)


@requires_db
def test_distinct_replies_logged_and_redelivery_deduped():
    async def scenario():
        from app.db import get_pool
        from app.events import dispatch_pending_events, enqueue_event

        reply_a = {"from": "pat@example.com", "subject": "Re:", "body": "interested, send over pricing"}
        reply_b = {"from": "pat@example.com", "subject": "Re:", "body": "not right now, check back next quarter"}

        await enqueue_event("instantly", "reply_received", reply_a)
        await enqueue_event("instantly", "reply_received", reply_b)
        await dispatch_pending_events()

        pool = await get_pool()

        async def reply_notes():
            async with pool.connection() as conn:
                cur = await conn.execute(
                    "SELECT COUNT(*) FROM mock_crm_objects WHERE type = 'note' "
                    "AND payload->>'body' LIKE 'Reply received%%'"
                )
                return (await cur.fetchone())[0]

        # Two different replies from the same sender are both real writes
        assert await reply_notes() == 2

        # A redelivered identical payload dedupes instead of double-logging
        await enqueue_event("instantly", "reply_received", reply_a)
        await dispatch_pending_events()
        assert await reply_notes() == 2

    run_db_test(scenario)
