"""Tests for the ICP rubric: loading, validation, and prompt rendering."""

import pytest

from app.icp import ICPError, load_icp, render_rubric


class TestLoadIcp:
    def test_shipped_rubric_loads(self):
        icp = load_icp()
        assert round(sum(c["weight"] for c in icp["criteria"].values())) == 100
        assert icp["hard_disqualifiers"]

    def test_missing_file_names_the_path(self, tmp_path):
        with pytest.raises(ICPError, match="not found"):
            load_icp(tmp_path / "nope.yaml")

    def test_invalid_yaml_is_reported(self, tmp_path):
        path = tmp_path / "icp.yaml"
        path.write_text("criteria:\n  - broken\n  key: value\n")
        with pytest.raises(ICPError, match="not valid YAML"):
            load_icp(path)

    def test_weights_must_sum_to_100(self, tmp_path):
        path = tmp_path / "icp.yaml"
        path.write_text(
            "criteria:\n"
            "  fit:\n"
            "    weight: 90\n"
            "    description: only criterion\n"
        )
        with pytest.raises(ICPError, match="sum to 100"):
            load_icp(path)

    def test_criterion_requires_weight_and_description(self, tmp_path):
        path = tmp_path / "icp.yaml"
        path.write_text("criteria:\n  fit:\n    description: no weight\n")
        with pytest.raises(ICPError, match="numeric 'weight'"):
            load_icp(path)

    def test_custom_path_is_used(self, tmp_path):
        path = tmp_path / "custom.yaml"
        path.write_text(
            "criteria:\n"
            "  vertical_fit:\n"
            "    weight: 100\n"
            "    description: dental clinics only\n"
        )
        icp = load_icp(path)
        assert "vertical_fit" in icp["criteria"]


class TestRenderRubric:
    def test_rendered_rubric_reflects_the_file(self):
        icp = load_icp()
        rubric = render_rubric(icp)
        for name, spec in icp["criteria"].items():
            label = name.replace("_", " ").capitalize()
            assert f"{label} ({spec['weight']:g}%)" in rubric
        for item in icp["hard_disqualifiers"]:
            assert item in rubric
        for segment in icp["target_segments"]["exclude"]:
            assert segment in rubric

    def test_qualifier_prompt_carries_the_rubric(self):
        from app.prompts.qualifier import QUALIFIER_INSTRUCTIONS

        icp = load_icp()
        for name in icp["criteria"]:
            label = name.replace("_", " ").capitalize()
            assert label in QUALIFIER_INSTRUCTIONS

    def test_threshold_tier_uses_config(self, tmp_path):
        path = tmp_path / "icp.yaml"
        path.write_text(
            "criteria:\n"
            "  fit:\n"
            "    weight: 100\n"
            "    description: only criterion\n"
            "tiers:\n"
            "  B:\n"
            "    min_score_from_config: true\n"
            "    description: moderate\n"
        )
        from app.config import settings

        rubric = render_rubric(load_icp(path))
        assert f"score >= {settings.ICP_SCORE_THRESHOLD}" in rubric
