"""Guarded writes: validate → cap → dedupe → audit.

Every CRM write passes through GuardedCRM before reaching the adapter.
The audit table doubles as the activity feed for the digest and copilot.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import re
from typing import Any

from app.config import settings
from app.db import get_pool
from app.normalize import parse_amount

# ---------------------------------------------------------------------------
# WriteContext — every write must carry a context
# ---------------------------------------------------------------------------

_write_ctx: contextvars.ContextVar[dict[str, str] | None] = (
    contextvars.ContextVar("write_context", default=None)
)

# Per-source operation allowlists (S4.7)
_SOURCE_OPS: dict[str, set[str]] = {
    "triage": {"log_note", "create_task"},
    "events": {"log_note"},
}


def set_write_context(context_id: str, source: str) -> None:
    """Set the write context for the current async context."""
    _write_ctx.set({"context_id": context_id, "source": source})


def get_write_context() -> dict[str, str]:
    """Return the current write context, or raise if none is set."""
    ctx = _write_ctx.get()
    if ctx is None:
        raise ValueError(
            "No WriteContext set — every CRM write path must call "
            "set_write_context(context_id, source) before touching the CRM."
        )
    return ctx


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)+$")
_MAX_NOTE_BODY = 4_000

# Property allowlists per object type — fail early with a better message
# than HubSpot's 400.
_CONTACT_PROPS = {"email", "firstname", "lastname", "company", "jobtitle", "phone", "website"}
_COMPANY_PROPS = {"domain", "name", "industry", "numberofemployees", "description", "website"}
_DEAL_PROPS = {"dealname", "dealstage", "amount", "pipeline", "closedate", "hubspot_owner_id"}


def _validate_email(email: str) -> str:
    if not _EMAIL_RE.match(email):
        raise ValueError(f"Invalid email: {email!r}")
    return email


def _validate_domain(domain: str) -> str:
    if not _DOMAIN_RE.match(domain):
        raise ValueError(f"Invalid domain: {domain!r}")
    return domain


def _validate_note_body(body: str) -> str:
    if len(body) > _MAX_NOTE_BODY:
        raise ValueError(f"Note body exceeds {_MAX_NOTE_BODY} chars ({len(body)})")
    return body


def _validate_properties(props: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    unknown = set(props) - allowed
    if unknown:
        raise ValueError(f"Unknown properties: {sorted(unknown)}. Allowed: {sorted(allowed)}")
    return props


def _validate_amount(raw: str | None) -> str | None:
    """Validate and normalize a deal amount. Returns the string representation or None."""
    if raw is None or raw == "":
        return None
    parsed = parse_amount(raw)
    if parsed is None:
        raise ValueError(f"Invalid deal amount: {raw!r}. Must be a positive number ≤ {settings.MAX_DEAL_AMOUNT}.")
    return str(parsed)


# ---------------------------------------------------------------------------
# Idempotency key
# ---------------------------------------------------------------------------


def _idempotency_key(context_id: str, operation: str, natural_key: str) -> str:
    """Build a deterministic idempotency key (D6)."""
    raw = f"{context_id}|{operation}|{natural_key}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


async def _audit(
    *,
    context_id: str,
    source: str,
    operation: str,
    object_type: str,
    natural_key: str,
    idempotency_key: str,
    decision: str,
    reason: str = "",
    payload_summary: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """INSERT INTO write_audit
               (context_id, source, operation, object_type, natural_key,
                idempotency_key, decision, reason, payload_summary, result)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                context_id,
                source,
                operation,
                object_type,
                natural_key,
                idempotency_key,
                decision,
                reason,
                json.dumps(payload_summary or {}),
                json.dumps(result or {}),
            ),
        )


# ---------------------------------------------------------------------------
# Write counter (per-context cap)
# ---------------------------------------------------------------------------


async def _context_write_count(context_id: str) -> int:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM write_audit WHERE context_id = %s AND decision = 'allowed'",
            (context_id,),
        )
        row = await cur.fetchone()
        return row[0] if row else 0


# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------


async def _check_idempotent(idempotency_key: str) -> dict[str, Any] | None:
    """Return the prior result if this key was already executed, else None."""
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT result FROM write_audit WHERE idempotency_key = %s AND decision = 'allowed' LIMIT 1",
            (idempotency_key,),
        )
        row = await cur.fetchone()
        if row and row[0]:
            return row[0] if isinstance(row[0], dict) else json.loads(row[0])
    return None


# ---------------------------------------------------------------------------
# GuardedCRM
# ---------------------------------------------------------------------------


class GuardedCRM:
    """Wraps a CRMPort adapter with validate → cap → dedupe → audit.

    Every write is refused unless a WriteContext is active (S4.2).
    Per-source operation allowlists are enforced (S4.7).
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    # -- helpers -----------------------------------------------------------

    def _check_source_op(self, operation: str) -> None:
        ctx = get_write_context()
        source = ctx["source"]
        allowed = _SOURCE_OPS.get(source)
        if allowed is not None and operation not in allowed:
            raise ValueError(
                f"Operation {operation!r} not allowed for source {source!r}. "
                f"Allowed: {sorted(allowed)}"
            )

    async def _guard(
        self,
        operation: str,
        object_type: str,
        natural_key: str,
        payload_summary: dict[str, Any],
        fn,
    ) -> dict[str, Any]:
        ctx = get_write_context()
        context_id = ctx["context_id"]
        source = ctx["source"]
        ikey = _idempotency_key(context_id, operation, natural_key)

        # 1. Source operation allowlist
        self._check_source_op(operation)

        # 2. Cap
        count = await _context_write_count(context_id)
        if count >= settings.MAX_WRITES_PER_CONTEXT:
            await _audit(
                context_id=context_id,
                source=source,
                operation=operation,
                object_type=object_type,
                natural_key=natural_key,
                idempotency_key=ikey,
                decision="refused",
                reason=f"Write cap exceeded ({settings.MAX_WRITES_PER_CONTEXT})",
                payload_summary=payload_summary,
            )
            raise ValueError(
                f"Write cap exceeded: {count} writes already in context {context_id!r} "
                f"(max {settings.MAX_WRITES_PER_CONTEXT})."
            )

        # 3. Idempotency
        prior = await _check_idempotent(ikey)
        if prior is not None:
            await _audit(
                context_id=context_id,
                source=source,
                operation=operation,
                object_type=object_type,
                natural_key=natural_key,
                idempotency_key=ikey,
                decision="deduped",
                reason="Duplicate idempotency key",
                payload_summary=payload_summary,
            )
            return prior

        # 4. Execute
        try:
            result = await fn()
        except Exception as exc:
            await _audit(
                context_id=context_id,
                source=source,
                operation=operation,
                object_type=object_type,
                natural_key=natural_key,
                idempotency_key=ikey,
                decision="refused",
                reason=str(exc),
                payload_summary=payload_summary,
            )
            raise

        # 5. Audit success
        await _audit(
            context_id=context_id,
            source=source,
            operation=operation,
            object_type=object_type,
            natural_key=natural_key,
            idempotency_key=ikey,
            decision="allowed",
            reason="",
            payload_summary=payload_summary,
            result=result,
        )
        return result

    # -- CRM operations ----------------------------------------------------

    async def upsert_contact(
        self, email: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        _validate_email(email)
        _validate_properties(properties, _CONTACT_PROPS)
        return await self._guard(
            operation="upsert_contact",
            object_type="contact",
            natural_key=email,
            payload_summary={"email": email},
            fn=lambda: self._inner.upsert_contact(email, properties),
        )

    async def upsert_company(
        self, domain: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        _validate_domain(domain)
        _validate_properties(properties, _COMPANY_PROPS)
        return await self._guard(
            operation="upsert_company",
            object_type="company",
            natural_key=domain,
            payload_summary={"domain": domain},
            fn=lambda: self._inner.upsert_company(domain, properties),
        )

    async def create_deal(
        self, name: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        # company_domain is a dedup hint, not a HubSpot property — pull it out
        # before the property allowlist sees it.
        domain = properties.pop("company_domain", None)
        _validate_properties(properties, _DEAL_PROPS)
        if "amount" in properties:
            properties["amount"] = _validate_amount(properties["amount"])

        # S4.6: Cross-run deal dedup — a prior RevCrew deal on the same company
        # gets a "second signal" note instead of a sibling deal. A deal from
        # the *same* context is a retry, not a second signal: fall through and
        # let the idempotency check replay it silently.
        if settings.DEAL_DEDUP and domain:
            ctx = get_write_context()
            existing, prior_context = await self._find_prior_deal_for_domain(domain)
            if existing and existing.get("id") and prior_context != ctx["context_id"]:
                await _audit(
                    context_id=ctx["context_id"],
                    source=ctx["source"],
                    operation="create_deal",
                    object_type="deal",
                    natural_key=name,
                    idempotency_key=_idempotency_key(ctx["context_id"], "create_deal", name),
                    decision="deduped",
                    reason=f"Open deal already exists for {domain}",
                    payload_summary={"deal_name": name, "company_domain": domain},
                    result=existing,
                )
                await self.log_note(
                    "deal", existing["id"],
                    f"Second signal received for {domain}. Existing deal: {existing.get('name', name)}"
                )
                return existing

        return await self._guard(
            operation="create_deal",
            object_type="deal",
            natural_key=name,
            payload_summary={
                "deal_name": name,
                "amount": properties.get("amount"),
                "company_domain": domain,
            },
            fn=lambda: self._inner.create_deal(name, properties),
        )

    async def _find_prior_deal_for_domain(
        self, domain: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Return (deal, context_id) of the most recent deal RevCrew created
        for a company domain, or (None, None).

        Looks in write_audit (works identically in mock and live mode) rather
        than querying the CRM, so it only sees deals this system wrote — which
        is exactly the duplicate class the pipeline can produce. Horizon is
        bounded by RETENTION_DAYS.
        """
        pool = await get_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT result, context_id FROM write_audit "
                "WHERE operation = 'create_deal' AND decision = 'allowed' "
                "AND payload_summary->>'company_domain' = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (domain,),
            )
            row = await cur.fetchone()
            if row and row[0]:
                deal = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                return deal, row[1]
        return None, None

    async def log_note(
        self, object_type: str, object_id: str, body: str
    ) -> dict[str, Any]:
        _validate_note_body(body)
        # Body hash in the key: two different notes on the same object within
        # one context are both real writes, only an identical retry dedupes.
        body_hash = hashlib.sha256(body.encode()).hexdigest()[:12]
        return await self._guard(
            operation="log_note",
            object_type="note",
            natural_key=f"{object_type}:{object_id}:{body_hash}",
            payload_summary={"on": f"{object_type}/{object_id}"},
            fn=lambda: self._inner.log_note(object_type, object_id, body),
        )

    async def create_task(
        self, title: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        props_hash = hashlib.sha256(
            json.dumps(properties, sort_keys=True, default=str).encode()
        ).hexdigest()[:12]
        return await self._guard(
            operation="create_task",
            object_type="task",
            natural_key=f"{title}:{props_hash}",
            payload_summary={"title": title},
            fn=lambda: self._inner.create_task(title, properties),
        )

    async def associate(
        self, from_type: str, from_id: str, to_type: str, to_id: str
    ) -> None:
        await self._guard(
            operation="associate",
            object_type="association",
            natural_key=f"{from_type}:{from_id}->{to_type}:{to_id}",
            payload_summary={"from": f"{from_type}/{from_id}", "to": f"{to_type}/{to_id}"},
            fn=lambda: self._inner.associate(from_type, from_id, to_type, to_id),
        )

    # -- Read passthrough (unguarded) --------------------------------------

    async def search_contact(self, email: str) -> dict[str, Any] | None:
        return await self._inner.search_contact(email)

    async def get_timeline(
        self, object_type: str, object_id: str
    ) -> list[dict[str, Any]]:
        return await self._inner.get_timeline(object_type, object_id)