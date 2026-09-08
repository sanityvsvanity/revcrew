"""The tool contract: envelopes, classification, breaker."""

import asyncio
import json

import pytest

from app.toolkits import _contract as c


@pytest.fixture(autouse=True)
def _reset():
    c.reset_breaker()
    yield
    c.reset_breaker()


class TestClassify:
    def test_terminal_wins_over_transient_words(self):
        # Vendor prose: a not-found that mentions a "connection" is still permanent.
        assert (
            c.classify_error(
                "Could not find page shared with your integration connection"
            )
            == "terminal"
        )

    def test_http_codes(self):
        assert c.classify_error("HTTP 404") == "terminal"
        assert c.classify_error("HTTP 429 too many requests") == "transient"
        assert c.classify_error("503 service unavailable") == "transient"

    def test_budget_is_terminal(self):
        assert (
            c.classify_error("research budget: 25 tool calls per account reached")
            == "terminal"
        )

    def test_unknown_defaults_transient(self):
        assert c.classify_error("something odd happened") == "transient"

    def test_exception_type_can_decide(self):
        assert c.classify_error("weird", ValueError("weird")) == "terminal"


class TestWrapTool:
    def test_exception_becomes_envelope_never_raises(self):
        @c.wrap_tool(toolkit="t")
        async def boom(url: str):
            raise RuntimeError("HTTP 403 forbidden")

        out = json.loads(asyncio.run(boom(url="https://x")))
        assert out["ok"] is False
        assert out["error_class"] == "terminal"
        assert out["do_not_retry"] is True
        assert "forbidden" in out["error"]

    def test_success_dict_is_wrapped(self):
        @c.wrap_tool
        async def fine(x: int):
            return {"value": x}

        out = json.loads(asyncio.run(fine(x=2)))
        assert out == {"ok": True, "result": {"value": 2}}

    def test_tool_envelope_passes_through(self):
        @c.wrap_tool
        async def refuse(x: int):
            return c.envelope("research budget reached", "terminal", tier=2)

        out = json.loads(asyncio.run(refuse(x=1)))
        assert out["ok"] is False and out["tier"] == 2 and out["do_not_retry"] is True

    def test_sync_body_runs_in_thread(self):
        @c.wrap_tool
        def sync_fn(a: int):
            return a + 1

        assert json.loads(asyncio.run(sync_fn(a=1)))["result"] == 2

    def test_breaker_short_circuits_identical_failures(self):
        calls = {"n": 0}

        @c.wrap_tool
        async def flaky(q: str):
            calls["n"] += 1
            raise RuntimeError("connection reset")

        for _ in range(c.FAIL_THRESHOLD):
            json.loads(asyncio.run(flaky(q="same")))
        out = json.loads(asyncio.run(flaky(q="same")))
        assert out.get("breaker") is True and out["do_not_retry"] is True
        assert calls["n"] == c.FAIL_THRESHOLD, "the 4th identical call must not run"

        # Different arguments are a different signature: the tool runs again.
        json.loads(asyncio.run(flaky(q="other")))
        assert calls["n"] == c.FAIL_THRESHOLD + 1

    def test_timeout_is_transient(self):
        @c.wrap_tool(timeout_s=0.01)
        async def slow():
            await asyncio.sleep(0.2)

        out = json.loads(asyncio.run(slow()))
        assert out["ok"] is False and out["error_class"] == "transient"

    def test_wrapper_keeps_name_and_doc(self):
        @c.wrap_tool
        async def named(url: str):
            """Docstring survives."""
            return {}

        assert named.__name__ == "named" and "survives" in named.__doc__
