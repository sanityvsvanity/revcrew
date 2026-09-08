"""Tier 0 signals are parsed by code from fixtures shaped like the real APIs."""

from app.research.providers import signals as s

GREENHOUSE = {
    "jobs": [
        {
            "title": "Account Executive, ANZ",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            "location": {"name": "Melbourne"},
            "departments": [{"name": "Sales"}],
            "updated_at": "2026-09-01T00:00:00Z",
        },
        {
            "title": "Senior Backend Engineer",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
            "location": {"name": "Remote"},
            "departments": [{"name": "Engineering"}],
            "updated_at": "2026-08-20T00:00:00Z",
        },
        {
            "title": "SDR",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/3",
            "location": {"name": "Sydney"},
            "departments": [{"name": "Sales"}],
            "updated_at": "",
        },
    ]
}
LEVER = [
    {
        "text": "RevOps Lead",
        "hostedUrl": "https://jobs.lever.co/acme/abc",
        "createdAt": 1788220800000,
        "categories": {"location": "Melbourne", "team": "Revenue"},
    },
]
ASHBY = {
    "jobs": [
        {
            "title": "Data Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/acme/xyz",
            "location": "Remote",
            "department": "Engineering",
            "publishedAt": "2026-09-02",
        },
    ]
}
RSS = """<?xml version="1.0"?><rss><channel><title>x</title>
<item><title>Acme raises $12M Series A</title><link>https://news.example/acme-a</link>
<pubDate>Mon, 01 Sep 2026 01:00:00 GMT</pubDate><source url="https://news.example">Startup Daily</source></item>
<item><title>Acme opens Sydney office</title><link>https://news2.example/acme-syd</link>
<pubDate>Tue, 02 Sep 2026 01:00:00 GMT</pubDate></item>
</channel></rss>"""


class TestDetect:
    def test_ats_links_found_in_page_text(self):
        text = (
            "Apply at https://boards.greenhouse.io/acme and https://jobs.lever.co/acme-inc/123 "
            "or https://jobs.ashbyhq.com/Acme.Co/456"
        )
        assert s.detect_ats(text) == [
            ("greenhouse", "acme"),
            ("lever", "acme-inc"),
            ("ashby", "Acme.Co"),
        ]

    def test_embed_board_form(self):
        assert s.detect_ats("boards.greenhouse.io/embed/job_board?for=acmeco") == [
            ("greenhouse", "acmeco")
        ]

    def test_guess_tokens_from_domain_and_name(self):
        assert s.guess_tokens("www.acme-labs.io", "Acme Labs Inc") == [
            "acme-labs",
            "acmelabsinc",
            "acmelabs",
        ]


class TestParse:
    def test_greenhouse(self):
        jobs = s.parse_jobs("greenhouse", GREENHOUSE)
        assert jobs[0] == {
            "title": "Account Executive, ANZ",
            "location": "Melbourne",
            "department": "Sales",
            "url": "https://boards.greenhouse.io/acme/jobs/1",
            "posted": "2026-09-01T00:00:00Z",
        }
        assert s.summarize_jobs(jobs) == {
            "open_roles": 3,
            "sales_roles": 2,
            "engineering_roles": 1,
            "departments": {"Sales": 2, "Engineering": 1},
        }

    def test_lever_epoch_millis(self):
        jobs = s.parse_jobs("lever", LEVER)
        assert jobs[0]["title"] == "RevOps Lead" and jobs[0]["posted"].startswith(
            "2026-09-01"
        )
        assert s.summarize_jobs(jobs)["sales_roles"] == 1

    def test_ashby(self):
        jobs = s.parse_jobs("ashby", ASHBY)
        assert jobs[0]["url"] == "https://jobs.ashbyhq.com/acme/xyz"
        assert s.summarize_jobs(jobs)["engineering_roles"] == 1

    def test_news_rss(self):
        items = s.parse_news_rss(RSS)
        assert items[0] == {
            "title": "Acme raises $12M Series A",
            "url": "https://news.example/acme-a",
            "published": "Mon, 01 Sep 2026 01:00:00 GMT",
            "source": "Startup Daily",
        }
        assert items[1]["source"] == ""

    def test_bad_xml_is_empty_not_exception(self):
        assert s.parse_news_rss("<not xml") == []
