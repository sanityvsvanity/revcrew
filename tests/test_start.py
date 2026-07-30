"""Tests for the start.py entry point: env merging stays lossless."""

from start import merge_env


class TestMergeEnv:
    def test_updates_existing_key_in_place(self):
        text = "# comment\nDEMO_MODE=true\nENV=dev\n"
        merged = merge_env(text, {"DEMO_MODE": "false"})
        assert "DEMO_MODE=false" in merged
        assert "ENV=dev" in merged
        assert "# comment" in merged

    def test_appends_missing_key(self):
        merged = merge_env("ENV=dev\n", {"SLACK_BOT_TOKEN": "xoxb-1"})
        assert merged.endswith("SLACK_BOT_TOKEN=xoxb-1\n")

    def test_preserves_line_order_and_untouched_values(self):
        text = "A=1\nB=2\nC=3\n"
        merged = merge_env(text, {"B": "changed"})
        assert merged == "A=1\nB=changed\nC=3\n"

    def test_does_not_touch_commented_keys(self):
        text = "# DEMO_MODE=true is the default\nDEMO_MODE=true\n"
        merged = merge_env(text, {"DEMO_MODE": "false"})
        assert "# DEMO_MODE=true is the default" in merged
        assert "\nDEMO_MODE=false" in merged
