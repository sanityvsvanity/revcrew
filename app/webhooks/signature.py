"""Webhook signature verification: shared secret and HMAC-SHA256."""

from __future__ import annotations

import hashlib
import hmac

from app.config import settings


def verify_shared_secret(header_value: str, secret: str) -> bool:
    """Verify a shared secret using constant-time comparison.

    Rule: missing/empty secret => reject when ENV=prod, warn+pass when dev.
    """
    if not secret:
        if settings.ENV == "prod":
            return False
        print("[signature] Warning: empty secret, passing in dev mode")
        return True
    return hmac.compare_digest(header_value, secret)


def verify_hmac_sha256(body: bytes, signature: str, secret: str) -> bool:
    """Verify an HMAC-SHA256 signature against a body.

    Rule: missing/empty secret => reject when ENV=prod, warn+pass when dev.
    """
    if not secret:
        if settings.ENV == "prod":
            return False
        print("[signature] Warning: empty secret, passing in dev mode")
        return True

    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(signature, expected)