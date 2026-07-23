"""Webhook endpoints: Slack signature rules, Instantly secret, lead intake."""

import hashlib
import hmac
import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from tests.conftest import requires_db

SIGNING_SECRET = "test-signing-secret"


def _slack_app(monkeypatch):
    import app.webhooks.slack as slack_mod

    monkeypatch.setattr(settings, "SLACK_SIGNING_SECRET", SIGNING_SECRET)

    async def noop(event):
        return None

    monkeypatch.setattr(slack_mod, "_handle_incoming_message", noop)
    test_app = FastAPI()
    test_app.include_router(slack_mod.router)
    return TestClient(test_app)


def _sign(body: bytes, ts: str) -> str:
    base = f"v0:{ts}:{body.decode()}".encode()
    return "v0=" + hmac.new(SIGNING_SECRET.encode(), base, hashlib.sha256).hexdigest()


def test_slack_url_verification_challenge(monkeypatch):
    client = _slack_app(monkeypatch)
    resp = client.post(
        "/slack/events",
        json={"type": "url_verification", "challenge": "abc123"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"challenge": "abc123"}


def test_slack_invalid_signature_rejected(monkeypatch):
    client = _slack_app(monkeypatch)
    body = json.dumps({"event": {"type": "app_mention", "text": "hi"}})
    resp = client.post(
        "/slack/events",
        content=body,
        headers={
            "x-slack-signature": "v0=deadbeef",
            "x-slack-request-timestamp": str(int(time.time())),
        },
    )
    assert resp.status_code == 401


def test_slack_stale_timestamp_rejected(monkeypatch):
    client = _slack_app(monkeypatch)
    body = json.dumps({"event": {"type": "app_mention", "text": "hi"}}).encode()
    stale = str(int(time.time()) - 600)
    resp = client.post(
        "/slack/events",
        content=body,
        headers={
            "x-slack-signature": _sign(body, stale),
            "x-slack-request-timestamp": stale,
        },
    )
    assert resp.status_code == 401


def test_slack_valid_signature_accepted(monkeypatch):
    client = _slack_app(monkeypatch)
    body = json.dumps({"event": {"type": "app_mention", "text": "hi"}}).encode()
    ts = str(int(time.time()))
    resp = client.post(
        "/slack/events",
        content=body,
        headers={
            "x-slack-signature": _sign(body, ts),
            "x-slack-request-timestamp": ts,
        },
    )
    assert resp.status_code == 200


def test_slack_retry_header_short_circuits(monkeypatch):
    client = _slack_app(monkeypatch)
    body = json.dumps({"event": {"type": "app_mention", "text": "hi"}})
    resp = client.post(
        "/slack/events",
        content=body,
        headers={"x-slack-retry-num": "1"},
    )
    assert resp.status_code == 200


def test_instantly_rejects_bad_secret_in_prod(monkeypatch):
    import app.webhooks.instantly as instantly_mod

    monkeypatch.setattr(settings, "ENV", "prod")
    monkeypatch.setattr(settings, "INSTANTLY_WEBHOOK_SECRET", "")
    test_app = FastAPI()
    test_app.include_router(instantly_mod.router)
    client = TestClient(test_app)

    resp = client.post("/webhooks/instantly", json={"event": "reply_received"})
    assert resp.status_code == 401


def test_instantly_rejects_wrong_secret(monkeypatch):
    import app.webhooks.instantly as instantly_mod

    monkeypatch.setattr(settings, "INSTANTLY_WEBHOOK_SECRET", "right")
    test_app = FastAPI()
    test_app.include_router(instantly_mod.router)
    client = TestClient(test_app)

    resp = client.post(
        "/webhooks/instantly",
        json={"event": "reply_received"},
        headers={"x-revcrew-secret": "wrong"},
    )
    assert resp.status_code == 401


@requires_db
def test_intake_validates_and_enqueues(monkeypatch):
    import app.webhooks.intake as intake_mod

    test_app = FastAPI()
    test_app.include_router(intake_mod.router)
    client = TestClient(test_app)

    resp = client.post("/api/leads", json={"email": "not-an-email", "company": "Acme"})
    assert resp.status_code == 422

    resp = client.post("/api/leads", json={"email": "jane@acme.com", "company": "Acme"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
