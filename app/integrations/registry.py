"""Integration registry — returns mock or live adapters based on DEMO_MODE."""

from __future__ import annotations

from app.config import settings
from app.integrations.ports import ChatPort, CRMPort, OutreachPort

_crm: CRMPort | None = None
_outreach: OutreachPort | None = None
_chat: ChatPort | None = None


def get_crm() -> CRMPort:
    global _crm
    if _crm is None:
        if settings.DEMO_MODE:
            from app.integrations.mock.hubspot import MockHubSpot

            _crm = MockHubSpot()
        else:
            from app.integrations.live.hubspot import LiveHubSpot

            _crm = LiveHubSpot()
    return _crm


def get_outreach() -> OutreachPort:
    global _outreach
    if _outreach is None:
        if settings.DEMO_MODE:
            from app.integrations.mock.instantly import MockInstantly

            _outreach = MockInstantly()
        else:
            from app.integrations.live.instantly import LiveInstantly

            _outreach = LiveInstantly()
    return _outreach


def get_chat() -> ChatPort:
    global _chat
    if _chat is None:
        # Partial-live rule: in demo mode, if SLACK_BOT_TOKEN is set,
        # use live Slack while CRM/Outreach stay mocked (best video config).
        if settings.DEMO_MODE and not settings.SLACK_BOT_TOKEN:
            from app.integrations.mock.slack import MockSlack

            _chat = MockSlack()
        else:
            from app.integrations.live.slack import LiveSlack

            _chat = LiveSlack()
    return _chat


def reset_registry() -> None:
    """Reset all cached adapters (useful for testing)."""
    global _crm, _outreach, _chat
    _crm = None
    _outreach = None
    _chat = None