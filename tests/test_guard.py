"""Tests for GuardedCRM: validation, cap, idempotency, per-source ops, guarded registry."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.guard import (
    GuardedCRM,
    get_write_context,
    set_write_context,
)
from app.integrations.registry import get_crm, reset_registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_registry()
    yield
    reset_registry()


@pytest.fixture
def mock_inner():
    """Return an AsyncMock that satisfies the CRMPort protocol."""
    inner = AsyncMock()
    inner.upsert_contact.return_value = {"id": "c1", "email": "test@example.com"}
    inner.upsert_company.return_value = {"id": "co1", "domain": "example.com"}
    inner.create_deal.return_value = {"id": "d1", "dealname": "Test Deal"}
    inner.log_note.return_value = {"id": "n1"}
    inner.create_task.return_value = {"id": "t1"}
    inner.associate.return_value = None
    inner.search_contact.return_value = {"id": "c1", "email": "test@example.com"}
    inner.get_timeline.return_value = []
    return inner


@pytest.fixture
def guarded(mock_inner):
    return GuardedCRM(mock_inner)


@pytest.fixture
def _ctx():
    """Set a default write context for the test."""
    set_write_context("test-run-1", "demo")
    yield


# ---------------------------------------------------------------------------
# WriteContext
# ---------------------------------------------------------------------------


class TestWriteContext:
    @pytest.mark.asyncio
    async def test_context_required(self, guarded):
        """A write without a context should raise."""
        with pytest.raises(ValueError, match="No WriteContext"):
            await guarded.upsert_contact("test@example.com", {})

    def test_context_set_and_read(self):
        set_write_context("ctx-1", "demo")
        ctx = get_write_context()
        assert ctx["context_id"] == "ctx-1"
        assert ctx["source"] == "demo"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_ctx")
    async def test_invalid_email_refused(self, guarded):
        with pytest.raises(ValueError, match="Invalid email"):
            await guarded.upsert_contact("not-an-email", {})

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_ctx")
    async def test_invalid_domain_refused(self, guarded):
        with pytest.raises(ValueError, match="Invalid domain"):
            await guarded.upsert_company("not a domain", {})

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_ctx")
    async def test_unknown_properties_refused(self, guarded):
        with pytest.raises(ValueError, match="Unknown properties"):
            await guarded.upsert_contact("test@example.com", {"evil_field": "inject"})

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_ctx")
    async def test_invalid_amount_refused(self, guarded):
        with pytest.raises(ValueError, match="Invalid deal amount"):
            await guarded.create_deal("Test", {"amount": "-5000"})

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_ctx")
    async def test_note_body_too_long_refused(self, guarded):
        with pytest.raises(ValueError, match="Note body exceeds"):
            await guarded.log_note("contact", "1", "x" * 5000)

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_ctx")
    async def test_valid_write_passes(self, guarded, mock_inner):
        result = await guarded.upsert_contact("test@example.com", {"firstname": "Jane"})
        assert result["id"] == "c1"
        mock_inner.upsert_contact.assert_awaited_once()


# ---------------------------------------------------------------------------
# Cap
# ---------------------------------------------------------------------------


class TestCap:
    @pytest.mark.asyncio
    async def test_write_cap_exceeded(self, guarded, monkeypatch):
        set_write_context("cap-test-1", "demo")
        monkeypatch.setattr(settings, "MAX_WRITES_PER_CONTEXT", 2)
        # Two writes should succeed
        await guarded.upsert_contact("a@example.com", {})
        await guarded.upsert_contact("b@example.com", {})
        # Third should be refused
        with pytest.raises(ValueError, match="Write cap exceeded"):
            await guarded.upsert_contact("c@example.com", {})


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_duplicate_deduped(self, guarded, mock_inner):
        set_write_context("idem-test-1", "demo")
        result1 = await guarded.upsert_contact("dup@example.com", {"firstname": "A"})
        result2 = await guarded.upsert_contact("dup@example.com", {"firstname": "B"})
        # Second call should return the prior result, not re-execute
        assert result2 == result1
        # Inner should only have been called once
        assert mock_inner.upsert_contact.call_count == 1


# ---------------------------------------------------------------------------
# Per-source operation allowlist
# ---------------------------------------------------------------------------


class TestSourceOps:
    @pytest.mark.asyncio
    async def test_triage_can_log_note(self, guarded, mock_inner):
        set_write_context("triage-1", "triage")
        result = await guarded.log_note("contact", "1", "Follow up")
        assert result["id"] == "n1"

    @pytest.mark.asyncio
    async def test_triage_cannot_create_deal(self, guarded):
        set_write_context("triage-1", "triage")
        with pytest.raises(ValueError, match="not allowed for source 'triage'"):
            await guarded.create_deal("Bad Deal", {})

    @pytest.mark.asyncio
    async def test_events_can_log_note(self, guarded, mock_inner):
        set_write_context("evt-1", "events")
        result = await guarded.log_note("contact", "1", "Event note")
        assert result["id"] == "n1"

    @pytest.mark.asyncio
    async def test_events_cannot_upsert_contact(self, guarded):
        set_write_context("evt-1", "events")
        with pytest.raises(ValueError, match="not allowed for source 'events'"):
            await guarded.upsert_contact("x@example.com", {})

    @pytest.mark.asyncio
    async def test_demo_source_has_full_access(self, guarded, mock_inner):
        set_write_context("demo-1", "demo")
        # demo is not in _SOURCE_OPS, so all ops are allowed
        result = await guarded.create_deal("Demo Deal", {})
        assert result["id"] == "d1"


# ---------------------------------------------------------------------------
# Guarded registry
# ---------------------------------------------------------------------------


class TestGuardedRegistry:
    def test_get_crm_returns_guarded(self, monkeypatch):
        monkeypatch.setattr(settings, "DEMO_MODE", True)
        crm = get_crm()
        assert type(crm).__name__ == "GuardedCRM"

    def test_get_crm_live_returns_guarded(self, monkeypatch):
        monkeypatch.setattr(settings, "DEMO_MODE", False)
        monkeypatch.setattr(settings, "HUBSPOT_PRIVATE_APP_TOKEN", "fake-token")
        crm = get_crm()
        assert type(crm).__name__ == "GuardedCRM"


# ---------------------------------------------------------------------------
# Read passthrough
# ---------------------------------------------------------------------------


class TestReadPassthrough:
    @pytest.mark.asyncio
    async def test_search_contact_passthrough(self, guarded, mock_inner):
        # Reads do not require a write context
        result = await guarded.search_contact("test@example.com")
        assert result["id"] == "c1"
        mock_inner.search_contact.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_timeline_passthrough(self, guarded, mock_inner):
        result = await guarded.get_timeline("contact", "1")
        assert result == []
        mock_inner.get_timeline.assert_awaited_once()
