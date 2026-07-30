"""Data normalization: parse and validate CRM-bound values before they reach the adapter."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.config import settings

_AMOUNT_CLEAN = re.compile(r"[\s$,]")


def parse_amount(raw: str | None) -> Decimal | None:
    """Parse a deal amount string into a Decimal, or return None.

    Strips ``$``, ``,``, and spaces. Rejects negatives, NaN, and values
    exceeding ``MAX_DEAL_AMOUNT``. Returns ``None`` for empty / unparseable
    input so callers can decide whether to omit the field or raise.
    """
    if raw is None:
        return None
    cleaned = _AMOUNT_CLEAN.sub("", str(raw))
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if value < 0:
        return None
    cap = settings.MAX_DEAL_AMOUNT
    if value > cap:
        return None
    return value