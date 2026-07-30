"""Webhook signature verification: shared secret and HMAC-SHA256.

S5.1: Fail closed when anything is live (D7).
- DEMO_MODE=false: missing/empty secret always rejects.
- DEMO_MODE=true + ENV=dev: warn+pass (development convenience).
The Slack-specific rule (empty SLACK_SIGNING_SECRET rejects whenever
SLACK_BOT_TOKEN is set) is enforced in app/webhooks/slack.py, where the
signature is actually checked.
"""

from __future__ import annotations

import hashlib
import hmac

from app.config import settings


def verify_shared_secret(header_value: str, secret: str) -> bool:
    """Verify a shared secret using constant-time comparison.

    Rule: missing/empty secret => reject when DEMO_MODE=false, warn+pass when dev demo.
    """
    if not secret:
        if settings.DEMO_MODE and settings.ENV == "dev":
            print("[signature] Warning: empty secret, passing in dev demo mode")
            return True
        return False
    return hmac.compare_digest(header_value, secret)


def verify_hmac_sha256(body: bytes, signature: str, secret: str) -> bool:
    """Verify an HMAC-SHA256 signature against a body.

    Rule: missing/empty secret => reject when DEMO_MODE=false, warn+pass when dev demo.
    """
    if not secret:
        if settings.DEMO_MODE and settings.ENV == "dev":
            print("[signature] Warning: empty secret, passing in dev demo mode")
            return True
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(signature, expected)