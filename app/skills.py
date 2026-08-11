"""Copilot skills: playbooks the Slack-facing agent loads only when it needs them.

`skills/` (or the directory `SKILLS_PATH` points at) holds Agent Skills folders:
a `SKILL.md` with YAML frontmatter, plus an optional `references/` directory.
Only each skill's name and description sit in the copilot's system prompt. The
body is fetched with a tool call when a request actually matches one, so a deep
playbook costs nothing on the turns that do not need it.

Two rules this module adds on top of agno's loader:

- Skills are read-only. agno ships a `get_skill_script` tool that runs files
  from a skill's `scripts/` directory in a subprocess. The copilot reads
  prospect-authored text, so that tool is removed here, and a skill folder
  carrying a `scripts/` directory refuses to load rather than quietly opening
  an execution path around the write guard.
- Skills are optional. No directory, or `SKILLS_ENABLED=false`, and the copilot
  behaves exactly as it did before skills existed.
"""

from __future__ import annotations

from pathlib import Path

from agno.skills import LocalSkills, Skills, SkillValidationError
from agno.tools.function import Function

from app.config import settings

# agno's snippet documents three access tools and tells the model that skills
# carry executable scripts. Every line that says so is dropped, so the prompt
# never advertises a capability this agent does not have.
_SCRIPT_MARKERS = ("get_skill_script", "<scripts>", "**Scripts**")


class SkillsError(ValueError):
    """A skill folder is malformed, or ships an execution surface."""


class ReadOnlySkills(Skills):
    """Skills with script execution removed, in prompt and in tools."""

    def get_tools(self) -> list[Function]:
        return [tool for tool in super().get_tools() if tool.name != "get_skill_script"]

    def get_system_prompt_snippet(self) -> str:
        snippet = super().get_system_prompt_snippet()
        if not snippet:
            return ""
        kept = [
            line
            for line in snippet.splitlines()
            if not any(marker in line for marker in _SCRIPT_MARKERS)
        ]
        return "\n".join(kept)


def _reject_executable_skills(skills: Skills) -> None:
    """Refuse any skill that ships scripts. Read-only is the whole guarantee."""
    for skill in skills.get_all_skills():
        if skill.scripts:
            raise SkillsError(
                f"Skill '{skill.name}' at {skill.source_path} ships a scripts/ "
                f"directory ({', '.join(map(str, skill.scripts))}). RevCrew skills "
                "are read-only: move the logic into a tool in app/toolkits/, where "
                "the write guard and the audit trail apply, then delete scripts/."
            )


def load_skills(path: Path | None = None) -> Skills | None:
    """Load the copilot's skills. Returns None when there are none to load.

    Raises SkillsError with a fix hint when a folder is present but malformed,
    on the same principle as the ICP rubric: a broken customization stops the
    process instead of silently changing what the agent knows.
    """
    if not settings.SKILLS_ENABLED:
        return None

    path = path or settings.skills_dir_path
    if not path.exists():
        return None

    try:
        skills = ReadOnlySkills(loaders=[LocalSkills(str(path))])
    except SkillValidationError as exc:
        raise SkillsError(
            f"Invalid skill in {path}: {exc}. Every skill folder needs a SKILL.md "
            "opening with YAML frontmatter that sets 'name' (lowercase, matching "
            "the folder name) and 'description'."
        ) from exc

    _reject_executable_skills(skills)

    if not skills.get_all_skills():
        return None
    return skills
