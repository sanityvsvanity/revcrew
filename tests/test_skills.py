"""Tests for copilot skills: loading, the read-only guarantee, and wiring."""

from pathlib import Path

import pytest

from app.config import settings
from app.skills import SkillsError, load_skills

SHIPPED = {"call-prep", "objection-handling", "pipeline-review"}

FRONTMATTER = "---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"


def _write_skill(root, name, *, description="A test skill.", body="Do the thing."):
    """Create a minimal valid skill folder and return its path."""
    folder = root / name
    (folder / "references").mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        FRONTMATTER.format(name=name, description=description, body=body)
    )
    return folder


class TestShippedSkills:
    def test_every_shipped_skill_loads(self):
        skills = load_skills()
        assert set(skills.get_skill_names()) == SHIPPED

    def test_descriptions_carry_trigger_phrasing(self):
        # The description is the only text the model sees before deciding to
        # load a skill, so an empty or bare-noun one makes the skill unreachable.
        for skill in load_skills().get_all_skills():
            assert len(skill.description) > 80, skill.name

    def test_references_exist_and_are_not_empty(self):
        for skill in load_skills().get_all_skills():
            assert skill.references, f"{skill.name} ships no references"
            for ref in skill.references:
                path = Path(skill.source_path) / "references" / ref
                assert path.read_text().strip(), f"{skill.name}/{ref} is empty"

    def test_snippet_advertises_names_without_bodies(self):
        snippet = load_skills().get_system_prompt_snippet()
        for name in SHIPPED:
            assert name in snippet
        # Progressive disclosure is the point: bodies stay out of the prompt.
        assert "Gaps stay gaps" not in snippet


class TestReadOnly:
    def test_script_execution_tool_is_not_exposed(self):
        names = {tool.name for tool in load_skills().get_tools()}
        assert names == {"get_skill_instructions", "get_skill_reference"}

    def test_prompt_never_advertises_script_execution(self):
        snippet = load_skills().get_system_prompt_snippet()
        for advertisement in ("get_skill_script", "<scripts>", "Scripts", "Executable"):
            assert advertisement not in snippet, advertisement

    def test_a_skill_shipping_scripts_refuses_to_load(self, tmp_path):
        folder = _write_skill(tmp_path, "with-scripts")
        scripts = folder / "scripts"
        scripts.mkdir()
        (scripts / "run.sh").write_text("#!/bin/bash\necho hello\n")

        with pytest.raises(SkillsError, match="read-only"):
            load_skills(tmp_path)


class TestOptional:
    def test_missing_directory_is_not_an_error(self, tmp_path):
        assert load_skills(tmp_path / "nope") is None

    def test_empty_directory_loads_nothing(self, tmp_path):
        assert load_skills(tmp_path) is None

    def test_disabled_by_config(self, monkeypatch):
        monkeypatch.setattr(settings, "SKILLS_ENABLED", False)
        assert load_skills() is None

    def test_custom_path_is_used(self, tmp_path):
        _write_skill(tmp_path, "custom-play")
        skills = load_skills(tmp_path)
        assert skills.get_skill_names() == ["custom-play"]

    def test_malformed_skill_says_what_to_fix(self, tmp_path):
        folder = tmp_path / "broken"
        folder.mkdir()
        (folder / "SKILL.md").write_text("no frontmatter here\n")

        with pytest.raises(SkillsError, match="frontmatter"):
            load_skills(tmp_path)

    def test_name_must_match_folder(self, tmp_path):
        folder = tmp_path / "folder-name"
        folder.mkdir()
        (folder / "SKILL.md").write_text(
            FRONTMATTER.format(name="different-name", description="x", body="y")
        )

        with pytest.raises(SkillsError):
            load_skills(tmp_path)


class TestCopilotWiring:
    def test_copilot_holds_the_shipped_skills(self):
        from agents.copilot import copilot

        assert copilot.skills is not None
        assert set(copilot.skills.get_skill_names()) == SHIPPED

    def test_pipeline_agents_hold_none(self):
        # Skills are discretionary; the workflow agents' rules are not.
        from agents.outreach_writer import outreach_writer
        from agents.qualifier import qualifier
        from agents.researcher import researcher

        for agent in (researcher, qualifier, outreach_writer):
            assert agent.skills is None

    def test_safety_rules_stay_in_the_prompt(self):
        from app.prompts.copilot import COPILOT_INSTRUCTIONS

        assert "prospect_correspondence" in COPILOT_INSTRUCTIONS
        assert "require human approval" in COPILOT_INSTRUCTIONS
