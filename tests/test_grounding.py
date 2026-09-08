"""The grounding gate: a brief may only cite what the ledger holds."""

from app.research.grounding import REMOVED, ground
from app.schemas import AccountBrief


def _brief(**over):
    base = dict(
        company_name="Acme",
        domain="acme.example",
        snapshot="Acme sells anvils. See https://acme.example/about and https://www.linkedin.com/company/acme.",
        tech_signals=["HubSpot (per https://acme.example/stack)"],
        buying_triggers=["Hiring 3 SDRs (https://boards.greenhouse.io/acme/jobs/1)"],
        key_people=["Jo Bloggs, CEO"],
        talking_points=[
            "Mention the Series A (source: https://news.example/acme-raises)"
        ],
        sources=[
            "https://acme.example/about",
            "https://www.linkedin.com/company/acme",
            "https://acme.example/about/",  # duplicate after normalisation
            "https://news.example/acme-raises?utm_source=x",
        ],
        gaps=["no pricing page found"],
    )
    base.update(over)
    return AccountBrief.model_validate(base)


ALLOWED = {
    "https://acme.example/about",
    "https://boards.greenhouse.io/acme/jobs/1",
    "https://news.example/acme-raises",
}


class TestSources:
    def test_unverified_sources_removed_and_reported(self):
        grounded, report = ground(_brief(), ALLOWED, evidence_records=5)
        assert grounded.sources == [
            "https://acme.example/about",
            "https://news.example/acme-raises?utm_source=x",
        ]
        assert report.sources_removed == ["https://www.linkedin.com/company/acme"]
        assert report.sources_kept == 2

    def test_normalisation_tolerates_www_slash_and_utm(self):
        grounded, _ = ground(
            _brief(sources=["https://WWW.acme.example/about/?utm_medium=e"]),
            ALLOWED,
            evidence_records=1,
        )
        assert grounded.sources == ["https://WWW.acme.example/about/?utm_medium=e"]


class TestProse:
    def test_inline_unverified_links_replaced_sentence_kept(self):
        grounded, report = ground(_brief(), ALLOWED, evidence_records=5)
        assert "acme.example/about" in grounded.snapshot
        assert "linkedin.com" not in grounded.snapshot
        assert REMOVED in grounded.snapshot
        assert "Acme sells anvils" in grounded.snapshot
        assert (
            report.inline_links_removed == 2
        )  # linkedin in snapshot + the stack URL in tech_signals
        # tech_signals held an unverified URL as well
        assert grounded.tech_signals[0].startswith("HubSpot (per [unverified")

    def test_verified_inline_links_untouched(self):
        grounded, _ = ground(_brief(), ALLOWED, evidence_records=5)
        assert grounded.buying_triggers == [
            "Hiring 3 SDRs (https://boards.greenhouse.io/acme/jobs/1)"
        ]
        assert grounded.talking_points == [
            "Mention the Series A (source: https://news.example/acme-raises)"
        ]


class TestNoEvidence:
    def test_claims_moved_to_gaps_when_nothing_was_fetched(self):
        grounded, report = ground(_brief(), set(), evidence_records=0)
        assert (
            grounded.tech_signals == []
            and grounded.buying_triggers == []
            and grounded.key_people == []
        )
        assert report.claims_moved_to_gaps == 3
        assert any(
            g.startswith("unverified (no evidence gathered): key_people")
            for g in grounded.gaps
        )
        assert grounded.gaps[0] == "no pricing page found", (
            "existing gaps are kept first"
        )
        assert grounded.sources == []

    def test_claims_kept_when_evidence_exists_even_if_unlinked(self):
        grounded, report = ground(_brief(), ALLOWED, evidence_records=2)
        assert grounded.key_people == ["Jo Bloggs, CEO"]
        assert report.claims_moved_to_gaps == 0


class TestReport:
    def test_clean_brief_is_clean(self):
        b = _brief(
            snapshot="Acme sells anvils.",
            tech_signals=[],
            sources=["https://acme.example/about"],
        )
        grounded, report = ground(b, ALLOWED, evidence_records=3)
        assert report.clean and grounded.gaps == ["no pricing page found"]
        assert report.line() == "1 source verified"

    def test_line_reads_for_a_rep(self):
        _, report = ground(_brief(), ALLOWED, evidence_records=5)
        assert report.line() == "2 sources verified · 3 unverified links removed"

    def test_gate_never_adds_facts(self):
        before = _brief()
        grounded, _ = ground(before, ALLOWED, evidence_records=5)
        for name in ("tech_signals", "buying_triggers", "key_people", "talking_points"):
            assert len(getattr(grounded, name)) <= len(getattr(before, name))
        assert set(grounded.sources) <= set(before.sources)
