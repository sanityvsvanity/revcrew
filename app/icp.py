"""ICP rubric: load, validate and render the scoring configuration.

`app/icp.yaml` (or the file `ICP_PATH` points at) is the single source of
truth for what the qualifier scores against. The qualifier prompt is rendered
from the loaded rubric, so an edit to the file changes agent behavior on the
next restart. Validation errors say what to fix and where.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.config import settings


class ICPError(ValueError):
    """The ICP rubric file is missing or malformed."""


def load_icp(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the ICP rubric. Raises ICPError with a fix hint."""
    path = path or settings.icp_yaml_path
    if not path.exists():
        raise ICPError(
            f"ICP rubric not found at {path}. "
            "Restore app/icp.yaml or point ICP_PATH at your rubric file."
        )
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ICPError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ICPError(f"{path} must be a YAML mapping of rubric sections.")

    criteria = data.get("criteria")
    if not isinstance(criteria, dict) or not criteria:
        raise ICPError(f"{path}: 'criteria' must be a non-empty mapping.")
    total = 0.0
    for name, spec in criteria.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("weight"), (int, float)):
            raise ICPError(f"{path}: criterion '{name}' needs a numeric 'weight'.")
        if not spec.get("description"):
            raise ICPError(f"{path}: criterion '{name}' needs a 'description'.")
        total += spec["weight"]
    if round(total) != 100:
        raise ICPError(f"{path}: criteria weights must sum to 100, got {total:g}.")

    if not isinstance(data.get("hard_disqualifiers", []), list):
        raise ICPError(f"{path}: 'hard_disqualifiers' must be a list.")

    segments = data.get("target_segments", {})
    if segments and not isinstance(segments, dict):
        raise ICPError(
            f"{path}: 'target_segments' must be a mapping with "
            "'include' and 'exclude' lists."
        )

    return data


def render_rubric(icp: dict[str, Any]) -> str:
    """Render the rubric as the scoring section of the qualifier prompt."""
    lines: list[str] = []

    segments = icp.get("target_segments") or {}
    include = segments.get("include") or []
    exclude = segments.get("exclude") or []
    if include:
        lines.append("Target segments: " + ", ".join(include) + ".")
    if exclude:
        lines.append("Out of scope: " + ", ".join(exclude) + ".")
    if lines:
        lines.append("")

    lines.append("Scoring criteria and weights:")
    for name, spec in icp["criteria"].items():
        label = name.replace("_", " ").capitalize()
        lines.append(f"- {label} ({spec['weight']:g}%): {spec['description']}")

    tiers = icp.get("tiers") or {}
    if tiers:
        lines.append("")
        lines.append("Tier cutoffs:")
        for tier, spec in tiers.items():
            spec = spec or {}
            if spec.get("min_score_from_config"):
                cutoff = f"score >= {settings.ICP_SCORE_THRESHOLD}"
            elif spec.get("min_score") is not None:
                cutoff = f"score >= {spec['min_score']}"
            else:
                cutoff = "below the tiers above"
            desc = spec.get("description", "")
            lines.append(f"- {tier}: {cutoff}" + (f" ({desc})" if desc else ""))

    disqualifiers = icp.get("hard_disqualifiers") or []
    if disqualifiers:
        lines.append("")
        lines.append("Hard disqualifiers (any one of these caps the tier at C):")
        for item in disqualifiers:
            lines.append(f"- {item}")

    return "\n".join(lines)
