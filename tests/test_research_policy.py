"""Domain policy: the deny list, browser opt-in, host collapsing."""

from app.config import settings
from app.research import policy


class TestDeny:
    def test_linkedin_all_forms(self):
        assert policy.is_denied("https://www.linkedin.com/in/someone")
        assert policy.is_denied("https://au.linkedin.com/company/acme")
        assert policy.is_denied("linkedin.com")

    def test_social_and_review_sites(self):
        for url in (
            "https://x.com/acme",
            "https://www.glassdoor.com.au/Reviews/acme",
            "https://www.facebook.com/acme",
            "https://au.indeed.com/cmp/acme",
        ):
            assert policy.is_denied(url), url

    def test_ordinary_sites_allowed(self):
        assert not policy.is_denied("https://www.acme.example/about")
        assert not policy.is_denied("https://boards.greenhouse.io/acme")

    def test_env_extends_never_removes(self, monkeypatch):
        monkeypatch.setattr(
            settings, "RESEARCH_DENY_DOMAINS", "competitor.example, Other.Example"
        )
        assert policy.is_denied("https://competitor.example/pricing")
        assert policy.is_denied("https://other.example/")
        assert policy.is_denied("https://linkedin.com/")

    def test_deny_reason_names_the_domain(self):
        assert "linkedin.com" in policy.deny_reason("https://www.linkedin.com/in/x")


class TestRegistrable:
    def test_collapses_country_second_level(self):
        assert policy.registrable("www.glassdoor.com.au") == "glassdoor.com.au"
        assert policy.registrable("au.linkedin.com") == "linkedin.com"
        assert policy.registrable("acme.io") == "acme.io"


class TestBrowserOptIn:
    def test_disabled_by_default(self):
        allowed, why = policy.browser_allowed("https://acme.example")
        assert not allowed and "RESEARCH_BROWSER_ENABLED" in why

    def test_enabled_but_unconfigured(self, monkeypatch):
        monkeypatch.setattr(settings, "RESEARCH_BROWSER_ENABLED", True)
        monkeypatch.setattr(settings, "BROWSERBASE_API_KEY", "")
        allowed, why = policy.browser_allowed("https://acme.example")
        assert not allowed and "BROWSERBASE_API_KEY" in why

    def test_never_on_denied_domain(self, monkeypatch):
        monkeypatch.setattr(settings, "RESEARCH_BROWSER_ENABLED", True)
        monkeypatch.setattr(settings, "BROWSERBASE_API_KEY", "bb")
        monkeypatch.setattr(settings, "BROWSERBASE_PROJECT_ID", "p")
        allowed, why = policy.browser_allowed("https://www.linkedin.com/company/acme")
        assert not allowed and "deny list" in why
        assert policy.browser_allowed("https://acme.example/pricing") == (True, "")
