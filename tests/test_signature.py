"""Webhook signature verification rules."""

import hashlib
import hmac

from app.config import settings
from app.webhooks.signature import verify_hmac_sha256, verify_shared_secret

SECRET = "test-secret"
BODY = b'{"event": "reply_received"}'


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_shared_secret_valid():
    assert verify_shared_secret(SECRET, SECRET) is True


def test_shared_secret_invalid():
    assert verify_shared_secret("wrong", SECRET) is False


def test_hmac_valid():
    assert verify_hmac_sha256(BODY, _sign(BODY, SECRET), SECRET) is True


def test_hmac_invalid_signature():
    assert verify_hmac_sha256(BODY, _sign(BODY, "other"), SECRET) is False


def test_hmac_tampered_body():
    sig = _sign(BODY, SECRET)
    assert verify_hmac_sha256(BODY + b"x", sig, SECRET) is False


def test_missing_secret_rejected_in_prod(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "prod")
    assert verify_shared_secret("anything", "") is False
    assert verify_hmac_sha256(BODY, "anything", "") is False


def test_missing_secret_passes_in_dev(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "dev")
    assert verify_shared_secret("anything", "") is True
    assert verify_hmac_sha256(BODY, "anything", "") is True
