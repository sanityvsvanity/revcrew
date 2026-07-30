"""Tests for the research toolkit: provider choice, URL hygiene, formatting."""

from app.toolkits.research_tools import (
    FETCH_MAX_CHARS,
    format_crm_history,
    format_results,
    resolve_research_provider,
    strip_html,
    url_allowed,
)


class TestProviderResolution:
    def test_auto_without_key_is_basic(self):
        assert resolve_research_provider("auto", "") == "basic"

    def test_auto_with_key_is_firecrawl(self):
        assert resolve_research_provider("auto", "fc-123") == "firecrawl"

    def test_firecrawl_without_key_degrades_to_basic(self):
        assert resolve_research_provider("firecrawl", "") == "basic"

    def test_explicit_basic_ignores_key(self):
        assert resolve_research_provider("basic", "fc-123") == "basic"

    def test_unknown_provider_is_basic(self):
        assert resolve_research_provider("bing", "") == "basic"


class TestUrlAllowed:
    def test_public_https_ok(self):
        assert url_allowed("https://example.com/about")

    def test_localhost_blocked(self):
        assert not url_allowed("http://localhost:8000/health")

    def test_private_ip_blocked(self):
        assert not url_allowed("http://192.168.1.1/admin")
        assert not url_allowed("http://10.0.0.5/")
        assert not url_allowed("http://127.0.0.1/")

    def test_non_http_blocked(self):
        assert not url_allowed("file:///etc/passwd")
        assert not url_allowed("ftp://example.com/x")

    def test_internal_suffixes_blocked(self):
        assert not url_allowed("http://db.internal/")
        assert not url_allowed("http://printer.local/")


class TestStripHtml:
    def test_drops_scripts_and_tags(self):
        html = "<html><script>alert(1)</script><body><h1>Acme</h1><p>We sell anvils.</p></body></html>"
        text = strip_html(html)
        assert "Acme" in text
        assert "anvils" in text
        assert "alert" not in text
        assert "<" not in text

    def test_block_tags_become_newlines(self):
        text = strip_html("<p>one</p><p>two</p>")
        assert text == "one\ntwo"


class TestFormatting:
    def test_results_carry_urls(self):
        out = format_results(
            [{"title": "Acme raises $5M", "url": "https://news.example/acme", "snippet": "Series A"}]
        )
        assert "https://news.example/acme" in out
        assert "Acme raises $5M" in out

    def test_empty_results_say_so(self):
        assert "No results" in format_results([])

    def test_no_contact_reads_as_cold(self):
        assert "cold prospect" in format_crm_history(None, [])

    def test_existing_contact_flags_not_cold(self):
        contact = {"id": "c-1", "properties": {"email": "jo@acme.example", "company": "Acme"}}
        timeline = [{"created_at": "2026-03-01", "body": "Discovery call, went well"}]
        out = format_crm_history(contact, timeline)
        assert "NOT cold" in out
        assert "jo@acme.example" in out
        assert "Discovery call" in out

    def test_fetch_cap_is_sane(self):
        assert 1000 < FETCH_MAX_CHARS <= 20000
